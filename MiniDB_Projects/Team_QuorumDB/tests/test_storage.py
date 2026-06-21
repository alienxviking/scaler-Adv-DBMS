"""Tests for the storage engine: page, disk manager, buffer pool, heap file."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from minidb.storage.buffer_pool import BufferPool
from minidb.storage.disk_manager import DiskManager
from minidb.storage.heapfile import HeapFile
from minidb.storage.page import PAGE_SIZE, Page


# -- Page ------------------------------------------------------------------
def test_page_insert_get_delete():
    p = Page(0)
    s0 = p.insert_record(b"hello")
    s1 = p.insert_record(b"world!!")
    assert (s0, s1) == (0, 1)
    assert p.get_record(s0) == b"hello"
    assert p.get_record(s1) == b"world!!"
    assert p.delete_record(s0) is True
    assert p.get_record(s0) is None
    # live records only
    assert [r for _, r in p.iter_records()] == [b"world!!"]


def test_page_slot_reuse_after_delete():
    p = Page(0)
    s0 = p.insert_record(b"aaaa")
    p.insert_record(b"bbbb")
    p.delete_record(s0)
    s2 = p.insert_record(b"cc")
    assert s2 == s0  # the tombstoned slot is reused


def test_page_full():
    p = Page(0)
    big = b"x" * (PAGE_SIZE // 2)
    assert p.insert_record(big) is not None
    assert p.insert_record(big) is None  # second one will not fit


def test_page_roundtrip_and_lsn():
    p = Page(7)
    p.insert_record(b"persist me")
    p.lsn = 42
    raw = p.to_bytes()
    q = Page.from_bytes(7, raw)
    assert q.lsn == 42
    assert q.get_record(0) == b"persist me"


def test_page_apply_replays_to_exact_slot():
    p = Page(0)
    # Replay an insert that targets slot 3 even though the page is empty.
    p.apply_insert(3, b"replayed")
    assert p.num_slots == 4
    assert p.get_record(3) == b"replayed"
    assert p.get_record(0) is None
    p.apply_delete(3)
    assert p.get_record(3) is None


# -- DiskManager + BufferPool ---------------------------------------------
def test_disk_manager_alloc_and_persist(tmp_path):
    path = str(tmp_path / "t.db")
    dm = DiskManager(path)
    pid = dm.allocate_page()
    page = Page(pid)
    page.insert_record(b"durable")
    dm.write_page(page)
    dm.close()

    dm2 = DiskManager(path)
    assert dm2.num_pages == 1
    got = dm2.read_page(pid)
    assert got.get_record(0) == b"durable"
    dm2.close()


def test_buffer_pool_hit_and_eviction(tmp_path):
    dm = DiskManager(str(tmp_path / "t.db"))
    bp = BufferPool(dm, pool_size=2)
    p0 = bp.new_page()
    p0.insert_record(b"zero")
    bp.unpin_page(p0.page_id, True)
    p1 = bp.new_page()
    bp.unpin_page(p1.page_id, True)

    # Re-fetch p0: served from cache (hit).
    again = bp.fetch_page(p0.page_id)
    assert again.get_record(0) == b"zero"
    bp.unpin_page(p0.page_id, False)
    assert bp.stats["hits"] >= 1

    # Force eviction by touching a third page in a size-2 pool.
    p2 = bp.new_page()
    bp.unpin_page(p2.page_id, True)
    assert bp.stats["evictions"] >= 1

    # Evicted dirty pages must have been written back and survive a re-read.
    bp.flush_all()
    assert bp.fetch_page(p0.page_id).get_record(0) == b"zero"


def test_buffer_pool_rejects_when_all_pinned(tmp_path):
    dm = DiskManager(str(tmp_path / "t.db"))
    bp = BufferPool(dm, pool_size=1)
    bp.new_page()  # pinned, never unpinned
    with pytest.raises(RuntimeError):
        bp.new_page()


# -- HeapFile --------------------------------------------------------------
def _make_heap(tmp_path):
    dm = DiskManager(str(tmp_path / "t.db"))
    bp = BufferPool(dm, pool_size=8)
    page_ids: list[int] = []
    heap = HeapFile("t", bp, page_ids, register_page=lambda pid: None)
    return heap, bp


def test_heapfile_insert_scan_delete(tmp_path):
    heap, _ = _make_heap(tmp_path)
    rids = [heap.insert(f"row-{i}".encode()) for i in range(50)]
    seen = {rid: rec for rid, rec in heap.scan()}
    assert len(seen) == 50
    assert seen[rids[10]] == b"row-10"

    assert heap.delete(rids[10]) is True
    assert heap.get(rids[10]) is None
    assert heap.delete(rids[10]) is False  # already gone
    assert len(list(heap.scan())) == 49


def test_heapfile_spills_to_multiple_pages(tmp_path):
    heap, _ = _make_heap(tmp_path)
    big = b"y" * 500
    for _ in range(40):
        heap.insert(big)
    assert heap.num_data_pages() > 1
    assert len(list(heap.scan())) == 40
