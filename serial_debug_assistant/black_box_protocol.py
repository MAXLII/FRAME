from __future__ import annotations

import struct


CMD_SET_BLACK_BOX = 0x01
CMD_WORD_BLACK_BOX_RANGE_QUERY = 0x0E
CMD_WORD_BLACK_BOX_HEADER = 0x0F
CMD_WORD_BLACK_BOX_ROW = 0x10
CMD_WORD_BLACK_BOX_COMPLETE = 0x11

BLACK_BOX_INT8 = 0
BLACK_BOX_UINT8 = 1
BLACK_BOX_INT16 = 2
BLACK_BOX_UINT16 = 3
BLACK_BOX_INT32 = 4
BLACK_BOX_UINT32 = 5
BLACK_BOX_FP32 = 6


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


def parse_black_box_header_payload(payload: bytes) -> dict[str, int | str]:
    if len(payload) >= 2:
        declared_length = int.from_bytes(payload[:2], "little")
        if 0 < declared_length <= len(payload) - 2:
            return {
                "format": "legacy_text",
                "text": payload[2 : 2 + declared_length].decode("utf-8", errors="replace"),
            }
    if len(payload) < 4:
        return {
            "format": "binary_item",
            "column_index": 0,
            "is_last": 1,
            "name": "",
        }
    column_index = int.from_bytes(payload[:2], "little")
    is_last = payload[2]
    name_length = payload[3]
    raw_name = payload[4 : 4 + name_length]
    return {
        "format": "binary_item",
        "column_index": column_index,
        "is_last": is_last,
        "name": raw_name.decode("utf-8", errors="replace"),
    }


def parse_black_box_row_payload(payload: bytes) -> dict[str, int | float | str]:
    if len(payload) >= 6:
        record_offset = int.from_bytes(payload[:4], "little")
        declared_length = int.from_bytes(payload[4:6], "little")
        if 0 < declared_length <= len(payload) - 6:
            return {
                "format": "legacy_text",
                "record_offset": record_offset,
                "row_text": payload[6 : 6 + declared_length].decode("utf-8", errors="replace"),
            }
    if len(payload) < struct.calcsize("<IHBIB"):
        return {
            "format": "binary_item",
            "record_offset": 0,
            "column_index": 0,
            "type": BLACK_BOX_UINT32,
            "data_u32": 0,
            "value": "",
            "is_row_end": 1,
        }
    record_offset, column_index, value_type, data_u32, is_row_end = struct.unpack("<IHBIB", payload[: struct.calcsize("<IHBIB")])
    return {
        "format": "binary_item",
        "record_offset": record_offset,
        "column_index": column_index,
        "type": value_type,
        "data_u32": data_u32,
        "value": decode_black_box_value(value_type, data_u32),
        "is_row_end": is_row_end,
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


def decode_black_box_value(value_type: int, data_u32: int) -> int | float:
    packed = struct.pack("<I", data_u32 & 0xFFFFFFFF)
    if value_type == BLACK_BOX_INT8:
        return struct.unpack("<b", packed[:1])[0]
    if value_type == BLACK_BOX_UINT8:
        return packed[0]
    if value_type == BLACK_BOX_INT16:
        return struct.unpack("<h", packed[:2])[0]
    if value_type == BLACK_BOX_UINT16:
        return struct.unpack("<H", packed[:2])[0]
    if value_type == BLACK_BOX_INT32:
        return struct.unpack("<i", packed)[0]
    if value_type == BLACK_BOX_UINT32:
        return struct.unpack("<I", packed)[0]
    if value_type == BLACK_BOX_FP32:
        return struct.unpack("<f", packed)[0]
    return data_u32


def format_black_box_value(value_type: int, value: int | float) -> str:
    if value_type == BLACK_BOX_FP32 and isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
