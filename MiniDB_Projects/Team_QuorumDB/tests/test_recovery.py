"""Crash-recovery tests: committed work survives, uncommitted work is undone."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from minidb.storage.buffer_pool import BufferPool
from minidb.storage.disk_manager import DiskManager
from minidb.storage.heapfile import HeapFile
from minidb.txn.lock_manager import LockManager
from minidb.txn.transaction import TransactionManager
from minidb.wal.log_manager import LogManager
from minidb.wal.recovery import RecoveryManager


def _open(tmp_path):
    dm = DiskManager(str(tmp_path / "t.db"))
    bp = BufferPool(dm, pool_size=64)
    lm = LogManager(str(tmp_path / "t.wal"))
    bp.set_log_manager(lm)
    tm = TransactionManager(lm, LockManager(), bp)
    return dm, bp, lm, tm


def test_recovery_redo_committed_undo_uncommitted(tmp_path):
    # --- session 1: do work, then "crash" without flushing data pages -----
    dm, bp, lm, tm = _open(tmp_path)
    heap = HeapFile("t", bp, [], register_page=lambda pid: None)

    t1 = tm.begin()
    committed = [heap.insert(f"c{i}".encode(), txn=t1) for i in range(5)]
    tm.commit(t1)                       # flushes the log (commit durable)

    t2 = tm.begin()
    for i in range(3):
        heap.insert(f"d{i}".encode(), txn=t2)
    lm.flush()                          # log durable, but data pages are NOT
    committed_ids = {t1.txn_id}
    loser_ids = {t2.txn_id}
    # Simulate a crash: drop in-memory state without flush_all().
    lm.close()
    del bp, tm, heap, dm, lm

    # --- session 2: reopen and recover ------------------------------------
    dm2 = DiskManager(str(tmp_path / "t.db"))
    bp2 = BufferPool(dm2, pool_size=64)
    lm2 = LogManager(str(tmp_path / "t.wal"))
    bp2.set_log_manager(lm2)

    report = RecoveryManager(lm2, bp2).recover()
    assert report.winners == committed_ids
    assert report.losers == loser_ids
    assert report.redo_count >= 5

    pages = sorted(report.table_pages["t"])
    heap2 = HeapFile("t", bp2, pages, register_page=lambda pid: None)
    survivors = {rec for _, rec in heap2.scan()}
    assert survivors == {b"c0", b"c1", b"c2", b"c3", b"c4"}
    assert not any(r.startswith(b"d") for r in survivors)


def test_recovery_is_idempotent(tmp_path):
    dm, bp, lm, tm = _open(tmp_path)
    heap = HeapFile("t", bp, [], register_page=lambda pid: None)
    t1 = tm.begin()
    rids = [heap.insert(f"row{i}".encode(), txn=t1) for i in range(10)]
    tm.commit(t1)
    lm.close()
    del bp, tm, heap, dm, lm

    dm2 = DiskManager(str(tmp_path / "t.db"))
    bp2 = BufferPool(dm2, pool_size=64)
    lm2 = LogManager(str(tmp_path / "t.wal"))
    bp2.set_log_manager(lm2)
    rm = RecoveryManager(lm2, bp2)
    rm.recover()
    # Running recovery a second time must not corrupt or duplicate anything.
    rm.recover()
    heap2 = HeapFile("t", bp2, list(range(dm2.num_pages)),
                     register_page=lambda pid: None)
    survivors = sorted(rec for _, rec in heap2.scan())
    assert survivors == sorted(f"row{i}".encode() for i in range(10))
