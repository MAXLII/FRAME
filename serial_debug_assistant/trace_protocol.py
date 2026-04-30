from __future__ import annotations

from dataclasses import dataclass
import struct


CMD_SET_TRACE = 0x01
CMD_WORD_TRACE_CONTROL = 0x2C
CMD_WORD_TRACE_RECORD_REPORT = 0x2D

DEFAULT_TRACE_TIME_UNIT_US = 100


@dataclass(frozen=True)
class TraceControlAck:
    success: bool
    running: bool
    time_unit_us: int


@dataclass(frozen=True)
class TraceRecordReport:
    time_tick: int
    line: int


def build_trace_control_payload(enable: bool) -> bytes:
    return bytes([1 if enable else 0])


def parse_trace_control_ack_payload(payload: bytes) -> TraceControlAck:
    success = payload[0] != 0 if len(payload) >= 1 else False
    running = payload[1] != 0 if len(payload) >= 2 else False
    time_unit_us = DEFAULT_TRACE_TIME_UNIT_US
    if len(payload) >= 4:
        time_unit_us = struct.unpack_from("<H", payload, 2)[0]
    if time_unit_us <= 0:
        time_unit_us = DEFAULT_TRACE_TIME_UNIT_US
    return TraceControlAck(success=success, running=running, time_unit_us=time_unit_us)


def parse_trace_record_report_payload(payload: bytes) -> TraceRecordReport:
    if len(payload) < 6:
        raise ValueError("trace record payload is too short")
    time_tick, line = struct.unpack_from("<IH", payload, 0)
    return TraceRecordReport(time_tick=time_tick, line=line)
