"""Buffer pool: an in-memory cache of pages backed by the disk manager.

The pool owns a fixed number of *frames*. Callers ``fetch_page`` (which pins
the page so it cannot be evicted) and must ``unpin_page`` when done, flagging
whether they dirtied it. When every frame is occupied and a new page is
needed, a **CLOCK** replacement policy chooses an unpinned victim.

Two correctness rules are enforced here:

* **Write-ahead logging (WAL):** before a dirty page is written back to disk
  the log must be durable up to that page's LSN. The pool calls the optional
  log manager's ``flush(page.lsn)`` hook before every page write.
* **No eviction of pinned pages:** a page in active use by a transaction is
  never written out or replaced.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from .disk_manager import DiskManager
from .page import Page


class _Frame:
    __slots__ = ("page", "pin_count", "dirty", "ref_bit")

    def __init__(self) -> None:
        self.page: Optional[Page] = None
        self.pin_count: int = 0
        self.dirty: bool = False
        self.ref_bit: bool = False


class BufferPool:
    def __init__(self, disk_manager: DiskManager, pool_size: int = 64):
        if pool_size < 1:
            raise ValueError("pool_size must be >= 1")
        self.disk = disk_manager
        self.pool_size = pool_size
        self._frames: List[_Frame] = [_Frame() for _ in range(pool_size)]
        self._page_table: Dict[int, int] = {}      # page_id -> frame index
        self._free: List[int] = list(range(pool_size))
        self._clock_hand = 0
        self._lock = threading.RLock()
        self._log_manager = None                    # set by the engine, optional

        # Bookkeeping for the benchmark report.
        self.stats = {"hits": 0, "misses": 0, "evictions": 0, "writes": 0}

    def set_log_manager(self, log_manager) -> None:
        """Wire in the WAL so dirty pages obey the write-ahead rule on flush."""
        self._log_manager = log_manager

    # -- victim selection ---------------------------------------------------
    def _pick_victim(self) -> int:
        """CLOCK sweep: skip pinned frames, clear reference bits as we go."""
        for _ in range(2 * self.pool_size):
            idx = self._clock_hand
            self._clock_hand = (self._clock_hand + 1) % self.pool_size
            frame = self._frames[idx]
            if frame.pin_count > 0:
                continue
            if frame.ref_bit:
                frame.ref_bit = False
                continue
            return idx
        raise RuntimeError("buffer pool exhausted: all pages are pinned")

    def _flush_frame(self, frame: _Frame) -> None:
        page = frame.page
        assert page is not None
        if frame.dirty:
            if self._log_manager is not None:
                # Write-ahead rule: log durable up to this page's LSN first.
                self._log_manager.flush(page.lsn)
            self.disk.write_page(page)
            frame.dirty = False
            self.stats["writes"] += 1

    def _free_frame(self) -> int:
        """Return an unused frame index, evicting a victim if necessary."""
        if self._free:
            return self._free.pop()
        victim = self._pick_victim()
        frame = self._frames[victim]
        self._flush_frame(frame)
        assert frame.page is not None
        del self._page_table[frame.page.page_id]
        frame.page = None
        frame.dirty = False
        frame.ref_bit = False
        self.stats["evictions"] += 1
        return victim

    # -- public API ---------------------------------------------------------
    def fetch_page(self, page_id: int) -> Page:
        """Return the page for *page_id*, pinning it. Caller must unpin."""
        with self._lock:
            if page_id in self._page_table:
                frame = self._frames[self._page_table[page_id]]
                frame.pin_count += 1
                frame.ref_bit = True
                self.stats["hits"] += 1
                return frame.page  # type: ignore[return-value]

            self.stats["misses"] += 1
            idx = self._free_frame()
            page = self.disk.read_page(page_id)
            frame = self._frames[idx]
            frame.page = page
            frame.pin_count = 1
            frame.dirty = False
            frame.ref_bit = True
            self._page_table[page_id] = idx
            return page

    def new_page(self) -> Page:
        """Allocate a fresh page on disk, load it into the pool, pin it."""
        with self._lock:
            page_id = self.disk.allocate_page()
            idx = self._free_frame()
            page = Page(page_id)
            frame = self._frames[idx]
            frame.page = page
            frame.pin_count = 1
            frame.dirty = True          # newly allocated content must be written
            frame.ref_bit = True
            self._page_table[page_id] = idx
            return page

    def unpin_page(self, page_id: int, is_dirty: bool) -> None:
        with self._lock:
            if page_id not in self._page_table:
                return
            frame = self._frames[self._page_table[page_id]]
            if is_dirty:
                frame.dirty = True
            if frame.pin_count > 0:
                frame.pin_count -= 1

    def flush_page(self, page_id: int) -> None:
        with self._lock:
            if page_id in self._page_table:
                self._flush_frame(self._frames[self._page_table[page_id]])

    def flush_all(self) -> None:
        """Write every dirty page back to disk (used at checkpoint/shutdown)."""
        with self._lock:
            for frame in self._frames:
                if frame.page is not None:
                    self._flush_frame(frame)

    def is_cached(self, page_id: int) -> bool:
        with self._lock:
            return page_id in self._page_table

    def hit_ratio(self) -> float:
        total = self.stats["hits"] + self.stats["misses"]
        return self.stats["hits"] / total if total else 0.0

    def __repr__(self) -> str:
        return (f"<BufferPool size={self.pool_size} "
                f"resident={len(self._page_table)} "
                f"hit_ratio={self.hit_ratio():.2f}>")
