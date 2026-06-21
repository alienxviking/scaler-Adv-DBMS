"""Slotted-page layout.

A page is a fixed-size byte buffer (``PAGE_SIZE``) that stores variable-length
records using a *slot directory*. This is the classic design used by most
disk-oriented databases: the slot directory grows forward from the page
header while record bytes grow backward from the end of the page, with free
space in the middle.

    +----------------------------------------------------------+
    | header | slot 0 | slot 1 | ...   ->        free          |
    |        |--------- slot directory ---------|              |
    |                          free space      <- ... rec1 rec0|
    +----------------------------------------------------------+

Each *slot* is a (offset, length) pair. A length of 0 marks a tombstone left
behind by a deleted record; the slot index (and therefore every RID that
points at it) stays stable for the life of the record, which is exactly what
the B+Tree indexes rely on. Deleted slots are reused by later inserts before
the directory is grown.

The first 8 bytes of the header hold the page LSN, used by the recovery
subsystem to decide whether a logged update has already been applied.
"""

from __future__ import annotations

import struct
from typing import Iterator, Optional, Tuple

PAGE_SIZE = 4096

# Header: pageLSN (uint64), num_slots (uint16), free_space_end (uint16)
_HEADER_FMT = "<QHH"
HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 12 bytes

# Slot directory entry: offset (uint16), length (uint16)
_SLOT_FMT = "<HH"
SLOT_SIZE = struct.calcsize(_SLOT_FMT)  # 4 bytes

INVALID_PAGE_ID = -1


class Page:
    """A single fixed-size page holding variable-length records."""

    __slots__ = ("page_id", "data")

    def __init__(self, page_id: int, data: Optional[bytearray] = None):
        self.page_id = page_id
        if data is None:
            self.data = bytearray(PAGE_SIZE)
            self._set_header(lsn=0, num_slots=0, free_end=PAGE_SIZE)
        else:
            if len(data) != PAGE_SIZE:
                raise ValueError(f"page data must be {PAGE_SIZE} bytes, got {len(data)}")
            self.data = bytearray(data)

    # -- header accessors ---------------------------------------------------
    def _get_header(self) -> Tuple[int, int, int]:
        return struct.unpack_from(_HEADER_FMT, self.data, 0)

    def _set_header(self, lsn: int, num_slots: int, free_end: int) -> None:
        struct.pack_into(_HEADER_FMT, self.data, 0, lsn, num_slots, free_end)

    @property
    def lsn(self) -> int:
        return self._get_header()[0]

    @lsn.setter
    def lsn(self, value: int) -> None:
        _, num_slots, free_end = self._get_header()
        self._set_header(value, num_slots, free_end)

    @property
    def num_slots(self) -> int:
        return self._get_header()[1]

    @property
    def free_end(self) -> int:
        return self._get_header()[2]

    # -- slot helpers -------------------------------------------------------
    def _slot_pos(self, slot_no: int) -> int:
        return HEADER_SIZE + slot_no * SLOT_SIZE

    def _get_slot(self, slot_no: int) -> Tuple[int, int]:
        return struct.unpack_from(_SLOT_FMT, self.data, self._slot_pos(slot_no))

    def _set_slot(self, slot_no: int, offset: int, length: int) -> None:
        struct.pack_into(_SLOT_FMT, self.data, self._slot_pos(slot_no), offset, length)

    # -- free-space accounting ---------------------------------------------
    def free_space(self) -> int:
        """Bytes available for a *new* record that also needs a new slot."""
        _, num_slots, free_end = self._get_header()
        directory_end = HEADER_SIZE + num_slots * SLOT_SIZE
        return free_end - directory_end

    def _find_empty_slot(self) -> Optional[int]:
        _, num_slots, _ = self._get_header()
        for i in range(num_slots):
            _, length = self._get_slot(i)
            if length == 0:
                return i
        return None

    # -- record operations --------------------------------------------------
    def insert_record(self, record: bytes) -> Optional[int]:
        """Insert *record*; return its slot number, or ``None`` if it won't fit."""
        lsn, num_slots, free_end = self._get_header()
        rec_len = len(record)
        if rec_len == 0 or rec_len > 0xFFFF:
            raise ValueError("record length must be in 1..65535")

        reuse = self._find_empty_slot()
        # An empty slot avoids growing the directory.
        slot_overhead = 0 if reuse is not None else SLOT_SIZE
        if rec_len + slot_overhead > self.free_space():
            return None

        new_offset = free_end - rec_len
        self.data[new_offset:new_offset + rec_len] = record

        if reuse is not None:
            self._set_slot(reuse, new_offset, rec_len)
            slot_no = reuse
        else:
            slot_no = num_slots
            self._set_slot(slot_no, new_offset, rec_len)
            num_slots += 1
        self._set_header(lsn, num_slots, new_offset)
        return slot_no

    def get_record(self, slot_no: int) -> Optional[bytes]:
        """Return the record bytes, or ``None`` if the slot is empty/deleted."""
        if slot_no < 0 or slot_no >= self.num_slots:
            return None
        offset, length = self._get_slot(slot_no)
        if length == 0:
            return None
        return bytes(self.data[offset:offset + length])

    def delete_record(self, slot_no: int) -> bool:
        """Tombstone a record. The slot index stays valid (length set to 0)."""
        if slot_no < 0 or slot_no >= self.num_slots:
            return False
        offset, length = self._get_slot(slot_no)
        if length == 0:
            return False
        self._set_slot(slot_no, offset, 0)
        return True

    def update_record(self, slot_no: int, record: bytes) -> bool:
        """Overwrite a record in place when the new value is no larger.

        MiniDB's SQL surface does not require UPDATE, but recovery replays
        in-place edits, so we support the same-or-smaller case which keeps the
        RID (and thus index entries) stable.
        """
        if slot_no < 0 or slot_no >= self.num_slots:
            return False
        offset, length = self._get_slot(slot_no)
        if length == 0 or len(record) > length:
            return False
        self.data[offset:offset + len(record)] = record
        self._set_slot(slot_no, offset, len(record))
        return True

    # -- deterministic replay (used by recovery and replication) ------------
    # These mirror the normal operations but target an *explicit* slot so a
    # logged change reproduces the same (page_id, slot_no) -> record mapping
    # regardless of the page's current contents. Like insert_record, each
    # allocates fresh bytes at free_end, so replaying a log uses exactly the
    # same space the original operations did.
    def apply_insert(self, slot_no: int, record: bytes) -> None:
        lsn, num_slots, free_end = self._get_header()
        rec_len = len(record)
        new_offset = free_end - rec_len
        self.data[new_offset:new_offset + rec_len] = record
        if slot_no >= num_slots:
            # Grow the directory; any skipped slots become tombstones.
            for s in range(num_slots, slot_no):
                self._set_slot(s, 0, 0)
            num_slots = slot_no + 1
        self._set_slot(slot_no, new_offset, rec_len)
        self._set_header(lsn, num_slots, new_offset)

    def apply_delete(self, slot_no: int) -> None:
        if 0 <= slot_no < self.num_slots:
            offset, _ = self._get_slot(slot_no)
            self._set_slot(slot_no, offset, 0)

    def apply_update(self, slot_no: int, record: bytes) -> None:
        # Replay path mirrors update_record (new value fits the old footprint).
        self.update_record(slot_no, record)

    def iter_records(self) -> Iterator[Tuple[int, bytes]]:
        """Yield ``(slot_no, record_bytes)`` for every live record."""
        num_slots = self.num_slots
        for i in range(num_slots):
            offset, length = self._get_slot(i)
            if length != 0:
                yield i, bytes(self.data[offset:offset + length])

    # -- (de)serialisation --------------------------------------------------
    def to_bytes(self) -> bytes:
        return bytes(self.data)

    @classmethod
    def from_bytes(cls, page_id: int, data: bytes) -> "Page":
        return cls(page_id, bytearray(data))

    def __repr__(self) -> str:
        return (f"<Page id={self.page_id} slots={self.num_slots} "
                f"free={self.free_space()} lsn={self.lsn}>")
