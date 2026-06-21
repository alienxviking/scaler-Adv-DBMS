"""Heap file: an unordered collection of records spread across data pages.

A table's tuples live in a heap file — a set of pages owned by that table.
The list of page ids is held by the catalog (so it is persisted with the rest
of the table's metadata); the heap file operates on that shared list and calls
back into the catalog whenever it allocates a new page.

Inserts find the first page with enough free space (tracked by an in-memory
free-space map to avoid I/O), allocating a new page only when none has room.
Deletes tombstone the slot, keeping RIDs stable for the indexes.

When a transaction context is supplied, every mutation is logged through the
write-ahead log *before* the page is unpinned, and the returned LSN is stamped
on the page header — this is what makes both crash recovery and replication
(Track D) able to replay the change deterministically.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterator, List, Optional, Tuple

from .buffer_pool import BufferPool
from .page import SLOT_SIZE, Page
from .rid import RID


class HeapFile:
    def __init__(
        self,
        name: str,
        buffer_pool: BufferPool,
        page_ids: List[int],
        register_page: Callable[[int], None],
    ):
        self.name = name
        self.bp = buffer_pool
        self.page_ids = page_ids            # shared, owned by the catalog
        self._register_page = register_page
        self._free: Dict[int, int] = {}     # page_id -> free bytes (lazy cache)

    # -- free-space tracking ------------------------------------------------
    def _free_of(self, page_id: int) -> int:
        cached = self._free.get(page_id)
        if cached is not None:
            return cached
        page = self.bp.fetch_page(page_id)
        try:
            free = page.free_space()
        finally:
            self.bp.unpin_page(page_id, False)
        self._free[page_id] = free
        return free

    # -- mutations ----------------------------------------------------------
    def insert(self, record: bytes, txn=None) -> RID:
        need = len(record) + SLOT_SIZE      # worst case: a fresh slot
        for pid in self.page_ids:
            if self._free_of(pid) < need:
                continue
            page = self.bp.fetch_page(pid)
            try:
                slot = page.insert_record(record)
                if slot is None:
                    self._free[pid] = page.free_space()
                    self.bp.unpin_page(pid, False)
                    continue
                rid = RID(pid, slot)
                if txn is not None:
                    lsn = txn.log_insert(self.name, pid, slot, record)
                    page.lsn = lsn
                self._free[pid] = page.free_space()
                self.bp.unpin_page(pid, True)
                return rid
            except Exception:
                self.bp.unpin_page(pid, False)
                raise

        # No page had room — grow the heap.
        page = self.bp.new_page()
        pid = page.page_id
        try:
            self.page_ids.append(pid)
            self._register_page(pid)
            slot = page.insert_record(record)
            assert slot is not None, "fresh page rejected a record"
            rid = RID(pid, slot)
            if txn is not None:
                lsn = txn.log_insert(self.name, pid, slot, record)
                page.lsn = lsn
            self._free[pid] = page.free_space()
            return rid
        finally:
            self.bp.unpin_page(pid, True)

    def delete(self, rid: RID, txn=None) -> bool:
        page = self.bp.fetch_page(rid.page_id)
        dirtied = False
        try:
            before = page.get_record(rid.slot_no)
            if before is None:
                return False
            page.delete_record(rid.slot_no)
            dirtied = True
            if txn is not None:
                lsn = txn.log_delete(self.name, rid.page_id, rid.slot_no, before)
                page.lsn = lsn
            self._free[rid.page_id] = page.free_space()
            return True
        finally:
            self.bp.unpin_page(rid.page_id, dirtied)

    # -- reads --------------------------------------------------------------
    def get(self, rid: RID) -> Optional[bytes]:
        page = self.bp.fetch_page(rid.page_id)
        try:
            return page.get_record(rid.slot_no)
        finally:
            self.bp.unpin_page(rid.page_id, False)

    def scan(self) -> Iterator[Tuple[RID, bytes]]:
        """Sequential scan: yield ``(RID, record_bytes)`` for every live tuple."""
        for pid in list(self.page_ids):
            page = self.bp.fetch_page(pid)
            try:
                records = list(page.iter_records())
            finally:
                self.bp.unpin_page(pid, False)
            for slot, rec in records:
                yield RID(pid, slot), rec

    def num_data_pages(self) -> int:
        return len(self.page_ids)

    def __repr__(self) -> str:
        return f"<HeapFile {self.name!r} pages={len(self.page_ids)}>"
