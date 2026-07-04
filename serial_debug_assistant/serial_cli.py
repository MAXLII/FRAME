from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
from io import StringIO
import json
from pathlib import Path
import struct
import time

import serial
import serial.tools.list_ports

from serial_debug_assistant.black_box_protocol import (
    CMD_WORD_BLACK_BOX_COMPLETE,
    CMD_WORD_BLACK_BOX_HEADER,
    CMD_WORD_BLACK_BOX_RANGE_QUERY,
    CMD_WORD_BLACK_BOX_ROW,
    build_black_box_range_query_payload,
    parse_black_box_complete_payload,
    parse_black_box_header_payload,
    parse_black_box_range_query_ack,
    parse_black_box_row_payload,
)
from serial_debug_assistant.models import ParameterEntry, ProtocolFrame
from serial_debug_assistant.perf_protocol import (
    CMD_WORD_PERF_DICT_END,
    CMD_WORD_PERF_DICT_ITEM_REPORT,
    CMD_WORD_PERF_DICT_QUERY,
    CMD_WORD_PERF_INFO_QUERY,
    CMD_WORD_PERF_RESET_PEAK,
    CMD_WORD_PERF_SAMPLE_BATCH_REPORT,
    CMD_WORD_PERF_SAMPLE_END,
    CMD_WORD_PERF_SAMPLE_QUERY,
    CMD_WORD_PERF_SUMMARY_QUERY,
    PERF_FILTER_ALL,
    PerfDictEntry,
    build_perf_dict_query_payload,
    build_perf_sample_query_payload,
    describe_perf_end_status,
    describe_perf_filter,
    describe_perf_record_type,
    parse_perf_dict_ack_payload,
    parse_perf_dict_end_payload,
    parse_perf_dict_item_payload,
    parse_perf_info_payload,
    parse_perf_sample_ack_payload,
    parse_perf_sample_batch_payload,
    parse_perf_sample_end_payload,
    parse_perf_summary_payload,
)
from serial_debug_assistant.protocol import FrameParser, build_frame, format_value, value_to_u32
from serial_debug_assistant.scope_protocol import (
    CMD_WORD_SCOPE_INFO_QUERY,
    CMD_WORD_SCOPE_LIST_QUERY,
    CMD_WORD_SCOPE_RESET,
    CMD_WORD_SCOPE_SAMPLE_QUERY,
    CMD_WORD_SCOPE_START,
    CMD_WORD_SCOPE_STOP,
    CMD_WORD_SCOPE_TRIGGER,
    CMD_WORD_SCOPE_VAR_QUERY,
    SCOPE_READ_MODE_FORCE,
    SCOPE_READ_MODE_NORMAL,
    build_scope_info_query_payload,
    build_scope_list_query_payload,
    build_scope_sample_query_payload,
    build_scope_simple_command_payload,
    build_scope_var_query_payload,
    describe_scope_state,
    describe_scope_status,
    parse_scope_control_ack_payload,
    parse_scope_info_ack_payload,
    parse_scope_list_item_payload,
    parse_scope_sample_ack_payload,
    parse_scope_var_ack_payload,
)
from serial_debug_assistant.sfra_protocol import (
    CMD_WORD_SFRA_CFG_SET,
    CMD_WORD_SFRA_INFO_QUERY,
    CMD_WORD_SFRA_LIST_QUERY,
    CMD_WORD_SFRA_POINT_QUERY,
    CMD_WORD_SFRA_RESET,
    CMD_WORD_SFRA_START,
    CMD_WORD_SFRA_STOP,
    SFRA_APPLY_AMPLITUDE,
    SFRA_APPLY_RANGE,
    build_sfra_config_set_payload,
    build_sfra_info_query_payload,
    build_sfra_list_query_payload,
    build_sfra_point_query_payload,
    build_sfra_simple_command_payload,
    describe_sfra_state,
    describe_sfra_status,
    parse_sfra_control_ack_payload,
    parse_sfra_info_ack_payload,
    parse_sfra_list_item_payload,
    parse_sfra_point_payload,
)
from serial_debug_assistant.trace_protocol import (
    CMD_WORD_TRACE_CONTROL,
    CMD_WORD_TRACE_RECORD_REPORT,
    build_trace_control_payload,
    parse_trace_control_ack_payload,
    parse_trace_record_report_payload,
)


@dataclass(frozen=True)
class SerialOptions:
    port: str
    baudrate: int
    timeout: float
    dst: int
    d_dst: int


class SerialCliError(RuntimeError):
    pass


class ProtocolSerialClient:
    def __init__(self, options: SerialOptions) -> None:
        self.options = _resolve_serial_options(options)
        self.parser = FrameParser()
        self.serial_port: serial.Serial | None = None

    def __enter__(self) -> "ProtocolSerialClient":
        self.serial_port = serial.Serial(
            port=self.options.port,
            baudrate=self.options.baudrate,
            bytesize=8,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
        )
        try:
            self.serial_port.reset_input_buffer()
        except serial.SerialException:
            pass
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self.serial_port is not None:
            self.serial_port.close()
            self.serial_port = None

    def send(
        self,
        *,
        cmd_set: int,
        cmd_word: int,
        payload: bytes = b"",
        dst: int | None = None,
        d_dst: int | None = None,
    ) -> bytes:
        if self.serial_port is None:
            raise SerialCliError("serial port is not open")
        frame = build_frame(
            dst=self.options.dst if dst is None else dst,
            d_dst=self.options.d_dst if d_dst is None else d_dst,
            cmd_set=cmd_set,
            cmd_word=cmd_word,
            payload=payload,
        )
        self.serial_port.write(frame)
        return frame

    def read_frames(self, *, timeout: float | None = None) -> list[ProtocolFrame]:
        if self.serial_port is None:
            raise SerialCliError("serial port is not open")
        deadline = time.monotonic() + (self.options.timeout if timeout is None else timeout)
        frames: list[ProtocolFrame] = []
        while time.monotonic() < deadline:
            data = self.serial_port.read(self.serial_port.in_waiting or 1)
            if data:
                frames.extend(self.parser.feed(data))
        return frames

    def request(
        self,
        *,
        cmd_set: int,
        cmd_word: int,
        payload: bytes = b"",
        timeout: float | None = None,
        dst: int | None = None,
        d_dst: int | None = None,
    ) -> list[ProtocolFrame]:
        self.send(cmd_set=cmd_set, cmd_word=cmd_word, payload=payload, dst=dst, d_dst=d_dst)
        return self.read_frames(timeout=timeout)


def list_serial_ports() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for port in serial.tools.list_ports.comports():
        rows.append(
            {
                "device": port.device,
                "description": port.description or "",
                "hwid": port.hwid or "",
            }
        )
    return rows


def resolve_serial_port(port: str) -> str:
    requested = port.strip()
    if requested.lower() not in {"jlink", "j-link"}:
        return requested
    for item in list_serial_ports():
        text = " ".join(str(item.get(key, "")) for key in ("device", "description", "hwid")).lower()
        if "jlink" in text or "j-link" in text:
            return str(item["device"])
    raise SerialCliError("No J-Link CDC UART serial port was found.")


def _resolve_serial_options(options: SerialOptions) -> SerialOptions:
    resolved_port = resolve_serial_port(options.port)
    if resolved_port == options.port:
        return options
    return SerialOptions(
        port=resolved_port,
        baudrate=options.baudrate,
        timeout=options.timeout,
        dst=options.dst,
        d_dst=options.d_dst,
    )


def raw_serial(options: SerialOptions, *, send_hex: str, send_text: str, read_seconds: float, receive_hex: bool) -> str:
    payload = _parse_hex_bytes(send_hex) if send_hex else decode_text_escapes(send_text).encode("utf-8")
    options = _resolve_serial_options(options)
    with serial.Serial(port=options.port, baudrate=options.baudrate, timeout=0.05) as ser:
        if payload:
            ser.write(payload)
        deadline = time.monotonic() + read_seconds
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            data = ser.read(ser.in_waiting or 1)
            if data:
                chunks.append(data)
        data = b"".join(chunks)
    if receive_hex:
        return data.hex(" ").upper()
    return data.decode("utf-8", errors="replace")


def decode_text_escapes(text: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\" or index + 1 >= len(text):
            result.append(char)
            index += 1
            continue
        marker = text[index + 1]
        if marker == "r":
            result.append("\r")
            index += 2
        elif marker == "n":
            result.append("\n")
            index += 2
        elif marker == "t":
            result.append("\t")
            index += 2
        elif marker == "\\":
            result.append("\\")
            index += 2
        elif marker == '"':
            result.append('"')
            index += 2
        elif marker == "x" and index + 3 < len(text):
            hex_text = text[index + 2 : index + 4]
            try:
                result.append(chr(int(hex_text, 16)))
                index += 4
            except ValueError:
                result.append(char)
                index += 1
        else:
            result.append(char)
            index += 1
    return "".join(result)


def protocol_request(options: SerialOptions, *, cmd_set: int, cmd_word: int, payload_hex: str) -> list[dict[str, object]]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=cmd_set, cmd_word=cmd_word, payload=_parse_hex_bytes(payload_hex))
    return [_frame_to_dict(frame) for frame in frames]


def param_list(options: SerialOptions) -> list[dict[str, object]]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=0x01, payload=b"\x00")
    entries: list[ParameterEntry] = []
    expected_count = 0
    for frame in frames:
        if frame.cmd_set != 0x01:
            continue
        if frame.cmd_word == 0x01 and frame.is_ack == 1 and len(frame.payload) >= 4:
            expected_count = int.from_bytes(frame.payload[:4], "little")
        elif frame.cmd_word == 0x04:
            entry = parse_parameter_list_item(frame.payload)
            if entry is not None:
                entries.append(entry)
    return [parameter_to_dict(entry) for entry in entries[: expected_count or None]]


def param_read(options: SerialOptions, *, name: str) -> dict[str, object]:
    name_bytes = name.encode("utf-8")
    payload = bytes([len(name_bytes)]) + name_bytes
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=0x02, payload=payload)
    for frame in frames:
        if frame.cmd_set == 0x01 and frame.cmd_word == 0x02 and frame.is_ack == 1:
            entry = parse_single_parameter(frame.payload)
            if entry is not None:
                return parameter_to_dict(entry)
    raise SerialCliError(f"parameter read timeout or invalid response: {name}")


def param_write(options: SerialOptions, *, name: str, type_id: int, value: str, min_value: str | None, max_value: str | None) -> dict[str, object]:
    raw = value_to_u32(value, type_id)
    min_raw = value_to_u32(value if min_value is None else min_value, type_id)
    max_raw = value_to_u32(value if max_value is None else max_value, type_id)
    name_bytes = name.encode("utf-8")[:64]
    payload = (
        bytes([len(name_bytes)])
        + raw.to_bytes(4, "little")
        + max_raw.to_bytes(4, "little")
        + min_raw.to_bytes(4, "little")
        + name_bytes
    )
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=0x03, payload=payload)
    for frame in frames:
        if frame.cmd_set == 0x01 and frame.cmd_word == 0x03 and frame.is_ack == 1:
            entry = parse_write_response(frame.payload)
            if entry is not None:
                return parameter_to_dict(entry)
    raise SerialCliError(f"parameter write timeout or invalid response: {name}")


def scope_list(options: SerialOptions) -> list[dict[str, object]]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_SCOPE_LIST_QUERY, payload=build_scope_list_query_payload())
    return [parse_scope_list_item_payload(frame.payload) for frame in frames if frame.cmd_word == CMD_WORD_SCOPE_LIST_QUERY]


def scope_info(options: SerialOptions, *, scope_id: int) -> dict[str, object]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_SCOPE_INFO_QUERY, payload=build_scope_info_query_payload(scope_id))
    for frame in frames:
        if frame.cmd_word == CMD_WORD_SCOPE_INFO_QUERY and frame.is_ack == 1:
            info = parse_scope_info_ack_payload(frame.payload)
            info["state_text"] = describe_scope_state(int(info["state"]))
            info["status_text"] = describe_scope_status(int(info["status"]))
            return info
    raise SerialCliError("scope info timeout")


def scope_vars(options: SerialOptions, *, scope_id: int, count: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with ProtocolSerialClient(options) as client:
        for index in range(count):
            frames = client.request(
                cmd_set=0x01,
                cmd_word=CMD_WORD_SCOPE_VAR_QUERY,
                payload=build_scope_var_query_payload(scope_id, index),
            )
            for frame in frames:
                if frame.cmd_word == CMD_WORD_SCOPE_VAR_QUERY and frame.is_ack == 1:
                    rows.append(parse_scope_var_ack_payload(frame.payload))
                    break
    return rows


def scope_control(options: SerialOptions, *, scope_id: int, action: str) -> dict[str, object]:
    cmd_word = {
        "start": CMD_WORD_SCOPE_START,
        "trigger": CMD_WORD_SCOPE_TRIGGER,
        "stop": CMD_WORD_SCOPE_STOP,
        "reset": CMD_WORD_SCOPE_RESET,
    }[action]
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=cmd_word, payload=build_scope_simple_command_payload(scope_id))
    for frame in frames:
        if frame.cmd_word == cmd_word and frame.is_ack == 1:
            ack = parse_scope_control_ack_payload(frame.payload)
            ack["state_text"] = describe_scope_state(int(ack["state"]))
            ack["status_text"] = describe_scope_status(int(ack["status"]))
            return ack
    raise SerialCliError(f"scope {action} timeout")


def scope_sample(options: SerialOptions, *, scope_id: int, index: int, tag: int, force: bool) -> dict[str, object]:
    read_mode = SCOPE_READ_MODE_FORCE if force else SCOPE_READ_MODE_NORMAL
    with ProtocolSerialClient(options) as client:
        frames = client.request(
            cmd_set=0x01,
            cmd_word=CMD_WORD_SCOPE_SAMPLE_QUERY,
            payload=build_scope_sample_query_payload(scope_id, read_mode, index, tag),
        )
    for frame in frames:
        if frame.cmd_word == CMD_WORD_SCOPE_SAMPLE_QUERY and frame.is_ack == 1:
            sample = parse_scope_sample_ack_payload(frame.payload)
            sample["status_text"] = describe_scope_status(int(sample["status"]))
            return sample
    raise SerialCliError("scope sample timeout")


def sfra_list(options: SerialOptions) -> list[dict[str, object]]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_SFRA_LIST_QUERY, payload=build_sfra_list_query_payload())
    return [parse_sfra_list_item_payload(frame.payload) for frame in frames if frame.cmd_word == CMD_WORD_SFRA_LIST_QUERY]


def sfra_info(options: SerialOptions, *, sfra_id: int) -> dict[str, object]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_SFRA_INFO_QUERY, payload=build_sfra_info_query_payload(sfra_id))
    for frame in frames:
        if frame.cmd_word == CMD_WORD_SFRA_INFO_QUERY and frame.is_ack == 1:
            info = parse_sfra_info_ack_payload(frame.payload)
            info["state_text"] = describe_sfra_state(int(info["state"]))
            info["status_text"] = describe_sfra_status(int(info["status"]))
            return info
    raise SerialCliError("sfra info timeout")


def sfra_control(options: SerialOptions, *, sfra_id: int, action: str) -> dict[str, object]:
    cmd_word = {"start": CMD_WORD_SFRA_START, "stop": CMD_WORD_SFRA_STOP, "reset": CMD_WORD_SFRA_RESET}[action]
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=cmd_word, payload=build_sfra_simple_command_payload(sfra_id))
    for frame in frames:
        if frame.cmd_word == cmd_word and frame.is_ack == 1:
            ack = parse_sfra_control_ack_payload(frame.payload)
            ack["state_text"] = describe_sfra_state(int(ack["state"]))
            ack["status_text"] = describe_sfra_status(int(ack["status"]))
            return ack
    raise SerialCliError(f"sfra {action} timeout")


def sfra_config(options: SerialOptions, *, sfra_id: int, start_hz: float | None, stop_hz: float | None, amplitude: float | None) -> dict[str, object]:
    apply_mask = 0
    if start_hz is not None or stop_hz is not None:
        apply_mask |= SFRA_APPLY_RANGE
    if amplitude is not None:
        apply_mask |= SFRA_APPLY_AMPLITUDE
    payload = build_sfra_config_set_payload(
        sfra_id,
        apply_mask,
        0.0 if start_hz is None else start_hz,
        0.0 if stop_hz is None else stop_hz,
        0.0 if amplitude is None else amplitude,
    )
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_SFRA_CFG_SET, payload=payload)
    for frame in frames:
        if frame.cmd_word == CMD_WORD_SFRA_CFG_SET and frame.is_ack == 1:
            ack = parse_sfra_control_ack_payload(frame.payload)
            ack["state_text"] = describe_sfra_state(int(ack["state"]))
            ack["status_text"] = describe_sfra_status(int(ack["status"]))
            return ack
    raise SerialCliError("sfra config timeout")


def sfra_point(options: SerialOptions, *, sfra_id: int, index: int, tag: int) -> dict[str, object]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_SFRA_POINT_QUERY, payload=build_sfra_point_query_payload(sfra_id, index, tag))
    for frame in frames:
        if frame.cmd_word == CMD_WORD_SFRA_POINT_QUERY and frame.is_ack == 1:
            point = parse_sfra_point_payload(frame.payload)
            point["status_text"] = describe_sfra_status(int(point["status"]))
            return point
    raise SerialCliError("sfra point timeout")


def perf_info(options: SerialOptions) -> dict[str, object]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_PERF_INFO_QUERY)
    for frame in frames:
        if frame.cmd_word == CMD_WORD_PERF_INFO_QUERY and frame.is_ack == 1:
            return asdict(parse_perf_info_payload(frame.payload))
    raise SerialCliError("perf info timeout")


def perf_summary(options: SerialOptions) -> dict[str, object]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_PERF_SUMMARY_QUERY)
    for frame in frames:
        if frame.cmd_word == CMD_WORD_PERF_SUMMARY_QUERY and frame.is_ack == 1:
            return asdict(parse_perf_summary_payload(frame.payload))
    raise SerialCliError("perf summary timeout")


def perf_dict(options: SerialOptions, *, type_filter: int = PERF_FILTER_ALL) -> list[dict[str, object]]:
    entries, _dict_version = _perf_load_dict(options, type_filter=type_filter)
    return [_perf_dict_entry_to_dict(entry) for entry in sorted(entries, key=lambda item: item.index)]


def _perf_load_dict(options: SerialOptions, *, type_filter: int = PERF_FILTER_ALL) -> tuple[list[PerfDictEntry], int]:
    entries: list[PerfDictEntry] = []
    dict_version = 0
    expected_count = 0
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_PERF_DICT_QUERY, payload=build_perf_dict_query_payload(type_filter, 0), timeout=max(options.timeout, 2.0))
    sequence = None
    for frame in frames:
        if frame.cmd_word == CMD_WORD_PERF_DICT_QUERY and frame.is_ack == 1:
            ack = parse_perf_dict_ack_payload(frame.payload)
            if not ack.accepted:
                raise SerialCliError(f"perf dict rejected: {ack.reject_reason}")
            sequence = ack.sequence
            expected_count = ack.record_count
            dict_version = ack.dict_version
        elif frame.cmd_word == CMD_WORD_PERF_DICT_ITEM_REPORT:
            entry = parse_perf_dict_item_payload(frame.payload)
            if sequence is None or entry.sequence == sequence:
                entries.append(entry)
        elif frame.cmd_word == CMD_WORD_PERF_DICT_END:
            end = parse_perf_dict_end_payload(frame.payload)
            if end.status != 0:
                raise SerialCliError(f"perf dict end status: {describe_perf_end_status(end.status)}")
            dict_version = end.dict_version
    if sequence is None:
        raise SerialCliError("perf dict timeout: no ACK received")
    if expected_count and not entries:
        raise SerialCliError(f"perf dict returned no entries: expected={expected_count}, sequence={sequence}, version={dict_version}. Try again or increase the timeout.")
    return entries, dict_version


def perf_sample(options: SerialOptions, *, type_filter: int = PERF_FILTER_ALL) -> list[dict[str, object]]:
    dict_items, dict_version = _perf_load_dict(options, type_filter=type_filter)
    dict_entries = {
        item.record_id: item
        for item in dict_items
    }
    records = []
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_PERF_SAMPLE_QUERY, payload=build_perf_sample_query_payload(type_filter, dict_version))
    sequence = None
    for frame in frames:
        if frame.cmd_word == CMD_WORD_PERF_SAMPLE_QUERY and frame.is_ack == 1:
            ack = parse_perf_sample_ack_payload(frame.payload)
            if not ack.accepted:
                raise SerialCliError(f"perf sample rejected: {ack.reject_reason}")
            sequence = ack.sequence
        elif frame.cmd_word == CMD_WORD_PERF_SAMPLE_BATCH_REPORT:
            batch = parse_perf_sample_batch_payload(frame.payload, dict_entries)
            if sequence is None or batch.sequence == sequence:
                records.extend(asdict(record) for record in batch.records)
        elif frame.cmd_word == CMD_WORD_PERF_SAMPLE_END:
            end = parse_perf_sample_end_payload(frame.payload)
            if end.status != 0:
                raise SerialCliError(f"perf sample end status: {describe_perf_end_status(end.status)}")
    return records


def perf_reset_peak(options: SerialOptions) -> dict[str, object]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_PERF_RESET_PEAK)
    return {"frames": [_frame_to_dict(frame) for frame in frames]}


def trace_control(options: SerialOptions, *, enable: bool, listen_seconds: float) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with ProtocolSerialClient(options) as client:
        frames = client.request(cmd_set=0x01, cmd_word=CMD_WORD_TRACE_CONTROL, payload=build_trace_control_payload(enable), timeout=options.timeout)
        frames.extend(client.read_frames(timeout=listen_seconds))
    time_unit_us = 100
    for frame in frames:
        if frame.cmd_word == CMD_WORD_TRACE_CONTROL and frame.is_ack == 1:
            ack = parse_trace_control_ack_payload(frame.payload)
            time_unit_us = ack.time_unit_us
            rows.append(asdict(ack))
        elif frame.cmd_word == CMD_WORD_TRACE_RECORD_REPORT:
            record = parse_trace_record_report_payload(frame.payload)
            rows.append({"time_tick": record.time_tick, "time_us": record.time_tick * time_unit_us, "line": record.line})
    return rows


def black_box_read(options: SerialOptions, *, start_offset: int, length: int) -> list[dict[str, object]]:
    with ProtocolSerialClient(options) as client:
        frames = client.request(
            cmd_set=0x01,
            cmd_word=CMD_WORD_BLACK_BOX_RANGE_QUERY,
            payload=build_black_box_range_query_payload(start_offset, length),
            timeout=max(options.timeout, 2.0),
        )
    rows: list[dict[str, object]] = []
    for frame in frames:
        if frame.cmd_word == CMD_WORD_BLACK_BOX_RANGE_QUERY and frame.is_ack == 1:
            rows.append({"kind": "ack", **parse_black_box_range_query_ack(frame.payload)})
        elif frame.cmd_word == CMD_WORD_BLACK_BOX_HEADER:
            rows.append({"kind": "header", **parse_black_box_header_payload(frame.payload)})
        elif frame.cmd_word == CMD_WORD_BLACK_BOX_ROW:
            rows.append({"kind": "row", **parse_black_box_row_payload(frame.payload)})
        elif frame.cmd_word == CMD_WORD_BLACK_BOX_COMPLETE:
            rows.append({"kind": "complete", **parse_black_box_complete_payload(frame.payload)})
    return rows


def parse_parameter_list_item(payload: bytes) -> ParameterEntry | None:
    if not payload:
        return None
    name_len = payload[0]
    if len(payload) < 15 + name_len:
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


def parse_single_parameter(payload: bytes) -> ParameterEntry | None:
    if not payload:
        return None
    name_len = payload[0]
    if len(payload) < 6 + name_len:
        return None
    type_id = payload[1]
    data = int.from_bytes(payload[2:6], "little")
    name = payload[6 : 6 + name_len].decode("utf-8", errors="replace")
    return ParameterEntry(name=name, type_id=type_id, data_raw=data, min_raw=0, max_raw=0)


def parse_write_response(payload: bytes) -> ParameterEntry | None:
    if not payload:
        return None
    name_len = payload[0]
    if len(payload) < 14 + name_len:
        return None
    type_id = payload[1]
    data = int.from_bytes(payload[2:6], "little")
    data_max = int.from_bytes(payload[6:10], "little")
    data_min = int.from_bytes(payload[10:14], "little")
    name = payload[14 : 14 + name_len].decode("utf-8", errors="replace")
    return ParameterEntry(name=name, type_id=type_id, data_raw=data, min_raw=data_min, max_raw=data_max)


def parameter_to_dict(entry: ParameterEntry) -> dict[str, object]:
    return {
        "name": entry.name,
        "type_id": entry.type_id,
        "value": format_value(entry.data_raw, entry.type_id),
        "raw": f"0x{entry.data_raw:08X}",
        "min": format_value(entry.min_raw, entry.type_id),
        "max": format_value(entry.max_raw, entry.type_id),
        "status": entry.status,
        "auto_report": entry.auto_report,
        "important": entry.important,
        "readonly": entry.is_readonly,
    }


def format_output(data: object, *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)
    if output_format == "csv":
        rows = data if isinstance(data, list) else [data]
        if not rows:
            return ""
        if not all(isinstance(row, dict) for row in rows):
            return json.dumps(data, ensure_ascii=False, indent=2)
        fields: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in fields:
                    fields.append(str(key))
        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue()
    return _format_table(data)


def write_or_print(text: str, output: Path | None) -> None:
    if output is None:
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="")


def _format_table(data: object) -> str:
    rows = data if isinstance(data, list) else [data]
    if not rows:
        return "(empty)"
    if not all(isinstance(row, dict) for row in rows):
        return str(data)
    fields: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fields:
                fields.append(str(key))
    widths = {field: len(field) for field in fields}
    for row in rows:
        for field in fields:
            widths[field] = min(max(widths[field], len(str(row.get(field, "")))), 48)
    lines = ["  ".join(field.ljust(widths[field]) for field in fields)]
    lines.append("  ".join("-" * widths[field] for field in fields))
    for row in rows:
        cells = []
        for field in fields:
            text = str(row.get(field, ""))
            if len(text) > widths[field]:
                text = text[: max(1, widths[field] - 3)] + "..."
            cells.append(text.ljust(widths[field]))
        lines.append("  ".join(cells))
    return "\n".join(lines)


def _parse_hex_bytes(text: str) -> bytes:
    tokens = text.replace(",", " ").split()
    if not tokens:
        return b""
    return bytes(int(token, 16) for token in tokens)


def _frame_to_dict(frame: ProtocolFrame) -> dict[str, object]:
    return {
        "src": frame.src,
        "d_src": frame.d_src,
        "dst": frame.dst,
        "d_dst": frame.d_dst,
        "cmd_set": f"0x{frame.cmd_set:02X}",
        "cmd_word": f"0x{frame.cmd_word:02X}",
        "is_ack": frame.is_ack,
        "payload_len": len(frame.payload),
        "payload_hex": frame.payload.hex(" ").upper(),
    }


def _perf_dict_entry_to_dict(entry: PerfDictEntry) -> dict[str, object]:
    return {
        "sequence": entry.sequence,
        "index": entry.index,
        "record_count": entry.record_count,
        "record_id": entry.record_id,
        "record_type": entry.record_type,
        "type": describe_perf_record_type(entry.record_type),
        "name": entry.name,
    }


def parse_perf_filter(text: str) -> int:
    values = {
        "all": 0,
        "task": 1,
        "interrupt": 2,
        "code": 3,
    }
    normalized = text.strip().lower()
    if normalized in values:
        return values[normalized]
    return int(text, 0)


def perf_filter_label(value: int) -> str:
    return describe_perf_filter(value)
