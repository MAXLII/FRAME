from __future__ import annotations

from dataclasses import dataclass
import struct


CMD_SET_PERF = 0x01
CMD_WORD_PERF_INFO_QUERY = 0x20
CMD_WORD_PERF_SUMMARY_QUERY = 0x21
CMD_WORD_PERF_RECORD_LIST_QUERY = 0x22
CMD_WORD_PERF_RECORD_ITEM_REPORT = 0x23
CMD_WORD_PERF_RECORD_LIST_END = 0x24
CMD_WORD_PERF_RESET_PEAK = 0x25

PERF_FILTER_ALL = 0
PERF_FILTER_TASK = 1
PERF_FILTER_INTERRUPT = 2
PERF_FILTER_CODE = 3

PERF_RECORD_TASK = 1
PERF_RECORD_INTERRUPT = 2
PERF_RECORD_CODE = 3

PERF_END_STATUS_OK = 0
PERF_END_STATUS_CANCELLED = 1
PERF_END_STATUS_OVERFLOW = 2
PERF_END_STATUS_INTERNAL_ERROR = 3


@dataclass(frozen=True)
class PerfInfo:
    protocol_version: int
    record_count: int
    unit_us: float
    cnt_per_sys_tick: int
    cpu_window_ms: int
    flags: int


@dataclass(frozen=True)
class PerfSummary:
    task_load_percent: float
    task_peak_percent: float
    interrupt_load_percent: float
    interrupt_peak_percent: float


@dataclass(frozen=True)
class PerfListAck:
    accepted: bool
    type_filter: int
    record_count: int
    sequence: int
    reject_reason: int


@dataclass(frozen=True)
class PerfRecord:
    sequence: int
    index: int
    record_count: int
    record_type: int
    name: str
    time_us: int
    max_time_us: int
    period_us: int
    load_percent: float
    peak_percent: float


@dataclass(frozen=True)
class PerfListEnd:
    sequence: int
    record_count: int
    status: int


def build_perf_record_list_query_payload(type_filter: int) -> bytes:
    return struct.pack("<B3x", type_filter & 0xFF)


def parse_perf_info_payload(payload: bytes) -> PerfInfo:
    fmt = "<HHfIIB3x"
    if len(payload) < struct.calcsize(fmt):
        raise ValueError("perf info payload is too short")
    protocol_version, record_count, unit_us, cnt_per_sys_tick, cpu_window_ms, flags = struct.unpack(
        fmt,
        payload[: struct.calcsize(fmt)],
    )
    return PerfInfo(
        protocol_version=protocol_version,
        record_count=record_count,
        unit_us=unit_us,
        cnt_per_sys_tick=cnt_per_sys_tick,
        cpu_window_ms=cpu_window_ms,
        flags=flags,
    )


def parse_perf_summary_payload(payload: bytes) -> PerfSummary:
    fmt = "<ffff"
    if len(payload) < struct.calcsize(fmt):
        raise ValueError("perf summary payload is too short")
    task_load, task_peak, interrupt_load, interrupt_peak = struct.unpack(fmt, payload[: struct.calcsize(fmt)])
    return PerfSummary(
        task_load_percent=task_load,
        task_peak_percent=task_peak,
        interrupt_load_percent=interrupt_load,
        interrupt_peak_percent=interrupt_peak,
    )


def parse_perf_record_list_ack_payload(payload: bytes) -> PerfListAck:
    fmt = "<BBHIB3x"
    if len(payload) < struct.calcsize(fmt):
        raise ValueError("perf list ack payload is too short")
    accepted, type_filter, record_count, sequence, reject_reason = struct.unpack(fmt, payload[: struct.calcsize(fmt)])
    return PerfListAck(
        accepted=accepted != 0,
        type_filter=type_filter,
        record_count=record_count,
        sequence=sequence,
        reject_reason=reject_reason,
    )


def parse_perf_record_item_payload(payload: bytes) -> PerfRecord:
    new_fmt = "<IHHBBHIIIff"
    old_fmt = "<IHHBBHIIff"
    new_header_size = struct.calcsize(new_fmt)
    old_header_size = struct.calcsize(old_fmt)
    if len(payload) < old_header_size:
        raise ValueError("perf record item payload is too short")
    name_len = payload[9]
    if len(payload) >= new_header_size + name_len:
        (
            sequence,
            index,
            record_count,
            record_type,
            name_len,
            _reserved,
            time_us,
            max_time_us,
            period_us,
            load_percent,
            peak_percent,
        ) = struct.unpack(new_fmt, payload[:new_header_size])
        header_size = new_header_size
    elif len(payload) >= old_header_size + name_len:
        (
            sequence,
            index,
            record_count,
            record_type,
            name_len,
            _reserved,
            time_us,
            max_time_us,
            load_percent,
            peak_percent,
        ) = struct.unpack(old_fmt, payload[:old_header_size])
        period_us = 0
        header_size = old_header_size
    else:
        raise ValueError("perf record item name is truncated")
    raw_name = payload[header_size : header_size + name_len]
    return PerfRecord(
        sequence=sequence,
        index=index,
        record_count=record_count,
        record_type=record_type,
        name=raw_name.decode("utf-8", errors="replace"),
        time_us=time_us,
        max_time_us=max_time_us,
        period_us=period_us,
        load_percent=load_percent,
        peak_percent=peak_percent,
    )


def parse_perf_record_list_end_payload(payload: bytes) -> PerfListEnd:
    fmt = "<IHBB"
    if len(payload) < struct.calcsize(fmt):
        raise ValueError("perf list end payload is too short")
    sequence, record_count, status, _reserved = struct.unpack(fmt, payload[: struct.calcsize(fmt)])
    return PerfListEnd(sequence=sequence, record_count=record_count, status=status)


def parse_perf_success_payload(payload: bytes) -> bool:
    if not payload:
        raise ValueError("perf success payload is too short")
    return payload[0] != 0


def describe_perf_filter(type_filter: int) -> str:
    descriptions = {
        PERF_FILTER_ALL: "All",
        PERF_FILTER_TASK: "Task",
        PERF_FILTER_INTERRUPT: "Interrupt",
        PERF_FILTER_CODE: "Code",
    }
    return descriptions.get(type_filter, f"Filter {type_filter}")


def describe_perf_record_type(record_type: int) -> str:
    descriptions = {
        PERF_RECORD_TASK: "Task",
        PERF_RECORD_INTERRUPT: "Interrupt",
        PERF_RECORD_CODE: "Code",
    }
    return descriptions.get(record_type, f"Type {record_type}")


def describe_perf_reject_reason(reason: int) -> str:
    descriptions = {
        0: "OK",
        1: "Busy",
        2: "Invalid filter",
        3: "No buffer",
        4: "Unsupported",
    }
    return descriptions.get(reason, f"Reason {reason}")


def describe_perf_end_status(status: int) -> str:
    descriptions = {
        PERF_END_STATUS_OK: "OK",
        PERF_END_STATUS_CANCELLED: "Cancelled",
        PERF_END_STATUS_OVERFLOW: "Overflow",
        PERF_END_STATUS_INTERNAL_ERROR: "Internal error",
    }
    return descriptions.get(status, f"Status {status}")
