from __future__ import annotations

import struct


CMD_SET_BLACK_BOX = 0x01
CMD_WORD_BLACK_BOX_RANGE_QUERY = 0x0E
CMD_WORD_BLACK_BOX_HEADER = 0x0F
CMD_WORD_BLACK_BOX_ROW = 0x10
CMD_WORD_BLACK_BOX_COMPLETE = 0x11


def build_black_box_range_query_payload(start_offset: int, read_length: int) -> bytes:
    return struct.pack("<II", start_offset, read_length)


def parse_black_box_range_query_ack(payload: bytes) -> dict[str, int]:
    if len(payload) >= struct.calcsize("<BII"):
        accepted, start_offset, read_length = struct.unpack("<BII", payload[: struct.calcsize("<BII")])
        return {
            "accepted": accepted,
            "start_offset": start_offset,
            "read_length": read_length,
        }
    if len(payload) >= 1:
        return {
            "accepted": payload[0],
            "start_offset": 0,
            "read_length": 0,
        }
    return {
        "accepted": 1,
        "start_offset": 0,
        "read_length": 0,
    }


def parse_black_box_header_payload(payload: bytes) -> str:
    if len(payload) >= 2:
        declared_length = int.from_bytes(payload[:2], "little")
        if declared_length <= len(payload) - 2:
            return payload[2 : 2 + declared_length].decode("utf-8", errors="replace")
    return payload.decode("utf-8", errors="replace")


def parse_black_box_row_payload(payload: bytes) -> dict[str, int | str]:
    if len(payload) >= 6:
        record_offset = int.from_bytes(payload[:4], "little")
        declared_length = int.from_bytes(payload[4:6], "little")
        if declared_length <= len(payload) - 6:
            return {
                "record_offset": record_offset,
                "row_text": payload[6 : 6 + declared_length].decode("utf-8", errors="replace"),
            }
    return {
        "record_offset": 0,
        "row_text": payload.decode("utf-8", errors="replace"),
    }


def parse_black_box_complete_payload(payload: bytes) -> dict[str, int]:
    full_size = struct.calcsize("<IIIHB")
    if len(payload) >= full_size:
        start_offset, end_offset, scanned_bytes, row_count, has_more = struct.unpack("<IIIHB", payload[:full_size])
        return {
            "start_offset": start_offset,
            "end_offset": end_offset,
            "scanned_bytes": scanned_bytes,
            "row_count": row_count,
            "has_more": has_more,
        }
    partial_size = struct.calcsize("<II")
    if len(payload) >= partial_size:
        start_offset, end_offset = struct.unpack("<II", payload[:partial_size])
        return {
            "start_offset": start_offset,
            "end_offset": end_offset,
            "scanned_bytes": 0,
            "row_count": 0,
            "has_more": 0,
        }
    return {
        "start_offset": 0,
        "end_offset": 0,
        "scanned_bytes": 0,
        "row_count": 0,
        "has_more": 0,
    }
