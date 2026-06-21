"""Wire protocol for primary -> replica streaming (Track D).

A tiny length-framed message protocol over a TCP stream. Every message is:

    [ 1 byte type ][ 4 byte big-endian length ][ length bytes payload ]

Message types:
    CATALOG    payload = UTF-8 JSON of the primary's catalog snapshot
    RECORDS    payload = concatenated length-framed LogRecords (redo stream)
    ACK        payload = 8-byte applied LSN sent by the replica
    HEARTBEAT  payload = empty (liveness / lag probe)

The same ``LogRecord`` encoding used by the WAL is reused verbatim, so the
replica applies records with the exact redo logic recovery uses.
"""

from __future__ import annotations

import socket
import struct
from typing import List, Tuple

from ..wal.log_record import LogRecord

CATALOG = 1
RECORDS = 2
ACK = 3
HEARTBEAT = 4

_HDR = struct.Struct(">BI")
_FRAME = struct.Struct("<I")


def send_msg(sock: socket.socket, msg_type: int, payload: bytes = b"") -> None:
    sock.sendall(_HDR.pack(msg_type, len(payload)) + payload)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    got = 0
    while got < n:
        b = sock.recv(n - got)
        if not b:
            raise ConnectionError("peer closed the connection")
        chunks.append(b)
        got += len(b)
    return b"".join(chunks)


def recv_msg(sock: socket.socket) -> Tuple[int, bytes]:
    header = recv_exact(sock, _HDR.size)
    msg_type, length = _HDR.unpack(header)
    payload = recv_exact(sock, length) if length else b""
    return msg_type, payload


def encode_records(records: List[LogRecord]) -> bytes:
    return b"".join(r.framed() for r in records)


def decode_records(payload: bytes) -> List[LogRecord]:
    out: List[LogRecord] = []
    off = 0
    n = len(payload)
    while off + _FRAME.size <= n:
        (length,) = _FRAME.unpack_from(payload, off)
        off += _FRAME.size
        rec, _ = LogRecord.decode_from(payload, off)
        off += length
        out.append(rec)
    return out


def encode_ack(lsn: int) -> bytes:
    return struct.pack(">Q", lsn)


def decode_ack(payload: bytes) -> int:
    return struct.unpack(">Q", payload)[0]
