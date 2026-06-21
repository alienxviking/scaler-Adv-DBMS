"""Disk manager: the only component that touches the data file.

Pages are stored back-to-back in a single file, addressed by a 0-based page
id (``file offset = page_id * PAGE_SIZE``). The disk manager allocates new
pages by extending the file and provides durable ``fsync``-backed writes used
by the buffer pool and the recovery subsystem.
"""

from __future__ import annotations

import os
import threading

from .page import PAGE_SIZE, Page


class DiskManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        # Open for read/write, creating the file if necessary, without
        # truncating an existing database.
        if not os.path.exists(db_path):
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            open(db_path, "wb").close()
        self._f = open(db_path, "r+b", buffering=0)
        self._f.seek(0, os.SEEK_END)
        size = self._f.tell()
        if size % PAGE_SIZE != 0:
            raise IOError(f"corrupt data file: size {size} not a multiple of {PAGE_SIZE}")
        self.num_pages = size // PAGE_SIZE

    def read_page(self, page_id: int) -> Page:
        with self._lock:
            if page_id < 0 or page_id >= self.num_pages:
                raise IndexError(f"page {page_id} out of range (0..{self.num_pages - 1})")
            self._f.seek(page_id * PAGE_SIZE)
            data = self._f.read(PAGE_SIZE)
            if len(data) != PAGE_SIZE:
                raise IOError(f"short read for page {page_id}: {len(data)} bytes")
            return Page.from_bytes(page_id, data)

    def write_page(self, page: Page) -> None:
        with self._lock:
            if page.page_id < 0 or page.page_id >= self.num_pages:
                raise IndexError(f"cannot write unallocated page {page.page_id}")
            self._f.seek(page.page_id * PAGE_SIZE)
            self._f.write(page.to_bytes())

    def allocate_page(self) -> int:
        """Grow the file by one page and return the new page id."""
        with self._lock:
            page_id = self.num_pages
            self._f.seek(page_id * PAGE_SIZE)
            self._f.write(bytes(PAGE_SIZE))
            self.num_pages += 1
            return page_id

    def fsync(self) -> None:
        with self._lock:
            self._f.flush()
            os.fsync(self._f.fileno())

    def close(self) -> None:
        with self._lock:
            if not self._f.closed:
                self._f.flush()
                os.fsync(self._f.fileno())
                self._f.close()

    def __repr__(self) -> str:
        return f"<DiskManager path={self.db_path!r} pages={self.num_pages}>"
