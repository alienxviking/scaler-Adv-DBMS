"""Replica node (Track D).

A replica is an ordinary ``Database`` that, instead of accepting writes,
*follows* a primary by applying the primary's redo stream. Because replication
reuses the WAL records and the exact ``page_ops.redo`` logic, a replica is
essentially "continuous recovery" against a live log feed.

Applying a batch:
  1. sync the schema from the primary's catalog snapshot,
  2. make sure every referenced page exists locally (allocate empties to match
     the primary's page numbering),
  3. redo each new record onto its page (guarded by the page LSN),
  4. rebuild the affected indexes so local reads are consistent.

On primary failure the replica can be **promoted**: it stops following and
begins accepting writes, which is the failover path the demo exercises.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import List, Optional

from ..engine import Database
from ..wal import page_ops
from ..wal.log_record import LogRecord, LogType
from . import protocol

_DATA = (LogType.INSERT, LogType.DELETE, LogType.UPDATE)


class Replica:
    def __init__(self, db: Database):
        self.db = db
        self.applied_lsn = 0
        self._lock = threading.RLock()
        self._following = False
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._catalog_doc: Optional[dict] = None
        self.primary_down = False
        self.promoted = False

    # -- core apply (also used in-process by tests/benchmarks) --------------
    def apply_batch(self, records: List[LogRecord], catalog_doc: Optional[dict]) -> int:
        with self._lock:
            if self.promoted:
                return self.applied_lsn      # no longer following
            if catalog_doc is not None:
                self._catalog_doc = catalog_doc
                self.db.catalog.load_from_doc(catalog_doc)
                self._ensure_catalog_pages()

            touched = set()
            for rec in records:
                if rec.lsn <= self.applied_lsn:
                    continue
                if rec.type in _DATA:
                    self._ensure_page(rec.page_id)
                    page = self.db.buffer_pool.fetch_page(rec.page_id)
                    dirty = False
                    try:
                        if page.lsn < rec.lsn:
                            page_ops.redo(rec, page)
                            page.lsn = rec.lsn
                            dirty = True
                    finally:
                        self.db.buffer_pool.unpin_page(rec.page_id, dirty)
                    touched.add(rec.table)
                self.applied_lsn = max(self.applied_lsn, rec.lsn)

            # Refresh indexes so reads on the replica are consistent.
            if catalog_doc is not None:
                self.db.catalog.rebuild_all_indexes()
            else:
                for t in touched:
                    if self.db.catalog.has_table(t):
                        self.db.catalog.rebuild_indexes(t)
            return self.applied_lsn

    def _ensure_page(self, page_id: int) -> None:
        while self.db.disk.num_pages <= page_id:
            self.db.disk.allocate_page()

    def _ensure_catalog_pages(self) -> None:
        max_pid = -1
        for t in self.db.catalog.tables.values():
            for pid in t.page_ids:
                max_pid = max(max_pid, pid)
        if max_pid >= 0:
            self._ensure_page(max_pid)

    # -- read path ----------------------------------------------------------
    def query(self, sql: str):
        """Read-only query against the replica's local copy."""
        return self.db.connect().execute(sql)

    # -- streaming client ---------------------------------------------------
    def start_following(self, host: str, port: int) -> None:
        self._following = True
        self._thread = threading.Thread(target=self._follow_loop, args=(host, port),
                                        daemon=True)
        self._thread.start()

    def _follow_loop(self, host: str, port: int) -> None:
        try:
            self._sock = socket.create_connection((host, port), timeout=5)
            self._sock.settimeout(1.0)
            while self._following and not self.promoted:
                try:
                    msg_type, payload = protocol.recv_msg(self._sock)
                except socket.timeout:
                    continue
                if msg_type == protocol.CATALOG:
                    self._catalog_doc = json.loads(payload.decode("utf-8"))
                elif msg_type == protocol.RECORDS:
                    records = protocol.decode_records(payload)
                    lsn = self.apply_batch(records, self._catalog_doc)
                    protocol.send_msg(self._sock, protocol.ACK, protocol.encode_ack(lsn))
                elif msg_type == protocol.HEARTBEAT:
                    protocol.send_msg(self._sock, protocol.ACK,
                                      protocol.encode_ack(self.applied_lsn))
        except (ConnectionError, OSError):
            self.primary_down = True          # primary unreachable -> failover candidate
        finally:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass

    def promote(self) -> None:
        """Failover: stop following and accept writes locally."""
        with self._lock:
            self.promoted = True
            self._following = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass

    def stop(self) -> None:
        self._following = False
        if self._thread is not None:
            self._thread.join(timeout=2)
