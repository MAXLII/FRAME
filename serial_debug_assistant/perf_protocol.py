from __future__ import annotations

from dataclasses import dataclass
import struct


CMD_SET_PERF = 0x01
CMD_WORD_PERF_INFO_QUERY = 0x20
CMD_WORD_PERF_SUMMARY_QUERY = 0x21
CMD_WORD_PERF_RESET_PEAK = 0x25
CMD_WORD_PERF_DICT_QUERY = 0x26
CMD_WORD_PERF_DICT_ITEM_REPORT = 0x27
CMD_WORD_PERF_DICT_END = 0x28
CMD_WORD_PERF_SAMPLE_QUERY = 0x29
CMD_WORD_PERF_SAMPLE_BATCH_REPORT = 0x2A
CMD_WORD_PERF_SAMPLE_END = 0x2B
CMD_WORD_PERF_CONTROL = 0x2E

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
class PerfDictAck:
    accepted: bool
    type_filter: int
    record_count: int
    sequence: int
    dict_version: int
    reject_reason: int


@dataclass(frozen=True)
class PerfDictEntry:
    sequence: int
    index: int
    record_count: int
    record_id: int
    record_type: int
    name: str


@dataclass(frozen=True)
class PerfRecord:
    sequence: int
    record_id: int
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
class PerfDictEnd:
    sequence: int
    record_count: int
    status: int
    dict_version: int


@dataclass(frozen=True)
class PerfSampleAck:
    accepted: bool
    type_filter: int
    record_count: int
    sequence: int
    dict_version: int
    reject_reason: int


@dataclass(frozen=True)
class PerfSampleBatch:
    sequence: int
    record_count: int
    item_count: int
    records: tuple[PerfRecord, ...]


def build_perf_dict_query_payload(type_filter: int, dict_version: int) -> bytes:
    return struct.pack("<B3xI", type_filter & 0xFF, dict_version & 0xFFFFFFFF)


def build_perf_sample_query_payload(type_filter: int, dict_version: int, flags: int = 0) -> bytes:
    return struct.pack("<BBHI", type_filter & 0xFF, flags & 0xFF, 0, dict_version & 0xFFFFFFFF)


def build_perf_control_payload(enable: bool) -> bytes:
    return bytes([1 if enable else 0])


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


def parse_perf_dict_ack_payload(payload: bytes) -> PerfDictAck:
    fmt = "<BBHIIB3x"
    if len(payload) < struct.calcsize(fmt):
        raise ValueError("perf dict ack payload is too short")
    accepted, type_filter, record_count, sequence, dict_version, reject_reason = struct.unpack(
        fmt,
        payload[: struct.calcsize(fmt)],
    )
    return PerfDictAck(
        accepted=accepted != 0,
        type_filter=type_filter,
        record_count=record_count,
        sequence=sequence,
        dict_version=dict_version,
        reject_reason=reject_reason,
    )


def parse_perf_dict_item_payload(payload: bytes) -> PerfDictEntry:
    fmt = "<IHHHBB"
    header_size = struct.calcsize(fmt)
    if len(payload) < header_size:
        raise ValueError("perf dict item payload is too short")
    sequence, index, record_count, record_id, record_type, name_len = struct.unpack(fmt, payload[:header_size])
    if len(payload) < header_size + name_len:
        raise ValueError("perf dict item name is truncated")
    raw_name = payload[header_size : header_size + name_len]
    return PerfDictEntry(
        sequence=sequence,
        index=index,
        record_count=record_count,
        record_id=record_id,
        record_type=record_type,
        name=raw_name.decode("utf-8", errors="replace"),
    )


def parse_perf_dict_end_payload(payload: bytes) -> PerfDictEnd:
    fmt = "<IHBBI"
    if len(payload) < struct.calcsize(fmt):
        raise ValueError("perf dict end payload is too short")
    sequence, record_count, status, _reserved, dict_version = struct.unpack(fmt, payload[: struct.calcsize(fmt)])
    return PerfDictEnd(sequence=sequence, record_count=record_count, status=status, dict_version=dict_version)


def parse_perf_sample_end_payload(payload: bytes) -> PerfDictEnd:
    fmt = "<IHBB"
    if len(payload) < struct.calcsize(fmt):
        raise ValueError("perf sample end payload is too short")
    sequence, record_count, status, _reserved = struct.unpack(fmt, payload[: struct.calcsize(fmt)])
    return PerfDictEnd(sequence=sequence, record_count=record_count, status=status, dict_version=0)


def parse_perf_sample_ack_payload(payload: bytes) -> PerfSampleAck:
    fmt = "<BBHIIB3x"
    if len(payload) < struct.calcsize(fmt):
        raise ValueError("perf sample ack payload is too short")
    accepted, type_filter, record_count, sequence, dict_version, reject_reason = struct.unpack(
        fmt,
        payload[: struct.calcsize(fmt)],
    )
    return PerfSampleAck(
        accepted=accepted != 0,
        type_filter=type_filter,
        record_count=record_count,
        sequence=sequence,
        dict_version=dict_version,
        reject_reason=reject_reason,
    )


def parse_perf_sample_batch_payload(
    payload: bytes,
    dict_entries: dict[int, PerfDictEntry],
) -> PerfSampleBatch:
    fmt = "<IHH"
    header_size = struct.calcsize(fmt)
    if len(payload) < header_size:
        raise ValueError("perf sample batch payload is too short")
    sequence, record_count, item_count = struct.unpack(fmt, payload[:header_size])
    offset = header_size
    records: list[PerfRecord] = []
    for _ in range(item_count):
        if len(payload) < offset + 2:
            raise ValueError("perf sample item id is truncated")
        record_id = struct.unpack_from("<H", payload, offset)[0]
        entry = dict_entries.get(record_id)
        if entry is None:
            raise ValueError(f"perf sample references unknown record id {record_id}")
        if entry.record_type == PERF_RECORD_TASK:
            item_fmt = "<HIIIff"
            item_size = struct.calcsize(item_fmt)
            if len(payload) < offset + item_size:
                raise ValueError("perf task sample item is truncated")
            _, time_us, max_time_us, period_us, load_percent, peak_percent = struct.unpack_from(item_fmt, payload, offset)
        elif entry.record_type == PERF_RECORD_INTERRUPT:
            item_fmt = "<HIIff"
            item_size = struct.calcsize(item_fmt)
            if len(payload) < offset + item_size:
                raise ValueError("perf interrupt sample item is truncated")
            _, time_us, max_time_us, load_percent, peak_percent = struct.unpack_from(item_fmt, payload, offset)
            period_us = 0
        elif entry.record_type == PERF_RECORD_CODE:
            item_fmt = "<HII"
            item_size = struct.calcsize(item_fmt)
            if len(payload) < offset + item_size:
                raise ValueError("perf code sample item is truncated")
            _, time_us, max_time_us = struct.unpack_from(item_fmt, payload, offset)
            period_us = 0
            load_percent = 0.0
            peak_percent = 0.0
        else:
            raise ValueError(f"unsupported perf record type {entry.record_type}")
        offset += item_size
        records.append(
            PerfRecord(
                sequence=sequence,
                record_id=record_id,
                index=entry.index,
                record_count=record_count,
                record_type=entry.record_type,
                name=entry.name,
                time_us=time_us,
                max_time_us=max_time_us,
                period_us=period_us,
                load_percent=load_percent,
                peak_percent=peak_percent,
            )
        )
    return PerfSampleBatch(
        sequence=sequence,
        record_count=record_count,
        item_count=item_count,
        records=tuple(records),
    )


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
        1: "设备忙",
        2: "筛选类型无效",
        3: "设备缓存不足",
        4: "设备不支持",
        5: "字典版本不匹配",
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
