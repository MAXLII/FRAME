from __future__ import annotations

import math
import struct


CMD_SET_SFRA = 0x01
CMD_WORD_SFRA_LIST_QUERY = 0x2F
CMD_WORD_SFRA_INFO_QUERY = 0x30
CMD_WORD_SFRA_CFG_SET = 0x31
CMD_WORD_SFRA_START = 0x32
CMD_WORD_SFRA_STOP = 0x33
CMD_WORD_SFRA_RESET = 0x34
CMD_WORD_SFRA_POINT_QUERY = 0x35
CMD_WORD_SFRA_POINT_REPORT = 0x36
CMD_WORD_SFRA_DONE_REPORT = 0x37

SFRA_APPLY_RANGE = 0x01
SFRA_APPLY_AMPLITUDE = 0x02

SFRA_STATE_IDLE = 0
SFRA_STATE_PREPARE_FREQ = 1
SFRA_STATE_SETTLE = 2
SFRA_STATE_COLLECT = 3
SFRA_STATE_CALC = 4
SFRA_STATE_DONE = 5

SFRA_TOOL_STATUS_OK = 0
SFRA_TOOL_STATUS_ID_INVALID = 1
SFRA_TOOL_STATUS_POINT_INDEX_INVALID = 2
SFRA_TOOL_STATUS_BUSY = 3
SFRA_TOOL_STATUS_DATA_NOT_READY = 4
SFRA_TOOL_STATUS_SWEEP_CHANGED = 5
SFRA_TOOL_STATUS_INVALID_PARAM = 6
SFRA_TOOL_STATUS_CORE_ERROR = 7


def build_sfra_list_query_payload() -> bytes:
    return b"\x00"


def build_sfra_info_query_payload(sfra_id: int) -> bytes:
    return struct.pack("<B3x", sfra_id & 0xFF)


def build_sfra_config_set_payload(
    sfra_id: int,
    apply_mask: int,
    start_hz: float,
    stop_hz: float,
    amplitude: float,
) -> bytes:
    return struct.pack(
        "<BB2xfff",
        sfra_id & 0xFF,
        apply_mask & 0xFF,
        float(start_hz),
        float(stop_hz),
        float(amplitude),
    )


def build_sfra_simple_command_payload(sfra_id: int) -> bytes:
    return struct.pack("<B3x", sfra_id & 0xFF)


def build_sfra_point_query_payload(sfra_id: int, point_index: int, expected_sweep_tag: int) -> bytes:
    return struct.pack("<BBHI", sfra_id & 0xFF, 0, point_index & 0xFFFF, expected_sweep_tag & 0xFFFFFFFF)


def parse_sfra_list_item_payload(payload: bytes) -> dict[str, int | str]:
    if len(payload) < 4:
        return {"sfra_id": 0, "is_last": 1, "name": ""}
    sfra_id, is_last, name_len, _reserved = struct.unpack("<BBBB", payload[:4])
    raw_name = payload[4 : 4 + name_len]
    return {
        "sfra_id": sfra_id,
        "is_last": is_last,
        "name": raw_name.decode("utf-8", errors="replace"),
    }


def parse_sfra_info_ack_payload(payload: bytes) -> dict[str, int | float]:
    header_fmt = "<BBBBBBBBHHHHI"
    float_fmt = "<fffffff"
    header_size = struct.calcsize(header_fmt)
    expected_size = header_size + struct.calcsize(float_fmt)
    if len(payload) < expected_size:
        return {
            "sfra_id": 0,
            "status": SFRA_TOOL_STATUS_BUSY,
            "state": SFRA_STATE_IDLE,
            "busy": 0,
            "done": 0,
            "data_ready": 0,
            "freq_index": 0,
            "freq_length": 0,
            "table_length": 0,
            "inject_delay_tick": 0,
            "sweep_tag": 0,
            "current_freq_hz": 0.0,
            "isr_freq_hz": 0.0,
            "freq_start_hz": 0.0,
            "freq_end_hz": 0.0,
            "inject_amplitude": 0.0,
            "settle_cycle_count": 0.0,
            "collect_cycle_count": 0.0,
        }
    (
        sfra_id,
        status,
        state,
        busy,
        done,
        data_ready,
        _r0,
        _r1,
        freq_index,
        freq_length,
        table_length,
        inject_delay_tick,
        sweep_tag,
    ) = struct.unpack(header_fmt, payload[:header_size])
    (
        current_freq_hz,
        isr_freq_hz,
        freq_start_hz,
        freq_end_hz,
        inject_amplitude,
        settle_cycle_count,
        collect_cycle_count,
    ) = struct.unpack(float_fmt, payload[header_size:expected_size])

    return {
        "sfra_id": sfra_id,
        "status": status,
        "state": state,
        "busy": busy,
        "done": done,
        "data_ready": data_ready,
        "freq_index": freq_index,
        "freq_length": freq_length,
        "table_length": table_length,
        "inject_delay_tick": inject_delay_tick,
        "sweep_tag": sweep_tag,
        "current_freq_hz": current_freq_hz,
        "isr_freq_hz": isr_freq_hz,
        "freq_start_hz": freq_start_hz,
        "freq_end_hz": freq_end_hz,
        "inject_amplitude": inject_amplitude,
        "settle_cycle_count": settle_cycle_count,
        "collect_cycle_count": collect_cycle_count,
    }


def parse_sfra_control_ack_payload(payload: bytes) -> dict[str, int]:
    fmt = "<BBBBBBBBHHHHI"
    if len(payload) < struct.calcsize(fmt):
        return {
            "sfra_id": 0,
            "status": SFRA_TOOL_STATUS_BUSY,
            "state": SFRA_STATE_IDLE,
            "busy": 0,
            "done": 0,
            "data_ready": 0,
            "freq_index": 0,
            "freq_length": 0,
            "table_length": 0,
            "sweep_tag": 0,
        }
    (
        sfra_id,
        status,
        state,
        busy,
        done,
        data_ready,
        _r0,
        _r1,
        freq_index,
        freq_length,
        table_length,
        _reserved16,
        sweep_tag,
    ) = struct.unpack(fmt, payload[: struct.calcsize(fmt)])
    return {
        "sfra_id": sfra_id,
        "status": status,
        "state": state,
        "busy": busy,
        "done": done,
        "data_ready": data_ready,
        "freq_index": freq_index,
        "freq_length": freq_length,
        "table_length": table_length,
        "sweep_tag": sweep_tag,
    }


def parse_sfra_point_payload(payload: bytes) -> dict[str, int | float]:
    fmt = "<BBBBHHIfff"
    if len(payload) < struct.calcsize(fmt):
        return {
            "sfra_id": 0,
            "status": SFRA_TOOL_STATUS_BUSY,
            "is_last": 1,
            "point_index": 0,
            "point_count": 0,
            "sweep_tag": 0,
            "freq_hz": 0.0,
            "magnitude": 0.0,
            "magnitude_db": 0.0,
            "phase_deg": 0.0,
        }
    (
        sfra_id,
        status,
        is_last,
        _reserved,
        point_index,
        point_count,
        sweep_tag,
        freq_hz,
        magnitude,
        phase_deg,
    ) = struct.unpack(fmt, payload[: struct.calcsize(fmt)])
    magnitude_db = 20.0 * math.log10(max(float(magnitude), 1e-12))
    return {
        "sfra_id": sfra_id,
        "status": status,
        "is_last": is_last,
        "point_index": point_index,
        "point_count": point_count,
        "sweep_tag": sweep_tag,
        "freq_hz": freq_hz,
        "magnitude": magnitude,
        "magnitude_db": magnitude_db,
        "phase_deg": phase_deg,
    }


def describe_sfra_state(state: int) -> str:
    descriptions = {
        SFRA_STATE_IDLE: "Idle",
        SFRA_STATE_PREPARE_FREQ: "Prepare",
        SFRA_STATE_SETTLE: "Settle",
        SFRA_STATE_COLLECT: "Collect",
        SFRA_STATE_CALC: "Calculate",
        SFRA_STATE_DONE: "Done",
    }
    return descriptions.get(state, f"State {state}")


def describe_sfra_status(status: int) -> str:
    descriptions = {
        SFRA_TOOL_STATUS_OK: "OK",
        SFRA_TOOL_STATUS_ID_INVALID: "Invalid SFRA ID",
        SFRA_TOOL_STATUS_POINT_INDEX_INVALID: "Invalid Point Index",
        SFRA_TOOL_STATUS_BUSY: "Busy",
        SFRA_TOOL_STATUS_DATA_NOT_READY: "Data Not Ready",
        SFRA_TOOL_STATUS_SWEEP_CHANGED: "Sweep Changed",
        SFRA_TOOL_STATUS_INVALID_PARAM: "Invalid Parameter",
        SFRA_TOOL_STATUS_CORE_ERROR: "Core Error",
    }
    return descriptions.get(status, f"Status {status}")
