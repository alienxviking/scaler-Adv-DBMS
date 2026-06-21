"""Transactions and the transaction manager.

A ``Transaction`` is the unit of atomicity. It logs each change it makes
(maintaining the per-transaction prev-LSN chain used for undo), acquires locks
through the lock manager, and tracks the records it must compensate if it
aborts.

The ``TransactionManager`` drives BEGIN/COMMIT/ABORT:

* **commit** appends a COMMIT record and flushes the log up to it — once that
  fsync returns, the transaction is durable even across a crash (no-force on
  data pages; redo will reconstruct them).
* **abort** walks the transaction's changes in reverse, applies the undo image
  to each page, and writes a compensation log record (CLR) for each, then logs
  ABORT. This is the same undo logic recovery uses for loser transactions.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Dict, List, Optional

from ..storage.buffer_pool import BufferPool
from ..wal import page_ops
from ..wal.log_manager import LogManager
from ..wal.log_record import LogRecord, LogType
from .lock_manager import LockManager, LockMode


class TxnState(Enum):
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


class Transaction:
    def __init__(self, txn_id: int, manager: "TransactionManager"):
        self.txn_id = txn_id
        self._mgr = manager
        self.state = TxnState.ACTIVE
        self.prev_lsn = -1
        self._undo: List[LogRecord] = []   # data records to compensate on abort

    # -- locking ------------------------------------------------------------
    def acquire(self, resource: str, mode: LockMode) -> None:
        self._mgr.lock_manager.acquire(self.txn_id, resource, mode)

    def lock_shared(self, resource: str) -> None:
        self.acquire(resource, LockMode.S)

    def lock_exclusive(self, resource: str) -> None:
        self.acquire(resource, LockMode.X)

    # -- logging (called by the heap file) ----------------------------------
    def _append(self, rec: LogRecord, undoable: bool) -> int:
        rec.prev_lsn = self.prev_lsn
        lsn = self._mgr.log_manager.append(rec)
        self.prev_lsn = lsn
        if undoable:
            self._undo.append(rec)
        return lsn

    def log_insert(self, table: str, page_id: int, slot_no: int, after: bytes) -> int:
        return self._append(LogRecord(type=LogType.INSERT, txn_id=self.txn_id,
                                      table=table, page_id=page_id,
                                      slot_no=slot_no, after=after), undoable=True)

    def log_delete(self, table: str, page_id: int, slot_no: int, before: bytes) -> int:
        return self._append(LogRecord(type=LogType.DELETE, txn_id=self.txn_id,
                                      table=table, page_id=page_id,
                                      slot_no=slot_no, before=before), undoable=True)

    def log_update(self, table: str, page_id: int, slot_no: int,
                   before: bytes, after: bytes) -> int:
        return self._append(LogRecord(type=LogType.UPDATE, txn_id=self.txn_id,
                                      table=table, page_id=page_id, slot_no=slot_no,
                                      before=before, after=after), undoable=True)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<Txn {self.txn_id} {self.state.value}>"


class TransactionManager:
    def __init__(self, log_manager: LogManager, lock_manager: LockManager,
                 buffer_pool: BufferPool):
        self.log_manager = log_manager
        self.lock_manager = lock_manager
        self.bp = buffer_pool
        self._next_id = 1
        self._lock = threading.Lock()
        self.active: Dict[int, Transaction] = {}

    def begin(self) -> Transaction:
        with self._lock:
            txn_id = self._next_id
            self._next_id += 1
        txn = Transaction(txn_id, self)
        txn.prev_lsn = self.log_manager.append(
            LogRecord(type=LogType.BEGIN, txn_id=txn_id))
        with self._lock:
            self.active[txn_id] = txn
        return txn

    def commit(self, txn: Transaction) -> None:
        if txn.state is not TxnState.ACTIVE:
            return
        rec = LogRecord(type=LogType.COMMIT, txn_id=txn.txn_id, prev_lsn=txn.prev_lsn)
        lsn = self.log_manager.append(rec)
        txn.prev_lsn = lsn
        self.log_manager.flush(lsn)          # commit is durable here
        self.lock_manager.release_all(txn.txn_id)
        txn.state = TxnState.COMMITTED
        with self._lock:
            self.active.pop(txn.txn_id, None)

    def abort(self, txn: Transaction) -> None:
        if txn.state is not TxnState.ACTIVE:
            return
        # Undo this transaction's changes in reverse, writing a CLR per change.
        for rec in reversed(txn._undo):
            page = self.bp.fetch_page(rec.page_id)
            try:
                page_ops.undo(rec, page)
                clr = LogRecord(type=LogType.CLR, txn_id=txn.txn_id,
                                table=rec.table, page_id=rec.page_id,
                                slot_no=rec.slot_no, prev_lsn=txn.prev_lsn,
                                undo_next_lsn=rec.prev_lsn)
                clr_lsn = self.log_manager.append(clr)
                txn.prev_lsn = clr_lsn
                page.lsn = clr_lsn
            finally:
                self.bp.unpin_page(rec.page_id, True)
        self.log_manager.append(LogRecord(type=LogType.ABORT, txn_id=txn.txn_id,
                                          prev_lsn=txn.prev_lsn))
        self.lock_manager.release_all(txn.txn_id)
        txn.state = TxnState.ABORTED
        with self._lock:
            self.active.pop(txn.txn_id, None)

    def active_txn_ids(self) -> List[int]:
        with self._lock:
            return sorted(self.active)
