from __future__ import annotations

from dataclasses import dataclass
import struct

from serial_debug_assistant.models import ParameterEntry


CMD_SET_PARAMETER = 0x01
CMD_WORD_PARAMETER_LIST_BATCH = 0x3F
CMD_WORD_PARAMETER_WAVE_BATCH = 0x40
PARAMETER_LIST_BATCH_HEADER_FORMAT = "<IIH"
PARAMETER_LIST_BATCH_HEADER_SIZE = struct.calcsize(PARAMETER_LIST_BATCH_HEADER_FORMAT)
PARAMETER_LIST_ITEM_FIXED_SIZE = 15
PARAMETER_WAVE_BATCH_HEADER_FORMAT = "<IIIH"
PARAMETER_WAVE_BATCH_HEADER_SIZE = struct.calcsize(PARAMETER_WAVE_BATCH_HEADER_FORMAT)
PARAMETER_WAVE_ITEM_FIXED_SIZE = 6


@dataclass(frozen=True)
class ParameterListBatch:
    total_count: int
    first_index: int
    entries: tuple[ParameterEntry, ...]


@dataclass(frozen=True)
class ParameterWaveValue:
    name: str
    type_id: int
    data_raw: int


@dataclass(frozen=True)
class ParameterWaveBatch:
    simulation_tick_100us: int
    total_count: int
    first_index: int
    values: tuple[ParameterWaveValue, ...]


def parse_parameter_list_item(payload: bytes) -> ParameterEntry | None:
    if not payload:
        return None
    name_len = payload[0]
    if len(payload) < PARAMETER_LIST_ITEM_FIXED_SIZE + name_len:
        return None
    type_id = payload[1]
    data = int.from_bytes(payload[2:6], "little")
    data_max = int.from_bytes(payload[6:10], "little")
    data_min = int.from_bytes(payload[10:14], "little")
    status = payload[14]
    name = payload[15 : 15 + name_len].decode("utf-8", errors="replace")
    return ParameterEntry(
        name=name,
        type_id=type_id,
        data_raw=data,
        min_raw=data_min,
        max_raw=data_max,
        status=status,
        auto_report=bool(status & 0x01),
        important=bool(status & 0x02),
    )


def parse_parameter_list_batch_payload(payload: bytes) -> ParameterListBatch:
    if len(payload) < PARAMETER_LIST_BATCH_HEADER_SIZE:
        raise ValueError("parameter list batch header is truncated")

    total_count, first_index, item_count = struct.unpack_from(PARAMETER_LIST_BATCH_HEADER_FORMAT, payload)
    if first_index > total_count or first_index + item_count > total_count:
        raise ValueError("parameter list batch index range is invalid")

    offset = PARAMETER_LIST_BATCH_HEADER_SIZE
    entries: list[ParameterEntry] = []
    for _ in range(item_count):
        if offset >= len(payload):
            raise ValueError("parameter list batch item is missing")
        record_size = PARAMETER_LIST_ITEM_FIXED_SIZE + payload[offset]
        record_end = offset + record_size
        if record_end > len(payload):
            raise ValueError("parameter list batch item is truncated")
        entry = parse_parameter_list_item(payload[offset:record_end])
        if entry is None:
            raise ValueError("parameter list batch item is invalid")
        entries.append(entry)
        offset = record_end

    if offset != len(payload):
        raise ValueError("parameter list batch has trailing bytes")

    return ParameterListBatch(total_count=total_count, first_index=first_index, entries=tuple(entries))


def parse_parameter_wave_batch_payload(payload: bytes) -> ParameterWaveBatch:
    if len(payload) < PARAMETER_WAVE_BATCH_HEADER_SIZE:
        raise ValueError("parameter wave batch header is truncated")

    simulation_tick, total_count, first_index, item_count = struct.unpack_from(
        PARAMETER_WAVE_BATCH_HEADER_FORMAT,
        payload,
    )
    if first_index > total_count or first_index + item_count > total_count:
        raise ValueError("parameter wave batch index range is invalid")

    offset = PARAMETER_WAVE_BATCH_HEADER_SIZE
    values: list[ParameterWaveValue] = []
    for _ in range(item_count):
        if offset >= len(payload):
            raise ValueError("parameter wave batch item is missing")
        name_len = payload[offset]
        record_end = offset + PARAMETER_WAVE_ITEM_FIXED_SIZE + name_len
        if record_end > len(payload):
            raise ValueError("parameter wave batch item is truncated")
        type_id = payload[offset + 1]
        data_raw = int.from_bytes(payload[offset + 2 : offset + 6], "little")
        name = payload[offset + 6 : record_end].decode("utf-8", errors="replace")
        values.append(ParameterWaveValue(name=name, type_id=type_id, data_raw=data_raw))
        offset = record_end

    if offset != len(payload):
        raise ValueError("parameter wave batch has trailing bytes")

    return ParameterWaveBatch(
        simulation_tick_100us=simulation_tick,
        total_count=total_count,
        first_index=first_index,
        values=tuple(values),
    )
