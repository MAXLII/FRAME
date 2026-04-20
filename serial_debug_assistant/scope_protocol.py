from __future__ import annotations

import struct


CMD_SET_SCOPE = 0x01
CMD_WORD_SCOPE_LIST_QUERY = 0x18
CMD_WORD_SCOPE_INFO_QUERY = 0x19
CMD_WORD_SCOPE_VAR_QUERY = 0x1A
CMD_WORD_SCOPE_START = 0x1B
CMD_WORD_SCOPE_TRIGGER = 0x1C
CMD_WORD_SCOPE_STOP = 0x1D
CMD_WORD_SCOPE_RESET = 0x1E
CMD_WORD_SCOPE_SAMPLE_QUERY = 0x1F

SCOPE_TOOL_STATE_IDLE = 0
SCOPE_TOOL_STATE_RUNNING = 1
SCOPE_TOOL_STATE_TRIGGERED = 2

SCOPE_READ_MODE_NORMAL = 0
SCOPE_READ_MODE_FORCE = 1

SCOPE_TOOL_STATUS_OK = 0
SCOPE_TOOL_STATUS_SCOPE_ID_INVALID = 1
SCOPE_TOOL_STATUS_VAR_INDEX_INVALID = 2
SCOPE_TOOL_STATUS_SAMPLE_INDEX_INVALID = 3
SCOPE_TOOL_STATUS_RUNNING_DENIED = 4
SCOPE_TOOL_STATUS_DATA_NOT_READY = 5
SCOPE_TOOL_STATUS_BUSY = 6
SCOPE_TOOL_STATUS_CAPTURE_CHANGED = 7


def build_scope_list_query_payload() -> bytes:
    return b"\x00"


def build_scope_info_query_payload(scope_id: int) -> bytes:
    return struct.pack("<B3x", scope_id & 0xFF)


def build_scope_var_query_payload(scope_id: int, var_index: int) -> bytes:
    return struct.pack("<BB2x", scope_id & 0xFF, var_index & 0xFF)


def build_scope_simple_command_payload(scope_id: int) -> bytes:
    return struct.pack("<B3x", scope_id & 0xFF)


def build_scope_sample_query_payload(scope_id: int, read_mode: int, sample_index: int, expected_capture_tag: int) -> bytes:
    return struct.pack(
        "<BB2xII",
        scope_id & 0xFF,
        read_mode & 0xFF,
        sample_index & 0xFFFFFFFF,
        expected_capture_tag & 0xFFFFFFFF,
    )


def parse_scope_list_item_payload(payload: bytes) -> dict[str, int | str]:
    if len(payload) < 4:
        return {
            "scope_id": 0,
            "is_last": 1,
            "name": "",
        }
    scope_id, is_last, name_len, _reserved = struct.unpack("<BBBB", payload[:4])
    raw_name = payload[4 : 4 + name_len]
    return {
        "scope_id": scope_id,
        "is_last": is_last,
        "name": raw_name.decode("utf-8", errors="replace"),
    }


def parse_scope_info_ack_payload(payload: bytes) -> dict[str, int]:
    fmt = "<BBBBBBBBIIIIIII"
    if len(payload) < struct.calcsize(fmt):
        return {
            "scope_id": 0,
            "status": SCOPE_TOOL_STATUS_BUSY,
            "state": SCOPE_TOOL_STATE_IDLE,
            "data_ready": 0,
            "var_count": 0,
            "sample_count": 0,
            "write_index": 0,
            "trigger_index": 0,
            "trigger_post_cnt": 0,
            "trigger_display_index": 0,
            "sample_period_us": 0,
            "capture_tag": 0,
        }
    (
        scope_id,
        status,
        state,
        data_ready,
        var_count,
        _reserved0,
        _reserved1,
        _reserved2,
        sample_count,
        write_index,
        trigger_index,
        trigger_post_cnt,
        trigger_display_index,
        sample_period_us,
        capture_tag,
    ) = struct.unpack(fmt, payload[: struct.calcsize(fmt)])
    return {
        "scope_id": scope_id,
        "status": status,
        "state": state,
        "data_ready": data_ready,
        "var_count": var_count,
        "sample_count": sample_count,
        "write_index": write_index,
        "trigger_index": trigger_index,
        "trigger_post_cnt": trigger_post_cnt,
        "trigger_display_index": trigger_display_index,
        "sample_period_us": sample_period_us,
        "capture_tag": capture_tag,
    }


def parse_scope_var_ack_payload(payload: bytes) -> dict[str, int | str]:
    if len(payload) < 8:
        return {
            "scope_id": 0,
            "status": SCOPE_TOOL_STATUS_BUSY,
            "var_index": 0,
            "is_last": 1,
            "name": "",
        }
    scope_id, status, var_index, is_last, name_len, _r0, _r1, _r2 = struct.unpack("<BBBBBBBB", payload[:8])
    raw_name = payload[8 : 8 + name_len]
    return {
        "scope_id": scope_id,
        "status": status,
        "var_index": var_index,
        "is_last": is_last,
        "name": raw_name.decode("utf-8", errors="replace"),
    }


def parse_scope_control_ack_payload(payload: bytes) -> dict[str, int]:
    fmt = "<BBBBI"
    if len(payload) < struct.calcsize(fmt):
        return {
            "scope_id": 0,
            "status": SCOPE_TOOL_STATUS_BUSY,
            "state": SCOPE_TOOL_STATE_IDLE,
            "data_ready": 0,
            "capture_tag": 0,
        }
    scope_id, status, state, data_ready, capture_tag = struct.unpack(fmt, payload[: struct.calcsize(fmt)])
    return {
        "scope_id": scope_id,
        "status": status,
        "state": state,
        "data_ready": data_ready,
        "capture_tag": capture_tag,
    }


def parse_scope_sample_ack_payload(payload: bytes) -> dict[str, int | list[float]]:
    header_fmt = "<BBBBIIB3x"
    header_size = struct.calcsize(header_fmt)
    if len(payload) < header_size:
        return {
            "scope_id": 0,
            "status": SCOPE_TOOL_STATUS_BUSY,
            "read_mode": SCOPE_READ_MODE_NORMAL,
            "var_count": 0,
            "sample_index": 0,
            "capture_tag": 0,
            "is_last_sample": 1,
            "values": [],
        }
    scope_id, status, read_mode, var_count, sample_index, capture_tag, is_last_sample = struct.unpack(
        header_fmt,
        payload[:header_size],
    )
    values: list[float] = []
    float_count = min(var_count, max(0, (len(payload) - header_size) // 4))
    if float_count > 0:
        values = list(struct.unpack(f"<{float_count}f", payload[header_size : header_size + float_count * 4]))
    return {
        "scope_id": scope_id,
        "status": status,
        "read_mode": read_mode,
        "var_count": var_count,
        "sample_index": sample_index,
        "capture_tag": capture_tag,
        "is_last_sample": is_last_sample,
        "values": values,
    }


def describe_scope_state(state: int) -> str:
    if state == SCOPE_TOOL_STATE_RUNNING:
        return "Running"
    if state == SCOPE_TOOL_STATE_TRIGGERED:
        return "Triggered"
    return "Idle"


def describe_scope_status(status: int) -> str:
    descriptions = {
        SCOPE_TOOL_STATUS_OK: "OK",
        SCOPE_TOOL_STATUS_SCOPE_ID_INVALID: "Invalid Scope ID",
        SCOPE_TOOL_STATUS_VAR_INDEX_INVALID: "Invalid Variable Index",
        SCOPE_TOOL_STATUS_SAMPLE_INDEX_INVALID: "Invalid Sample Index",
        SCOPE_TOOL_STATUS_RUNNING_DENIED: "Running Denied",
        SCOPE_TOOL_STATUS_DATA_NOT_READY: "Data Not Ready",
        SCOPE_TOOL_STATUS_BUSY: "Busy",
        SCOPE_TOOL_STATUS_CAPTURE_CHANGED: "Capture Changed",
    }
    return descriptions.get(status, f"Status {status}")
