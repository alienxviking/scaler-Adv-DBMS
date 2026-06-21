"""Tests for the lock manager, transactions, abort/undo, and deadlock."""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from minidb.storage.buffer_pool import BufferPool
from minidb.storage.disk_manager import DiskManager
from minidb.storage.heapfile import HeapFile
from minidb.txn.lock_manager import DeadlockError, LockManager, LockMode
from minidb.txn.transaction import TransactionManager, TxnState
from minidb.wal.log_manager import LogManager


def _env(tmp_path):
    dm = DiskManager(str(tmp_path / "t.db"))
    bp = BufferPool(dm, pool_size=16)
    lm = LogManager(str(tmp_path / "t.wal"))
    bp.set_log_manager(lm)
    lk = LockManager()
    tm = TransactionManager(lm, lk, bp)
    return dm, bp, lm, lk, tm


def test_commit_persists_and_abort_undoes(tmp_path):
    dm, bp, lm, lk, tm = _env(tmp_path)
    page_ids = []
    heap = HeapFile("t", bp, page_ids, register_page=lambda pid: None)

    t1 = tm.begin()
    rid_a = heap.insert(b"committed-row", txn=t1)
    tm.commit(t1)
    assert t1.state is TxnState.COMMITTED
    assert heap.get(rid_a) == b"committed-row"

    # An aborted insert must be rolled back.
    t2 = tm.begin()
    rid_b = heap.insert(b"doomed-row", txn=t2)
    assert heap.get(rid_b) == b"doomed-row"
    tm.abort(t2)
    assert t2.state is TxnState.ABORTED
    assert heap.get(rid_b) is None
    # committed row survives
    assert heap.get(rid_a) == b"committed-row"


def test_shared_locks_compatible(tmp_path):
    *_, lk, _ = _env(tmp_path)
    lk.acquire(1, "table:t", LockMode.S)
    lk.acquire(2, "table:t", LockMode.S)  # must not block
    held = lk.snapshot()["table:t"]
    assert held == {1: "S", 2: "S"}


def test_exclusive_blocks_until_release(tmp_path):
    *_, lk, _ = _env(tmp_path)
    lk.acquire(1, "table:t", LockMode.X)
    got = []

    def waiter():
        lk.acquire(2, "table:t", LockMode.S)
        got.append("acquired")

    th = threading.Thread(target=waiter)
    th.start()
    time.sleep(0.1)
    assert got == []          # blocked while txn 1 holds X
    lk.release_all(1)
    th.join(timeout=2)
    assert got == ["acquired"]


def test_deadlock_detected(tmp_path):
    *_, lk, _ = _env(tmp_path)
    lk.acquire(1, "A", LockMode.X)
    lk.acquire(2, "B", LockMode.X)

    started = threading.Event()

    def t1_wants_b():
        started.set()
        lk.acquire(1, "B", LockMode.X)  # will block on txn 2

    th = threading.Thread(target=t1_wants_b)
    th.start()
    started.wait()
    time.sleep(0.1)  # let txn 1 enter the wait queue

    # Txn 2 now wants A -> closes the cycle -> deadlock victim is txn 2.
    with pytest.raises(DeadlockError):
        lk.acquire(2, "A", LockMode.X)

    # Resolve: txn 2 backs off, txn 1 proceeds.
    lk.release_all(2)
    th.join(timeout=2)
    assert not th.is_alive()


def test_upgrade_shared_to_exclusive(tmp_path):
    *_, lk, _ = _env(tmp_path)
    lk.acquire(1, "r", LockMode.S)
    lk.acquire(1, "r", LockMode.X)  # sole holder upgrade
    assert lk.snapshot()["r"] == {1: "X"}
