"""Record identifier (RID).

A RID is the physical address of a tuple: the page it lives on plus its slot
number within that page's slot directory. RIDs are stable for the life of a
record (slots are tombstoned on delete, never renumbered), which lets B+Tree
indexes store them as leaf payloads.
"""

from __future__ import annotations

import struct
from typing import NamedTuple


class RID(NamedTuple):
    page_id: int
    slot_no: int

    def pack(self) -> bytes:
        return struct.pack("<iH", self.page_id, self.slot_no)

    @classmethod
    def unpack(cls, buf: bytes) -> "RID":
        page_id, slot_no = struct.unpack("<iH", buf)
        return cls(page_id, slot_no)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"RID({self.page_id},{self.slot_no})"


RID_SIZE = struct.calcsize("<iH")  # 6 bytes
