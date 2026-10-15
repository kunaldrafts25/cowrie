# SPDX-License-Identifier: BSD-3-Clause
"""Sizes of complete messages in the existing pool wire format.

A two-byte length bounds each variable field. No extra bytes are added to the
wire, so existing senders remain compatible.
"""

from __future__ import annotations

import struct


def request_size(data: bytes) -> int | None:
    if not data:
        return None
    opcode = data[:1]
    if opcode == b"i":
        return 10
    if opcode in (b"f", b"u"):
        return 5
    if opcode != b"r":
        raise ValueError
    if len(data) < 3:
        return None
    return 3 + int(struct.unpack_from("!H", data, 1)[0])


def response_size(data: bytes) -> int | None:
    if not data:
        return None
    opcode = data[:1]
    if opcode not in (b"i", b"r"):
        raise ValueError
    if len(data) < 5:
        return None
    if opcode == b"i" or struct.unpack_from("!I", data, 1)[0] != 0:
        return 5
    if len(data) < 11:
        return None
    ip_length = int(struct.unpack_from("!H", data, 9)[0])
    snapshot_length_offset = 15 + ip_length
    if len(data) < snapshot_length_offset + 2:
        return None
    snapshot_length = int(struct.unpack_from("!H", data, snapshot_length_offset)[0])
    return snapshot_length_offset + 2 + snapshot_length
