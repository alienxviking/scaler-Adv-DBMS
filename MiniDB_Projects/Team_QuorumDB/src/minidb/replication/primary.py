"""Primary node (Track D).

Wraps a writable ``Database`` and streams its redo log to connected replicas.
When a replica connects, the primary first sends a catalog snapshot and the
full log so the replica catches up, then continuously pushes new records as
the workload generates them. Per-replica acknowledged LSNs are tracked so the
demo can report replication lag.

``replicate_to`` provides the same streaming in-process (no sockets), which the
tests and benchmarks use for determinism.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Dict, List

from ..engine import Database
from . import protocol


class Primary:
    def __init__(self, db: Database):
        self.db = db
        self._server: socket.socket = None  # type: ignore[assignment]
        self._accept_thread: threading.Thread = None  # type: ignore[assignment]
        self._running = False
        self._lock = threading.Lock()
        self._acks: Dict[str, int] = {}     # replica peer name -> acked LSN
        self.port = 0

    # -- in-process streaming (deterministic, used by tests/benchmarks) -----
    def replicate_to(self, replica, from_lsn: int = 0) -> int:
        """Ship every record after *from_lsn* to *replica*; return new LSN."""
        records = self.db.log.records_since(from_lsn)
        if not records:
            return from_lsn
        return replica.apply_batch(records, self.db.catalog.to_doc())

    # -- socket server ------------------------------------------------------
    def serve(self, host: str = "127.0.0.1", port: int = 0) -> int:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen(8)
        self.port = self._server.getsockname()[1]
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        return self.port

    def _accept_loop(self) -> None:
        self._server.settimeout(0.5)
        while self._running:
            try:
                client, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve_client, args=(client, addr),
                             daemon=True).start()

    def _serve_client(self, client: socket.socket, addr) -> None:
        peer = f"{addr[0]}:{addr[1]}"
        client.settimeout(0.5)
        last_sent = 0
        try:
            self._push(client, from_lsn=0)
            last_sent = self.db.log.current_lsn
            while self._running:
                # Drain any acks the replica sent.
                try:
                    msg_type, payload = protocol.recv_msg(client)
                    if msg_type == protocol.ACK:
                        with self._lock:
                            self._acks[peer] = protocol.decode_ack(payload)
                except socket.timeout:
                    pass
                # Push any new records.
                current = self.db.log.current_lsn
                if current > last_sent:
                    self._push(client, from_lsn=last_sent)
                    last_sent = current
                else:
                    protocol.send_msg(client, protocol.HEARTBEAT)
        except (ConnectionError, OSError):
            pass
        finally:
            with self._lock:
                self._acks.pop(peer, None)
            try:
                client.close()
            except OSError:
                pass

    def _push(self, client: socket.socket, from_lsn: int) -> None:
        records = self.db.log.records_since(from_lsn)
        if not records:
            return
        doc = json.dumps(self.db.catalog.to_doc()).encode("utf-8")
        protocol.send_msg(client, protocol.CATALOG, doc)
        protocol.send_msg(client, protocol.RECORDS, protocol.encode_records(records))

    def replication_lag(self) -> Dict[str, int]:
        """Per-replica lag = primary LSN - replica's acked LSN."""
        current = self.db.log.current_lsn
        with self._lock:
            return {peer: current - acked for peer, acked in self._acks.items()}

    def stop(self) -> None:
        self._running = False
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
