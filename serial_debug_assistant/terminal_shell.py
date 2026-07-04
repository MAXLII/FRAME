from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import re
import shlex
import sys
import threading
import time

import serial

from serial_debug_assistant.app_config import load_config_section, save_config_section
from serial_debug_assistant.app_paths import get_app_paths
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
from serial_debug_assistant.factory_mode import (
    CMD_WORD_FACTORY_CALI_READ,
    CMD_WORD_FACTORY_CALI_SAVE,
    CMD_WORD_FACTORY_CALI_WRITE,
    CMD_WORD_FACTORY_TIME_QUERY,
    CMD_WORD_FACTORY_TIME_WRITE,
    build_factory_cali_read_payload,
    build_factory_cali_save_payload,
    build_factory_cali_write_payload,
    build_factory_time_query_payload,
    build_factory_time_write_payload,
    format_factory_time_string,
    parse_factory_cali_payload,
    parse_factory_time_payload,
    parse_timezone_input,
)
from serial_debug_assistant.firmware_update import (
    CMD_WORD_LLC_PFC_UPGRADE_PROGRESS_QUERY,
    CMD_WORD_UPDATE_END,
    CMD_WORD_UPDATE_FW,
    CMD_WORD_UPDATE_INFO,
    CMD_WORD_UPDATE_READY,
    UPDATE_TYPE_FORCE,
    UPDATE_TYPE_NORMAL,
    build_llc_pfc_upgrade_progress_query_payload,
    CMD_WORD_FIRMWARE_VERSION_QUERY,
    build_firmware_version_query_payload,
    build_update_end_payload,
    build_update_info_payload,
    build_update_packet_payload,
    build_update_ready_payload,
    describe_reject_reason,
    format_unix_time,
    format_version,
    load_firmware_image,
    module_name,
    parse_llc_pfc_upgrade_progress_ack,
    parse_firmware_version_ack,
)
from serial_debug_assistant.jlink_debug import (
    DebugVariable,
    JLinkDebugError,
    JLinkSettings,
    JLinkVariableService,
    infer_jlink_device,
    is_jlink_expandable_address,
    jlink_symbol_name_for_address,
    jlink_type_template_key,
    resolve_elf_function_source_location,
    resolve_elf_source_location,
)
from serial_debug_assistant.models import FirmwareImage, ProtocolFrame
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
    PERF_RECORD_INTERRUPT,
    PERF_RECORD_TASK,
    PerfDictEntry,
    build_perf_dict_query_payload,
    build_perf_sample_query_payload,
    describe_perf_end_status,
    parse_perf_dict_ack_payload,
    parse_perf_dict_end_payload,
    parse_perf_dict_item_payload,
    parse_perf_info_payload,
    parse_perf_sample_ack_payload,
    parse_perf_sample_batch_payload,
    parse_perf_sample_end_payload,
    parse_perf_summary_payload,
)
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
from serial_debug_assistant.serial_cli import (
    ProtocolSerialClient,
    SerialCliError,
    SerialOptions,
    decode_text_escapes,
    format_output,
    list_serial_ports,
    parameter_to_dict,
    parse_parameter_list_item,
    parse_perf_filter,
    parse_single_parameter,
    parse_write_response,
    resolve_serial_port,
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
from serial_debug_assistant.protocol import value_to_u32
from serial_debug_assistant.trace_protocol import (
    CMD_WORD_TRACE_CONTROL,
    CMD_WORD_TRACE_RECORD_REPORT,
    build_trace_control_payload,
    parse_trace_control_ack_payload,
    parse_trace_record_report_payload,
)


class FrameTerminalShell:
    def __init__(self) -> None:
        self.client: ProtocolSerialClient | None = None
        self.options = SerialOptions(port="", baudrate=921600, timeout=1.5, dst=2, d_dst=0)
        self.loaded_firmware: FirmwareImage | None = None
        self.upgrade_thread: threading.Thread | None = None
        self.upgrade_stop_event = threading.Event()
        self.upgrade_lock = threading.RLock()
        self.upgrade_status: dict[str, object] = {
            "state": "idle",
            "detail": "",
            "sent_bytes": 0,
            "total_bytes": 0,
            "stage": "",
        }
        self.jlink_service = JLinkVariableService()
        self.jlink_variables: list[DebugVariable] = []
        self.jlink_loaded_paths: tuple[Path | None, Path | None] = (None, None)
        self.command_auto_prefix: tuple[str, ...] = ()

    def run(self) -> int:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        print("FRAME terminal. Type 'help' for commands, 'exit' to quit.")
        while True:
            try:
                line = input("frame> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                self._disconnect()
                return 0
            line = line.lstrip("\ufeff")
            if not line:
                continue
            try:
                if not self._execute(line):
                    self._disconnect()
                    return 0
            except (SerialCliError, serial.SerialException, ValueError, OSError) as exc:
                print(f"ERROR: {exc}")

    def _execute(self, line: str) -> bool:
        args = _split_command_line(line)
        command = args[0].replace("\ufeff", "").replace("ï»¿", "").lower()
        rest = args[1:]
        command = _normalize_command_name(args[0])
        auto_applied = False
        if command not in _terminal_command_names() and self.command_auto_prefix:
            args = [*self.command_auto_prefix, *args]
            command = _normalize_command_name(args[0])
            rest = args[1:]
            auto_applied = True
            print(f"[auto] {' '.join(args)}")
        if self._upgrade_is_active() and command != "upgrade":
            print("upgrade is running; use: upgrade progress | upgrade stop")
            return True
        if command in {"exit", "quit", "q"}:
            return False
        if command == "help":
            self._print_help()
        elif command == "ports":
            print(format_output(list_serial_ports(), output_format="table"))
        elif command == "connect":
            self._connect(rest)
        elif command == "disconnect":
            self._disconnect()
        elif command == "status":
            self._print_status()
        elif command == "raw":
            self._raw(rest)
        elif command == "home":
            self._home(rest)
        elif command == "param":
            self._param(rest)
        elif command == "wave":
            self._wave(rest)
        elif command == "upgrade":
            self._upgrade(rest)
        elif command == "blackbox":
            self._blackbox(rest)
        elif command == "factory":
            self._factory(rest)
        elif command == "perf":
            self._perf(rest)
        elif command == "scope":
            self._scope(rest)
        elif command == "sfra":
            self._sfra(rest)
        elif command == "trace":
            self._trace(rest)
        elif command == "jlink":
            self._jlink(rest)
        else:
            print(f"Unknown command: {command}")
        if not auto_applied:
            remembered_prefix = _remembered_command_prefix(args)
            if remembered_prefix:
                self.command_auto_prefix = remembered_prefix
        return True

    def _connect(self, args: list[str]) -> None:
        port = args[0] if args else "COM8"
        baud = int(args[1], 0) if len(args) >= 2 else 921600
        timeout = float(args[2]) if len(args) >= 3 else 1.5
        self._disconnect()
        resolved_port = resolve_serial_port(port)
        self.options = SerialOptions(port=resolved_port, baudrate=baud, timeout=timeout, dst=2, d_dst=0)
        self.client = ProtocolSerialClient(self.options)
        self.client.__enter__()
        print(f"connected: {resolved_port} @ {baud}")

    def _disconnect(self) -> None:
        if self._upgrade_is_active():
            self.upgrade_stop_event.set()
            thread = self.upgrade_thread
            if thread is not None:
                thread.join(timeout=2.0)
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None
            print("disconnected")

    def _print_status(self) -> None:
        if self.client is None:
            print("not connected")
            return
        print(f"connected: {self.options.port} @ {self.options.baudrate}, timeout={self.options.timeout}s")

    def _request(
        self,
        *,
        cmd_word: int,
        payload: bytes = b"",
        timeout: float | None = None,
        cmd_set: int = 0x01,
        dst: int | None = None,
        d_dst: int | None = None,
    ) -> list[ProtocolFrame]:
        if self.client is None:
            raise SerialCliError("not connected; run: connect COM8 921600")
        return self.client.request(cmd_set=cmd_set, cmd_word=cmd_word, payload=payload, timeout=timeout, dst=dst, d_dst=d_dst)

    def _raw(self, args: list[str]) -> None:
        if self.client is None or self.client.serial_port is None:
            raise SerialCliError("not connected; run: connect COM8 921600")
        if not args:
            print("usage: raw text <text> | raw hex <AA 55 ...> | raw read [seconds] | raw query <text> [seconds] | raw query-hex <AA 55 ...> [seconds]")
            return
        action = args[0]
        if action == "text" and len(args) >= 2:
            payload = decode_text_escapes(" ".join(args[1:])).encode("utf-8")
            self.client.serial_port.write(payload)
            print(f"sent {len(payload)} bytes")
        elif action == "hex" and len(args) >= 2:
            payload = _parse_hex_bytes(" ".join(args[1:]))
            self.client.serial_port.write(payload)
            print(f"sent {len(payload)} bytes")
        elif action == "query" and len(args) >= 2:
            seconds = float(args[-1]) if len(args) >= 3 and _looks_like_number(args[-1]) else 1.0
            text_parts = args[1:-1] if len(args) >= 3 and _looks_like_number(args[-1]) else args[1:]
            payload = decode_text_escapes(" ".join(text_parts)).encode("utf-8")
            self.client.serial_port.write(payload)
            print(f"sent {len(payload)} bytes")
            self._read_raw_text(seconds)
        elif action == "query-hex" and len(args) >= 2:
            seconds = float(args[-1]) if len(args) >= 3 and _looks_like_number(args[-1]) else 1.0
            hex_parts = args[1:-1] if len(args) >= 3 and _looks_like_number(args[-1]) else args[1:]
            payload = _parse_hex_bytes(" ".join(hex_parts))
            self.client.serial_port.write(payload)
            print(f"sent {len(payload)} bytes")
            self._read_raw_text(seconds)
        elif action == "read":
            seconds = float(args[1]) if len(args) >= 2 else 1.0
            self._read_raw_text(seconds)
        else:
            print("usage: raw text <text> | raw hex <AA 55 ...> | raw read [seconds] | raw query <text> [seconds] | raw query-hex <AA 55 ...> [seconds]")

    def _read_raw_text(self, seconds: float) -> None:
        if self.client is None or self.client.serial_port is None:
            raise SerialCliError("not connected; run: connect COM8 921600")
        deadline = time.monotonic() + seconds
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            data = self.client.serial_port.read(self.client.serial_port.in_waiting or 1)
            if data:
                chunks.append(data)
        data = b"".join(chunks)
        print(data.decode("utf-8", errors="replace") if data else "(empty)")

    def _home(self, args: list[str]) -> None:
        if not args:
            print("usage: home enable | home disable | home read | home set <rms> <freq>")
            return
        action = args[0]
        if action == "enable":
            payload = bytes([1, 0xFF, 0xFF, 0xFF])
        elif action == "disable":
            payload = bytes([0xFF, 1, 0xFF, 0xFF])
        elif action == "read":
            payload = bytes([0xFF, 0xFF, 0xFF, 0xFF])
        elif action == "set" and len(args) >= 3:
            payload = bytes([0xFF, 0xFF, int(args[1], 0) & 0xFF, int(args[2], 0) & 0xFF])
        else:
            print("usage: home enable | home disable | home read | home set <rms> <freq>")
            return
        frames = self._request(cmd_set=0x02, cmd_word=0x01, payload=payload)
        print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))

    def _param(self, args: list[str]) -> None:
        if not args:
            print("usage: param list | param read <name> | param write <name> <type_id> <value> [min] [max] | param wave <name> on|off")
            return
        action = args[0]
        if action == "list":
            frames = self._request(cmd_word=0x01, payload=b"\x00")
            rows = []
            for frame in frames:
                if frame.cmd_word == 0x04:
                    entry = parse_parameter_list_item(frame.payload)
                    if entry is not None:
                        rows.append(parameter_to_dict(entry))
            print(format_output(rows, output_format="table"))
        elif action == "read" and len(args) >= 2:
            name = args[1]
            name_bytes = name.encode("utf-8")
            frames = self._request(cmd_word=0x02, payload=bytes([len(name_bytes)]) + name_bytes)
            for frame in frames:
                if frame.cmd_word == 0x02 and frame.is_ack == 1:
                    entry = parse_single_parameter(frame.payload)
                    if entry is not None:
                        print(format_output(parameter_to_dict(entry), output_format="table"))
                        return
            raise SerialCliError(f"parameter read timeout: {name}")
        elif action == "write" and len(args) >= 4:
            name = args[1]
            type_id = int(args[2], 0)
            raw = value_to_u32(args[3], type_id)
            min_raw = value_to_u32(args[4] if len(args) >= 5 else args[3], type_id)
            max_raw = value_to_u32(args[5] if len(args) >= 6 else args[3], type_id)
            name_bytes = name.encode("utf-8")[:64]
            payload = bytes([len(name_bytes)]) + raw.to_bytes(4, "little") + max_raw.to_bytes(4, "little") + min_raw.to_bytes(4, "little") + name_bytes
            frames = self._request(cmd_word=0x03, payload=payload)
            for frame in frames:
                if frame.cmd_word == 0x03 and frame.is_ack == 1:
                    entry = parse_write_response(frame.payload)
                    if entry is not None:
                        print(format_output(parameter_to_dict(entry), output_format="table"))
                        return
            raise SerialCliError(f"parameter write timeout: {name}")
        elif action == "wave" and len(args) >= 3:
            name = args[1]
            enabled = _parse_on_off(args[2])
            name_bytes = name.encode("utf-8")[:64]
            payload = bytes([len(name_bytes), 1 if enabled else 0]) + name_bytes
            frames = self._request(cmd_word=0x05, payload=payload)
            print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))
        else:
            print("usage: param list | param read <name> | param write <name> <type_id> <value> [min] [max] | param wave <name> on|off")

    def _wave(self, args: list[str]) -> None:
        if not args:
            print("usage: wave period <ms> | wave start [period_ms] | wave stop | wave read [seconds]")
            return
        action = args[0]
        if action == "period" and len(args) >= 2:
            period_ms = int(args[1], 0)
            frames = self._request(cmd_word=0x06, payload=period_ms.to_bytes(4, "little"))
            print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))
        elif action == "start":
            if len(args) >= 2:
                period_ms = int(args[1], 0)
                self._request(cmd_word=0x06, payload=period_ms.to_bytes(4, "little"))
            frames = self._request(cmd_word=0x0C, payload=b"\x01")
            print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))
        elif action == "stop":
            frames = self._request(cmd_word=0x0C, payload=b"\x00")
            print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))
        elif action == "read":
            seconds = float(args[1]) if len(args) >= 2 else 1.0
            frames = self.client.read_frames(timeout=seconds) if self.client is not None else []
            print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))
        else:
            print("usage: wave period <ms> | wave start [period_ms] | wave stop | wave read [seconds]")

    def _upgrade(self, args: list[str]) -> None:
        if not args:
            print("usage: upgrade load <firmware.bin> | upgrade info | upgrade start normal|force [dst] [d_dst] | upgrade progress | upgrade stop | upgrade version [dst] [d_dst]")
            return
        action = args[0]
        if action == "load" and len(args) >= 2:
            image = load_firmware_image(Path(args[1]))
            self.loaded_firmware = image
            self._set_upgrade_status(state="loaded", detail=f"loaded {image.path}", sent_bytes=0, total_bytes=len(image.data), stage="loaded")
            print(format_output(_firmware_image_to_dict(image), output_format="table"))
            if image.warnings:
                print("warnings:")
                for warning in image.warnings:
                    print(f"  {warning}")
            return
        if action == "info":
            if self.loaded_firmware is None:
                raise SerialCliError("firmware is not loaded; run: upgrade load <firmware.bin>")
            print(format_output(_firmware_image_to_dict(self.loaded_firmware), output_format="table"))
            return
        if action == "start" and len(args) >= 2:
            update_type = _parse_update_type(args[1])
            dst = int(args[2], 0) if len(args) >= 3 else self.options.dst
            d_dst = int(args[3], 0) if len(args) >= 4 else self.options.d_dst
            self._start_upgrade(update_type=update_type, dst=dst, d_dst=d_dst)
            return
        if action == "progress":
            print(format_output(self._upgrade_status_snapshot(), output_format="table"))
            return
        if action == "stop":
            if not self._upgrade_is_active():
                print("upgrade is not running")
                return
            self.upgrade_stop_event.set()
            print("upgrade stop requested")
            return
        if action == "version":
            dst = int(args[1], 0) if len(args) >= 2 else self.options.dst
            d_dst = int(args[2], 0) if len(args) >= 3 else self.options.d_dst
            frames = self._request(cmd_word=CMD_WORD_FIRMWARE_VERSION_QUERY, payload=build_firmware_version_query_payload(), dst=dst, d_dst=d_dst)
            for frame in frames:
                if frame.cmd_word == CMD_WORD_FIRMWARE_VERSION_QUERY and frame.is_ack == 1:
                    print(format_output(parse_firmware_version_ack(frame.payload), output_format="table"))
                    return
            raise SerialCliError("firmware version timeout")
        print("usage: upgrade load <firmware.bin> | upgrade info | upgrade start normal|force [dst] [d_dst] | upgrade progress | upgrade stop | upgrade version [dst] [d_dst]")

    def _start_upgrade(self, *, update_type: int, dst: int, d_dst: int) -> None:
        if self.client is None:
            raise SerialCliError("not connected; run: connect COM8 921600")
        if self.loaded_firmware is None:
            raise SerialCliError("firmware is not loaded; run: upgrade load <firmware.bin>")
        if not self.loaded_firmware.footer_crc_ok:
            raise SerialCliError("firmware footer CRC32 validation failed")
        if self.loaded_firmware.footer.fw_type != 1:
            raise SerialCliError("only fw_type=1 IAP firmware is supported")
        if self._upgrade_is_active():
            raise SerialCliError("upgrade is already running")
        self.upgrade_stop_event.clear()
        self._set_upgrade_status(
            state="starting",
            detail=f"target=0x{dst:02X} d_dst=0x{d_dst:02X} update_type={update_type}",
            sent_bytes=0,
            total_bytes=len(self.loaded_firmware.data),
            stage="start",
        )
        self.upgrade_thread = threading.Thread(
            target=self._upgrade_worker,
            kwargs={"image": self.loaded_firmware, "update_type": update_type, "dst": dst, "d_dst": d_dst},
            daemon=True,
        )
        self.upgrade_thread.start()
        print("upgrade started; use: upgrade progress | upgrade stop")

    def _upgrade_worker(self, *, image: FirmwareImage, update_type: int, dst: int, d_dst: int) -> None:
        try:
            self._set_upgrade_status(state="running", detail="send upgrade info", stage="0x08", total_bytes=len(image.data))
            frames = self._upgrade_request(
                cmd_word=CMD_WORD_UPDATE_INFO,
                payload=build_update_info_payload(image, update_type),
                dst=dst,
                d_dst=d_dst,
                wait_seconds=10.0,
            )
            ack = self._find_ack(frames, CMD_WORD_UPDATE_INFO)
            if ack is None or len(ack.payload) < 3:
                raise SerialCliError("0x08 ACK timeout or invalid length")
            allow_update = ack.payload[0]
            reject_reason = int.from_bytes(ack.payload[1:3], "little")
            if allow_update != 1:
                raise SerialCliError(f"0x08 rejected upgrade: {describe_reject_reason(reject_reason)} (0x{reject_reason:04X})")

            while not self.upgrade_stop_event.is_set():
                self._set_upgrade_status(state="running", detail="query bootloader ready", stage="0x09")
                frames = self._upgrade_request(
                    cmd_word=CMD_WORD_UPDATE_READY,
                    payload=build_update_ready_payload(),
                    dst=dst,
                    d_dst=d_dst,
                    wait_seconds=1.5,
                )
                ack = self._find_ack(frames, CMD_WORD_UPDATE_READY)
                if ack is not None and len(ack.payload) >= 1 and ack.payload[0] == 1:
                    break
                time.sleep(0.3)
            self._raise_if_upgrade_stopped()

            offset = 0
            while offset < len(image.data):
                self._raise_if_upgrade_stopped()
                actual_len = min(1024, len(image.data) - offset)
                self._set_upgrade_status(
                    state="running",
                    detail=f"send packet offset={offset} len={actual_len}",
                    sent_bytes=offset,
                    total_bytes=len(image.data),
                    stage="0x0A",
                )
                frames = self._upgrade_request(
                    cmd_word=CMD_WORD_UPDATE_FW,
                    payload=build_update_packet_payload(image, offset),
                    dst=dst,
                    d_dst=d_dst,
                    wait_seconds=10.0,
                )
                ack = self._find_ack(frames, CMD_WORD_UPDATE_FW)
                if ack is None or len(ack.payload) < 1:
                    raise SerialCliError(f"0x0A ACK timeout at offset={offset}")
                if len(ack.payload) >= 5:
                    ack_offset = int.from_bytes(ack.payload[1:5], "little")
                    if ack_offset != offset:
                        raise SerialCliError(f"0x0A ACK offset mismatch: ack={ack_offset}, expect={offset}")
                if ack.payload[0] != 1:
                    self._set_upgrade_status(state="running", detail=f"packet rejected, retry offset={offset}", stage="0x0A")
                    continue
                offset += actual_len
                self._set_upgrade_status(
                    state="running",
                    detail=f"packet confirmed {offset}/{len(image.data)}",
                    sent_bytes=offset,
                    total_bytes=len(image.data),
                    stage="0x0A",
                )

            self._set_upgrade_status(state="running", detail="send upgrade end", sent_bytes=len(image.data), total_bytes=len(image.data), stage="0x0B")
            frames = self._upgrade_request(
                cmd_word=CMD_WORD_UPDATE_END,
                payload=build_update_end_payload(image),
                dst=dst,
                d_dst=d_dst,
                wait_seconds=10.0,
            )
            ack = self._find_ack(frames, CMD_WORD_UPDATE_END)
            if ack is None or len(ack.payload) < 1:
                raise SerialCliError("0x0B ACK timeout or invalid length")
            if ack.payload[0] != 1:
                raise SerialCliError("0x0B returned success_flg=0")

            if image.footer.module_id == 0x03:
                self._poll_llc_pfc_forward_progress(dst=dst, d_dst=d_dst, total_bytes=len(image.data))
            else:
                self._poll_application_ready(dst=dst, d_dst=d_dst, total_bytes=len(image.data))
        except Exception as exc:
            state = "stopped" if isinstance(exc, SerialCliError) and str(exc) == "upgrade stopped" else "failed"
            self._set_upgrade_status(state=state, detail=str(exc), stage=state)

    def _poll_application_ready(self, *, dst: int, d_dst: int, total_bytes: int) -> None:
        deadline = time.monotonic() + 75.0

        while time.monotonic() < deadline:
            self._raise_if_upgrade_stopped()
            self._set_upgrade_status(
                state="running",
                detail="upgrade completed; waiting for application parameter service",
                sent_bytes=total_bytes,
                total_bytes=total_bytes,
                stage="app_wait",
            )
            frames = self._upgrade_request(cmd_word=0x01, payload=b"\x00", dst=dst, d_dst=d_dst, wait_seconds=1.0)
            ack = self._find_ack(frames, 0x01)
            if ack is not None and len(ack.payload) >= 4:
                param_count = int.from_bytes(ack.payload[:4], "little")
                self._set_upgrade_status(
                    state="done",
                    detail=f"upgrade completed; application parameter service ready, count={param_count}",
                    sent_bytes=total_bytes,
                    total_bytes=total_bytes,
                    stage="app_ready",
                    extra={"param_count": param_count},
                )
                return
            time.sleep(0.5)

        self._set_upgrade_status(
            state="done",
            detail="upgrade completed; application parameter service did not become ready within 75s",
            sent_bytes=total_bytes,
            total_bytes=total_bytes,
            stage="app_timeout",
        )

    def _poll_llc_pfc_forward_progress(self, *, dst: int, d_dst: int, total_bytes: int) -> None:
        while not self.upgrade_stop_event.is_set():
            frames = self._upgrade_request(
                cmd_word=CMD_WORD_LLC_PFC_UPGRADE_PROGRESS_QUERY,
                payload=build_llc_pfc_upgrade_progress_query_payload(),
                dst=dst,
                d_dst=d_dst,
                wait_seconds=3.0,
            )
            ack = self._find_ack(frames, CMD_WORD_LLC_PFC_UPGRADE_PROGRESS_QUERY)
            if ack is None:
                self._set_upgrade_status(state="running", detail="waiting for LLC -> PFC progress", total_bytes=total_bytes, stage="0x0D")
                time.sleep(1.0)
                continue
            progress = parse_llc_pfc_upgrade_progress_ack(ack.payload)
            forwarded = int(progress["forwarded_bytes"])
            total = int(progress["total_bytes"]) or total_bytes
            detail = (
                f"LLC -> PFC {progress['stage_name']} {progress['result_name']} "
                f"{forwarded}/{total} error={progress['error_name']}"
            )
            self._set_upgrade_status(state="running", detail=detail, sent_bytes=forwarded, total_bytes=total, stage="0x0D", extra=progress)
            if str(progress["result_name"]) == "success" or str(progress["stage_name"]) == "done":
                self._set_upgrade_status(state="done", detail="upgrade completed; LLC finished forwarding PFC firmware", sent_bytes=total, total_bytes=total, stage="done", extra=progress)
                return
            if str(progress["result_name"]) == "failed" or str(progress["stage_name"]) == "failed":
                raise SerialCliError(f"LLC -> PFC forwarding failed: {progress['error_name']}")
            time.sleep(1.0)
        self._raise_if_upgrade_stopped()

    def _upgrade_request(self, *, cmd_word: int, payload: bytes, dst: int, d_dst: int, wait_seconds: float) -> list[ProtocolFrame]:
        deadline = time.monotonic() + wait_seconds
        last_frames: list[ProtocolFrame] = []
        while time.monotonic() < deadline:
            self._raise_if_upgrade_stopped()
            if self.client is None:
                raise SerialCliError("serial disconnected")
            last_frames = self.client.request(cmd_set=0x01, cmd_word=cmd_word, payload=payload, timeout=min(self.options.timeout, 1.0), dst=dst, d_dst=d_dst)
            if self._find_ack(last_frames, cmd_word) is not None:
                return last_frames
        return last_frames

    def _raise_if_upgrade_stopped(self) -> None:
        if self.upgrade_stop_event.is_set():
            raise SerialCliError("upgrade stopped")

    @staticmethod
    def _find_ack(frames: list[ProtocolFrame], cmd_word: int) -> ProtocolFrame | None:
        for frame in frames:
            if frame.cmd_word == cmd_word and frame.is_ack == 1:
                return frame
        return None

    def _upgrade_is_active(self) -> bool:
        thread = self.upgrade_thread
        return thread is not None and thread.is_alive()

    def _set_upgrade_status(
        self,
        *,
        state: str,
        detail: str,
        stage: str,
        sent_bytes: int | None = None,
        total_bytes: int | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        with self.upgrade_lock:
            if sent_bytes is None:
                sent_bytes = int(self.upgrade_status.get("sent_bytes", 0) or 0)
            if total_bytes is None:
                total_bytes = int(self.upgrade_status.get("total_bytes", 0) or 0)
            percent = (sent_bytes * 100.0 / total_bytes) if total_bytes > 0 else 0.0
            status: dict[str, object] = {
                "state": state,
                "stage": stage,
                "detail": detail,
                "sent_bytes": sent_bytes,
                "total_bytes": total_bytes,
                "percent": f"{percent:.1f}",
            }
            if extra:
                status.update(extra)
            self.upgrade_status = status

    def _upgrade_status_snapshot(self) -> dict[str, object]:
        with self.upgrade_lock:
            status = dict(self.upgrade_status)
        status["active"] = self._upgrade_is_active()
        return status

    def _blackbox(self, args: list[str]) -> None:
        if len(args) < 3 or args[0] != "read":
            print("usage: blackbox read <start_offset> <length>")
            return
        frames = self._request(
            cmd_word=CMD_WORD_BLACK_BOX_RANGE_QUERY,
            payload=build_black_box_range_query_payload(int(args[1], 0), int(args[2], 0)),
            timeout=max(self.options.timeout, 2.0),
        )
        rows = []
        for frame in frames:
            if frame.cmd_word == CMD_WORD_BLACK_BOX_RANGE_QUERY and frame.is_ack == 1:
                rows.append({"kind": "ack", **parse_black_box_range_query_ack(frame.payload)})
            elif frame.cmd_word == CMD_WORD_BLACK_BOX_HEADER:
                rows.append({"kind": "header", **parse_black_box_header_payload(frame.payload)})
            elif frame.cmd_word == CMD_WORD_BLACK_BOX_ROW:
                rows.append({"kind": "row", **parse_black_box_row_payload(frame.payload)})
            elif frame.cmd_word == CMD_WORD_BLACK_BOX_COMPLETE:
                rows.append({"kind": "complete", **parse_black_box_complete_payload(frame.payload)})
        print(format_output(rows, output_format="table"))

    def _factory(self, args: list[str]) -> None:
        if len(args) < 2:
            print("usage: factory time read | factory time set-now [timezone] | factory cali read <id> | factory cali write <id> <gain> <bias> | factory cali save")
            return
        group, action = args[0], args[1]
        if group == "time" and action == "read":
            frames = self._request(cmd_word=CMD_WORD_FACTORY_TIME_QUERY, payload=build_factory_time_query_payload())
            for frame in frames:
                if frame.cmd_word == CMD_WORD_FACTORY_TIME_QUERY and frame.is_ack == 1:
                    info = parse_factory_time_payload(frame.payload)
                    info["time_text"] = format_factory_time_string(int(info["unix_time_utc"]), int(info["timezone_half_hour"]))
                    print(format_output(info, output_format="table"))
                    return
            raise SerialCliError("factory time read timeout")
        if group == "time" and action == "set-now":
            timezone_half_hour = parse_timezone_input(args[2] if len(args) >= 3 else "+8")
            frames = self._request(cmd_word=CMD_WORD_FACTORY_TIME_WRITE, payload=build_factory_time_write_payload(int(time.time()), timezone_half_hour))
            print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))
            return
        if group == "cali" and action == "read" and len(args) >= 3:
            frames = self._request(cmd_word=CMD_WORD_FACTORY_CALI_READ, payload=build_factory_cali_read_payload(int(args[2], 0)))
            for frame in frames:
                if frame.cmd_word == CMD_WORD_FACTORY_CALI_READ and frame.is_ack == 1:
                    print(format_output(parse_factory_cali_payload(frame.payload), output_format="table"))
                    return
            raise SerialCliError("factory calibration read timeout")
        if group == "cali" and action == "write" and len(args) >= 5:
            frames = self._request(
                cmd_word=CMD_WORD_FACTORY_CALI_WRITE,
                payload=build_factory_cali_write_payload(int(args[2], 0), float(args[3]), float(args[4])),
            )
            print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))
            return
        if group == "cali" and action == "save":
            frames = self._request(cmd_word=CMD_WORD_FACTORY_CALI_SAVE, payload=build_factory_cali_save_payload())
            print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))
            return
        print("usage: factory time read | factory time set-now [timezone] | factory cali read <id> | factory cali write <id> <gain> <bias> | factory cali save")

    def _perf(self, args: list[str]) -> None:
        if not args:
            print("usage: perf info | perf summary | perf dict [filter] | perf sample [filter] | perf pull [filter] | perf reset")
            return
        action = args[0]
        if action == "info":
            frames = self._request(cmd_word=CMD_WORD_PERF_INFO_QUERY)
            for frame in frames:
                if frame.cmd_word == CMD_WORD_PERF_INFO_QUERY and frame.is_ack == 1:
                    print(format_output(asdict(parse_perf_info_payload(frame.payload)), output_format="table"))
                    return
            raise SerialCliError("perf info timeout")
        if action == "summary":
            frames = self._request(cmd_word=CMD_WORD_PERF_SUMMARY_QUERY)
            for frame in frames:
                if frame.cmd_word == CMD_WORD_PERF_SUMMARY_QUERY and frame.is_ack == 1:
                    print(format_output(asdict(parse_perf_summary_payload(frame.payload)), output_format="table"))
                    return
            print("perf summary command timed out; calculating from sample all...")
            entries, version = self._perf_dict_entries(PERF_FILTER_ALL)
            rows = self._perf_sample_records(PERF_FILTER_ALL, entries, version)
            print(format_output(_perf_summary_from_rows(rows), output_format="table"))
            return
        if action == "reset":
            frames = self._request(cmd_word=CMD_WORD_PERF_RESET_PEAK)
            print(format_output([_frame_to_dict(frame) for frame in frames], output_format="table"))
            return
        if action in {"dict", "sample", "pull"}:
            type_filter = parse_perf_filter(args[1] if len(args) >= 2 else "all")
            entries, version = self._perf_dict_entries(type_filter)
            if action == "dict":
                rows = [
                    {"index": entry.index, "record_id": entry.record_id, "type": entry.record_type, "name": entry.name}
                    for entry in entries
                ]
                print(format_output(rows, output_format="table"))
                return
            if action == "pull":
                print(format_output(
                    [{"index": entry.index, "record_id": entry.record_id, "type": entry.record_type, "name": entry.name} for entry in entries],
                    output_format="table",
                ))
            self._perf_sample(type_filter, entries, version)
            return
        print("usage: perf info | perf summary | perf dict [filter] | perf sample [filter] | perf pull [filter] | perf reset")

    def _perf_dict_entries(self, type_filter: int) -> tuple[list[PerfDictEntry], int]:
        frames = self._request(cmd_word=CMD_WORD_PERF_DICT_QUERY, payload=build_perf_dict_query_payload(type_filter, 0), timeout=2.0)
        entries: list[PerfDictEntry] = []
        version = 0
        expected_count = 0
        sequence = None
        for frame in frames:
            if frame.cmd_word == CMD_WORD_PERF_DICT_QUERY and frame.is_ack == 1:
                ack = parse_perf_dict_ack_payload(frame.payload)
                if not ack.accepted:
                    raise SerialCliError(f"perf dict rejected: {ack.reject_reason}")
                sequence = ack.sequence
                expected_count = ack.record_count
                version = ack.dict_version
            elif frame.cmd_word == CMD_WORD_PERF_DICT_ITEM_REPORT:
                entry = parse_perf_dict_item_payload(frame.payload)
                if sequence is None or entry.sequence == sequence:
                    entries.append(entry)
            elif frame.cmd_word == CMD_WORD_PERF_DICT_END:
                end = parse_perf_dict_end_payload(frame.payload)
                if end.status != 0:
                    raise SerialCliError(f"perf dict end status: {describe_perf_end_status(end.status)}")
                version = end.dict_version
        if sequence is None:
            raise SerialCliError("perf dict timeout: no ACK received")
        if expected_count and not entries:
            raise SerialCliError(f"perf dict returned no entries: expected={expected_count}, sequence={sequence}, version={version}. Try again or increase the timeout.")
        return sorted(entries, key=lambda item: item.index), version

    def _perf_sample(self, type_filter: int, entries: list[PerfDictEntry], version: int) -> None:
        print(format_output(self._perf_sample_records(type_filter, entries, version), output_format="table"))

    def _perf_sample_records(self, type_filter: int, entries: list[PerfDictEntry], version: int) -> list[dict[str, object]]:
        entry_map = {entry.record_id: entry for entry in entries}
        frames = self._request(cmd_word=CMD_WORD_PERF_SAMPLE_QUERY, payload=build_perf_sample_query_payload(type_filter, version), timeout=2.0)
        rows = []
        sequence = None
        for frame in frames:
            if frame.cmd_word == CMD_WORD_PERF_SAMPLE_QUERY and frame.is_ack == 1:
                ack = parse_perf_sample_ack_payload(frame.payload)
                if not ack.accepted:
                    raise SerialCliError(f"perf sample rejected: {ack.reject_reason}")
                sequence = ack.sequence
            elif frame.cmd_word == CMD_WORD_PERF_SAMPLE_BATCH_REPORT:
                batch = parse_perf_sample_batch_payload(frame.payload, entry_map)
                if sequence is None or batch.sequence == sequence:
                    rows.extend(asdict(record) for record in batch.records)
            elif frame.cmd_word == CMD_WORD_PERF_SAMPLE_END:
                end = parse_perf_sample_end_payload(frame.payload)
                if end.status != 0:
                    raise SerialCliError(f"perf sample end status: {describe_perf_end_status(end.status)}")
        return rows

    def _scope(self, args: list[str]) -> None:
        if not args:
            print("usage: scope list | scope info <id> | scope vars <id> [count] | scope start|trigger|stop|reset <id> | scope sample <id> <index> [tag] [force]")
            return
        action = args[0]
        if action == "list":
            frames = self._request(cmd_word=CMD_WORD_SCOPE_LIST_QUERY, payload=build_scope_list_query_payload())
            rows = [parse_scope_list_item_payload(frame.payload) for frame in frames if frame.cmd_word == CMD_WORD_SCOPE_LIST_QUERY]
            print(format_output(rows, output_format="table"))
        elif action == "info" and len(args) >= 2:
            scope_id = int(args[1], 0)
            frames = self._request(cmd_word=CMD_WORD_SCOPE_INFO_QUERY, payload=build_scope_info_query_payload(scope_id))
            for frame in frames:
                if frame.cmd_word == CMD_WORD_SCOPE_INFO_QUERY and frame.is_ack == 1:
                    info = parse_scope_info_ack_payload(frame.payload)
                    info["state_text"] = describe_scope_state(int(info["state"]))
                    info["status_text"] = describe_scope_status(int(info["status"]))
                    print(format_output(info, output_format="table"))
                    return
            raise SerialCliError("scope info timeout")
        elif action == "vars" and len(args) >= 2:
            scope_id = int(args[1], 0)
            count = int(args[2], 0) if len(args) >= 3 else 2
            rows = []
            for index in range(count):
                frames = self._request(cmd_word=CMD_WORD_SCOPE_VAR_QUERY, payload=build_scope_var_query_payload(scope_id, index))
                rows.extend(parse_scope_var_ack_payload(frame.payload) for frame in frames if frame.cmd_word == CMD_WORD_SCOPE_VAR_QUERY)
            print(format_output(rows, output_format="table"))
        elif action in {"start", "trigger", "stop", "reset"} and len(args) >= 2:
            cmd_word = {
                "start": CMD_WORD_SCOPE_START,
                "trigger": CMD_WORD_SCOPE_TRIGGER,
                "stop": CMD_WORD_SCOPE_STOP,
                "reset": CMD_WORD_SCOPE_RESET,
            }[action]
            frames = self._request(cmd_word=cmd_word, payload=build_scope_simple_command_payload(int(args[1], 0)))
            for frame in frames:
                if frame.cmd_word == cmd_word and frame.is_ack == 1:
                    ack = parse_scope_control_ack_payload(frame.payload)
                    ack["state_text"] = describe_scope_state(int(ack["state"]))
                    ack["status_text"] = describe_scope_status(int(ack["status"]))
                    print(format_output(ack, output_format="table"))
                    return
            raise SerialCliError(f"scope {action} timeout")
        elif action == "sample" and len(args) >= 3:
            scope_id = int(args[1], 0)
            index = int(args[2], 0)
            tag = int(args[3], 0) if len(args) >= 4 else 0
            force = len(args) >= 5 and args[4].lower() in {"force", "1", "true", "yes", "on"}
            mode = SCOPE_READ_MODE_FORCE if force else SCOPE_READ_MODE_NORMAL
            frames = self._request(cmd_word=CMD_WORD_SCOPE_SAMPLE_QUERY, payload=build_scope_sample_query_payload(scope_id, mode, index, tag), timeout=2.0)
            for frame in frames:
                if frame.cmd_word == CMD_WORD_SCOPE_SAMPLE_QUERY and frame.is_ack == 1:
                    sample = parse_scope_sample_ack_payload(frame.payload)
                    sample["status_text"] = describe_scope_status(int(sample["status"]))
                    print(format_output(sample, output_format="table"))
                    return
            raise SerialCliError("scope sample timeout")
        else:
            print("usage: scope list | scope info <id> | scope vars <id> [count] | scope start|trigger|stop|reset <id> | scope sample <id> <index> [tag] [force]")

    def _sfra(self, args: list[str]) -> None:
        if not args:
            print("usage: sfra list | sfra info <id> | sfra config <id> <start_hz> <stop_hz> <amplitude> | sfra start|stop|reset <id> | sfra point <id> <index> [tag]")
            return
        action = args[0]
        if action == "list":
            frames = self._request(cmd_word=CMD_WORD_SFRA_LIST_QUERY, payload=build_sfra_list_query_payload())
            rows = [parse_sfra_list_item_payload(frame.payload) for frame in frames if frame.cmd_word == CMD_WORD_SFRA_LIST_QUERY]
            print(format_output(rows, output_format="table"))
        elif action == "info" and len(args) >= 2:
            sfra_id = int(args[1], 0)
            frames = self._request(cmd_word=CMD_WORD_SFRA_INFO_QUERY, payload=build_sfra_info_query_payload(sfra_id))
            for frame in frames:
                if frame.cmd_word == CMD_WORD_SFRA_INFO_QUERY and frame.is_ack == 1:
                    info = parse_sfra_info_ack_payload(frame.payload)
                    info["state_text"] = describe_sfra_state(int(info["state"]))
                    info["status_text"] = describe_sfra_status(int(info["status"]))
                    print(format_output(info, output_format="table"))
                    return
            raise SerialCliError("sfra info timeout")
        elif action == "config" and len(args) >= 5:
            sfra_id = int(args[1], 0)
            payload = build_sfra_config_set_payload(
                sfra_id,
                SFRA_APPLY_RANGE | SFRA_APPLY_AMPLITUDE,
                float(args[2]),
                float(args[3]),
                float(args[4]),
            )
            frames = self._request(cmd_word=CMD_WORD_SFRA_CFG_SET, payload=payload)
            self._print_sfra_control_ack(frames, CMD_WORD_SFRA_CFG_SET)
        elif action in {"start", "stop", "reset"} and len(args) >= 2:
            cmd_word = {"start": CMD_WORD_SFRA_START, "stop": CMD_WORD_SFRA_STOP, "reset": CMD_WORD_SFRA_RESET}[action]
            frames = self._request(cmd_word=cmd_word, payload=build_sfra_simple_command_payload(int(args[1], 0)))
            self._print_sfra_control_ack(frames, cmd_word)
        elif action == "point" and len(args) >= 3:
            sfra_id = int(args[1], 0)
            point_index = int(args[2], 0)
            tag = int(args[3], 0) if len(args) >= 4 else 0
            frames = self._request(cmd_word=CMD_WORD_SFRA_POINT_QUERY, payload=build_sfra_point_query_payload(sfra_id, point_index, tag))
            for frame in frames:
                if frame.cmd_word == CMD_WORD_SFRA_POINT_QUERY and frame.is_ack == 1:
                    point = parse_sfra_point_payload(frame.payload)
                    point["status_text"] = describe_sfra_status(int(point["status"]))
                    print(format_output(point, output_format="table"))
                    return
            raise SerialCliError("sfra point timeout")
        else:
            print("usage: sfra list | sfra info <id> | sfra config <id> <start_hz> <stop_hz> <amplitude> | sfra start|stop|reset <id> | sfra point <id> <index> [tag]")

    def _print_sfra_control_ack(self, frames: list[ProtocolFrame], cmd_word: int) -> None:
        for frame in frames:
            if frame.cmd_word == cmd_word and frame.is_ack == 1:
                ack = parse_sfra_control_ack_payload(frame.payload)
                ack["state_text"] = describe_sfra_state(int(ack["state"]))
                ack["status_text"] = describe_sfra_status(int(ack["status"]))
                print(format_output(ack, output_format="table"))
                return
        raise SerialCliError(f"sfra command 0x{cmd_word:02X} timeout")

    def _trace(self, args: list[str]) -> None:
        if not args:
            print("usage: trace start [seconds] | trace stop")
            return
        enable = args[0] == "start"
        listen_seconds = float(args[1]) if enable and len(args) >= 2 else 0.0
        frames = self._request(cmd_word=CMD_WORD_TRACE_CONTROL, payload=build_trace_control_payload(enable))
        rows = []
        unit_us = 100
        for frame in frames:
            if frame.cmd_word == CMD_WORD_TRACE_CONTROL and frame.is_ack == 1:
                ack = parse_trace_control_ack_payload(frame.payload)
                unit_us = ack.time_unit_us
                rows.append(ack.__dict__)
        if enable and listen_seconds > 0:
            frames = self.client.read_frames(timeout=listen_seconds) if self.client is not None else []
            for frame in frames:
                if frame.cmd_word == CMD_WORD_TRACE_RECORD_REPORT:
                    record = parse_trace_record_report_payload(frame.payload)
                    rows.append({"time_tick": record.time_tick, "time_us": record.time_tick * unit_us, "line": record.line})
        print(format_output(rows, output_format="table"))

    def _jlink(self, args: list[str]) -> None:
        if not args:
            print(_jlink_usage())
            return
        action = args[0]
        if action == "elf" and len(args) >= 2:
            path = _validate_jlink_symbol_path(Path(args[1]), "ELF/AXF")
            self._save_jlink_symbol_paths(elf_path=path, map_path=None, keep_map=True)
            self._load_jlink_symbols(force=True)
            print(f"J-Link ELF saved: {path}")
            return
        if action == "map" and len(args) >= 2:
            map_path = None if args[1] in {"-", ""} else _validate_jlink_symbol_path(Path(args[1]), "MAP")
            self._save_jlink_symbol_paths(elf_path=None, map_path=map_path, keep_elf=True)
            self._load_jlink_symbols(force=True)
            print(f"J-Link MAP saved: {map_path if map_path else '-'}")
            return
        if action == "device" and len(args) >= 2:
            speed = int(args[2], 0) if len(args) >= 3 else None
            self._save_jlink_device(args[1], speed)
            print(f"J-Link device saved: {args[1]}{f' @ {speed} kHz' if speed is not None else ''}")
            return
        if action == "load":
            variables = self._load_jlink_symbols(force=True)
            print(f"J-Link symbols loaded: {len(variables)} variable(s)")
            return
        if action == "list":
            variables = self._load_jlink_symbols()
            name_filter = args[1].lower() if len(args) >= 2 else ""
            limit = int(args[2], 0) if len(args) >= 3 else 200
            rows = [_jlink_variable_row(variable) for variable in _jlink_top_level_variables(variables, name_filter)[:limit]]
            print(format_output(rows, output_format="table"))
            print(f"{len(rows)}/{len(variables)} variable(s) shown")
            return
        if action == "search":
            if len(args) < 2:
                print("usage: jlink search <keyword> [limit]")
                return
            variables = self._load_jlink_symbols()
            keyword = args[1].lower()
            limit = int(args[2], 0) if len(args) >= 3 else 200
            top_level = _jlink_top_level_variables(variables, "")
            matches = [variable for variable in top_level if keyword in variable.name.lower()]
            rows = [_jlink_variable_row(variable) for variable in matches[:limit]]
            print(format_output(rows, output_format="table"))
            print(f"{len(rows)}/{len(matches)} matched top-level variable(s), total {len(top_level)}")
            return
        if action in {"funcs", "functions"}:
            self._load_jlink_symbols()
            name_filter = args[1].lower() if len(args) >= 2 else ""
            limit = int(args[2], 0) if len(args) >= 3 else 200
            rows, matched_count = _jlink_function_rows(self.jlink_service.function_names, self.jlink_service.function_locations, name_filter, limit)
            print(format_output(rows, output_format="table"))
            print(f"{len(rows)}/{matched_count} function(s) shown")
            return
        if action == "connect" and len(args) >= 2:
            device = args[1]
            speed = int(args[2], 0) if len(args) >= 3 else 4000
            print(self.jlink_service.test_connection(JLinkSettings(executable="", device=device, interface="SWD", speed_khz=speed)))
            return
        if action == "read":
            if len(args) >= 2 and _looks_like_symbol_path(args[1]):
                elf_path, map_path, device, speed, name_filter, limit = _resolve_jlink_shell_read_args(args[1:])
                variables = self.jlink_service.load_variables(elf_path=elf_path, map_path=map_path)
                if name_filter:
                    variables = [item for item in variables if name_filter in item.name.lower()]
                variables = variables[:limit]
                values = self.jlink_service.read_variables(variables, JLinkSettings(executable="", device=device, interface="SWD", speed_khz=speed))
                rows = [_jlink_variable_row(item) for item in values]
                print(format_output(rows, output_format="table"))
                print(f"{sum(1 for item in values if item.status == 'OK')}/{len(values)} variables read, shown {len(rows)}")
                return
            expression = args[1] if len(args) >= 2 else ""
            depth = int(args[2], 0) if len(args) >= 3 and _looks_like_number(args[2]) else 1
            if not expression:
                print("usage: jlink read <expression> [depth]")
                return
            rows = self._read_jlink_expression(expression, max(depth, 0))
            print(format_output(rows, output_format="table"))
            return
        if action == "write" and len(args) >= 3:
            updated = self._write_jlink_expression(args[1], " ".join(args[2:]))
            print(format_output([_jlink_variable_row(updated, expression=args[1])], output_format="table"))
            return
        if action == "source":
            if len(args) < 2:
                print("usage: jlink source <expression|symbol|address> [context_lines]")
                return
            context = int(args[2], 0) if len(args) >= 3 else None
            print(self._jlink_source(args[1], context))
            return
        print(_jlink_usage())

    def _save_jlink_symbol_paths(self, *, elf_path: Path | None, map_path: Path | None, keep_elf: bool = False, keep_map: bool = False) -> None:
        saved_elf, saved_map, _, _ = _load_saved_jlink_shell_config()
        elf_to_save = saved_elf if keep_elf else elf_path
        map_to_save = saved_map if keep_map else map_path
        _save_jlink_shell_config(elf_path=elf_to_save, map_path=map_to_save, device=None, speed=None)
        self.jlink_loaded_paths = (None, None)
        self.jlink_variables = []

    def _save_jlink_device(self, device: str, speed: int | None) -> None:
        saved_elf, saved_map, _, saved_speed = _load_saved_jlink_shell_config()
        _save_jlink_shell_config(elf_path=saved_elf, map_path=saved_map, device=device, speed=speed or saved_speed)

    def _load_jlink_symbols(self, *, force: bool = False) -> list[DebugVariable]:
        elf_path, map_path, _, _ = _load_saved_jlink_shell_config()
        if elf_path is None and map_path is None:
            raise SerialCliError("J-Link symbols are not configured. Run: jlink elf <path> and/or jlink map <path>.")
        _validate_optional_file(elf_path, "ELF/AXF")
        _validate_optional_file(map_path, "MAP")
        paths = (elf_path, map_path)
        if force or not self.jlink_variables or self.jlink_loaded_paths != paths:
            self.jlink_variables = self.jlink_service.load_variables(elf_path=elf_path, map_path=map_path)
            self.jlink_loaded_paths = paths
        return list(self.jlink_variables)

    def _jlink_settings(self) -> JLinkSettings:
        elf_path, map_path, device, speed = _load_saved_jlink_shell_config()
        if not device:
            device = infer_jlink_device(elf_path=elf_path, map_path=map_path)
        if not device:
            raise SerialCliError("J-Link device is empty. Run: jlink device <target> [speed_khz].")
        return JLinkSettings(executable="", device=device, interface="SWD", speed_khz=speed)

    def _read_jlink_expression(self, expression: str, depth: int) -> list[dict[str, object]]:
        variable = self._resolve_jlink_expression(expression, read_pointers=True)
        refreshed = self.jlink_service.read_variables([variable], self._jlink_settings())[0]
        rows = [_jlink_variable_row(refreshed, expression=expression)]
        rows.extend(self._expand_jlink_variable(expression, refreshed, depth))
        return rows

    def _write_jlink_expression(self, expression: str, value_text: str) -> DebugVariable:
        variable = self._resolve_jlink_expression(expression, read_pointers=True)
        return self.jlink_service.write_variable(variable, value_text, self._jlink_settings())

    def _jlink_source(self, expression: str, context: int | None) -> str:
        self._load_jlink_symbols()
        elf_path, _, _, _ = _load_saved_jlink_shell_config()
        if elf_path is None:
            raise SerialCliError("J-Link source needs an ELF/AXF file. Run: jlink elf <path>.")
        if _looks_like_function_name(expression):
            try:
                location = resolve_elf_function_source_location(elf_path, expression, self.jlink_service.symbol_names)
                if location.address:
                    try:
                        address_location = resolve_elf_source_location(elf_path, location.address, self.jlink_service.symbol_names)
                        if location.file.suffix.lower() in {".h", ".hpp"} or address_location.file != location.file:
                            location = replace(address_location, symbol=location.symbol or address_location.symbol)
                    except JLinkDebugError:
                        pass
            except JLinkDebugError:
                location = self._jlink_source_location_from_address(elf_path, expression)
        else:
            location = self._jlink_source_location_from_address(elf_path, expression)
        lines = _source_context_lines(location.file, location.line, max(context, 0)) if context is not None else _source_function_lines(location.file, location.line, location.symbol)
        symbol = location.symbol or jlink_symbol_name_for_address(location.address, self.jlink_service.symbol_names) or "-"
        header = [
            f"symbol: {symbol}",
            f"address: 0x{location.address:08X}",
            f"source: {location.file}:{location.line}",
        ]
        return "\n".join(header + [""] + lines)

    def _jlink_source_location_from_address(self, elf_path: Path, expression: str):
        address = self._jlink_source_address(expression)
        try:
            return resolve_elf_source_location(elf_path, address, self.jlink_service.symbol_names)
        except JLinkDebugError as exc:
            raise SerialCliError(str(exc)) from exc

    def _jlink_source_address(self, expression: str) -> int:
        if _looks_like_int_literal(expression):
            return int(expression, 0)
        symbol_address = _jlink_symbol_address(expression, self.jlink_service.symbol_names)
        if symbol_address is None:
            symbol_address = _jlink_symbol_address(expression, self.jlink_service.function_names)
        if symbol_address is not None:
            return symbol_address
        variable = self._resolve_jlink_expression(expression, read_pointers=True)
        if "*" in variable.type_name:
            if not _jlink_is_function_pointer(variable.type_name):
                raise SerialCliError(f"J-Link source expects a function symbol, code address, or function pointer field: {expression}")
            refreshed = self.jlink_service.read_variables([variable], self._jlink_settings())[0]
            if refreshed.pointer_value is None:
                raise SerialCliError(f"Unable to read pointer value: {expression}")
            return refreshed.pointer_value
        raise SerialCliError(f"J-Link source cannot infer a function address from: {expression}")

    def _resolve_jlink_expression(self, expression: str, *, read_pointers: bool) -> DebugVariable:
        variables = self._load_jlink_symbols()
        exact = next((item for item in variables if item.name == expression), None)
        if exact is not None:
            return exact
        parts = [part for part in expression.split(".") if part]
        if not parts:
            raise SerialCliError("J-Link expression is empty.")
        current = next((item for item in variables if item.name == parts[0]), None)
        if current is None:
            raise SerialCliError(f"J-Link variable not found: {parts[0]}")
        current_expression = parts[0]
        for field in parts[1:]:
            current = self._resolve_jlink_child(current_expression, current, field, read_pointers=read_pointers)
            current_expression = f"{current_expression}.{field}"
        return current

    def _resolve_jlink_child(self, expression: str, variable: DebugVariable, field: str, *, read_pointers: bool) -> DebugVariable:
        templates = _jlink_child_templates(variable, self.jlink_service)
        template = next((item for item in templates if item.name == field or item.name.endswith(f".{field}")), None)
        if template is None:
            raise SerialCliError(f"J-Link field not found: {expression}.{field}")
        base_address = variable.address
        if "*" in variable.type_name:
            if not read_pointers:
                raise SerialCliError(f"J-Link pointer must be read before resolving fields: {expression}")
            pointer_variable = self.jlink_service.read_variables([variable], self._jlink_settings())[0]
            if pointer_variable.pointer_value is None:
                raise SerialCliError(f"Unable to read pointer value: {expression}")
            if pointer_variable.pointer_value == 0:
                raise SerialCliError(f"Pointer is NULL: {expression}")
            if not is_jlink_expandable_address(pointer_variable.pointer_value, self.jlink_service.memory_ranges):
                raise SerialCliError(f"{expression} points to unsupported address 0x{pointer_variable.pointer_value:08X}; it is outside the ELF/MAP memory ranges.")
            base_address = pointer_variable.pointer_value
        return replace(
            template,
            name=field,
            address=base_address + template.address,
            section=variable.section,
            source=variable.source,
            value="",
            raw_hex="",
            status="UNREAD",
        )

    def _expand_jlink_variable(self, expression: str, variable: DebugVariable, depth: int) -> list[dict[str, object]]:
        if depth <= 0:
            return []
        templates = _jlink_child_templates(variable, self.jlink_service)
        if not templates:
            return []
        base_address = variable.address
        if "*" in variable.type_name:
            if variable.pointer_value is None:
                variable = self.jlink_service.read_variables([variable], self._jlink_settings())[0]
            if variable.pointer_value in (None, 0):
                return []
            if not is_jlink_expandable_address(variable.pointer_value, self.jlink_service.memory_ranges):
                return []
            base_address = variable.pointer_value
        children = [
            replace(
                template,
                name=template.name,
                address=base_address + template.address,
                section=variable.section,
                source=variable.source,
                value="",
                raw_hex="",
                status="UNREAD",
            )
            for template in templates
        ]
        refreshed = self.jlink_service.read_variables(children, self._jlink_settings())
        rows: list[dict[str, object]] = []
        for child in refreshed:
            child_expression = f"{expression}.{child.name}"
            rows.append(_jlink_variable_row(child, expression=child_expression))
            rows.extend(self._expand_jlink_variable(child_expression, child, depth - 1))
        return rows

    @staticmethod
    def _print_help() -> None:
        print(
            """
commands:
  ports
  connect [COMx|jlink] [baud] [timeout]   default: connect COM8 921600
  disconnect
  status
  raw text <text> | raw hex <AA 55 ...> | raw read [seconds] | raw query <text> [seconds]
  home enable | home disable | home read | home set <rms> <freq>
  param list
  param read <name>
  param write <name> <type_id> <value> [min] [max]
  param wave <name> on|off
  wave period <ms> | wave start [period_ms] | wave stop | wave read [seconds]
  upgrade load <firmware.bin> | upgrade info
  upgrade start normal|force [dst] [d_dst] | upgrade progress | upgrade stop
  upgrade version [dst] [d_dst]
  blackbox read <start_offset> <length>
  factory time read | factory time set-now [timezone]
  factory cali read <id> | factory cali write <id> <gain> <bias> | factory cali save
  perf info | perf summary | perf dict [all|task|interrupt|code] | perf sample [filter] | perf pull [filter] | perf reset
  scope list | scope info <id> | scope vars <id> [count]
  scope start|trigger|stop|reset <id> | scope sample <id> <index> [tag] [force]
  sfra list | sfra info <id> | sfra config <id> <start_hz> <stop_hz> <amplitude>
  sfra start|stop|reset <id> | sfra point <id> <index> [tag]
  trace start [seconds] | trace stop
  jlink elf <path> | jlink map <path|->
  jlink device <target> [speed_khz] | jlink connect <target> [speed_khz]
  jlink load | jlink list [filter] [limit] | jlink search <keyword> [limit]
  jlink funcs [filter] [limit]
  jlink read <expression> [depth] | jlink write <expression> <value>
  jlink source <expression|symbol|address> [context_lines]
  auto prefix: explicit commands remember their prefix; bare input reuses it
  exit
""".strip()
        )


def run_terminal_shell() -> int:
    return FrameTerminalShell().run()


def _parse_hex_bytes(text: str) -> bytes:
    tokens = text.replace(",", " ").split()
    return bytes(int(token, 16) for token in tokens)


def _split_command_line(line: str) -> list[str]:
    args = shlex.split(line, posix=False)
    return [_strip_matching_quotes(arg) for arg in args]


def _looks_like_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _jlink_usage() -> str:
    return "\n".join(
        [
            "usage:",
            "  jlink elf <elf-or-axf>",
            "  jlink map <map|->",
            "  jlink device <target> [speed_khz]",
            "  jlink load",
            "  jlink list [filter] [limit]",
            "  jlink search <keyword> [limit]",
            "  jlink funcs [filter] [limit]",
            "  jlink read <expression> [depth]",
            "  jlink write <expression> <value>",
            "  jlink source <expression|symbol|address> [context_lines]",
            "  jlink connect <target> [speed_khz]",
            "",
            "examples:",
            r"  jlink elf D:\project\build\demo.elf",
            r"  jlink map D:\project\build\demo.map",
            "  jlink list p_init 20",
            "  jlink search p_init 20",
            "  jlink funcs task 20",
            "  jlink read p_init_first 2",
            "  jlink read p_init_first.p_next 1",
            "  jlink write reg_init_bsp_init.priority 1",
            "  jlink source p_init_first.p_next.p_func 6",
            "  jlink source bsp_gpio_init 6",
        ]
    )


def _validate_jlink_symbol_path(path: Path, label: str) -> Path:
    if not path.is_file():
        raise SerialCliError(f"J-Link {label} file does not exist: {path}")
    suffix = path.suffix.lower()
    allowed = {".elf", ".axf"} if label == "ELF/AXF" else {".map"}
    if suffix not in allowed:
        raise SerialCliError(f"J-Link {label} file has unsupported suffix: {path}")
    return path


def _save_jlink_shell_config(*, elf_path: Path | None, map_path: Path | None, device: str | None, speed: int | None) -> None:
    config_file = get_app_paths().app_config_file

    ui_section = load_config_section(config_file, "ui_settings")
    ui_values_raw = ui_section.get("values")
    ui_values = dict(ui_values_raw) if isinstance(ui_values_raw, dict) else {}
    ui_values["jlink.elf_path"] = str(elf_path) if elf_path is not None else ""
    ui_values["jlink.map_path"] = str(map_path) if map_path is not None else ""
    if device is not None:
        ui_values["jlink.target_device"] = device
    if speed is not None:
        ui_values["jlink.speed_khz"] = str(speed)
    ui_section["version"] = ui_section.get("version", 1)
    ui_section["values"] = ui_values
    save_config_section(config_file, "ui_settings", ui_section)

    jlink_section = load_config_section(config_file, "jlink")
    files_raw = jlink_section.get("files")
    files = dict(files_raw) if isinstance(files_raw, dict) else {}
    files["elf_path"] = str(elf_path) if elf_path is not None else ""
    files["map_path"] = str(map_path) if map_path is not None else ""
    jlink_section["files"] = files
    if device is not None and device.strip():
        history_raw = jlink_section.get("target_history")
        history = [item for item in history_raw if isinstance(item, str)] if isinstance(history_raw, list) else []
        normalized = device.strip()
        jlink_section["target_history"] = [normalized] + [item for item in history if item != normalized]
    save_config_section(config_file, "jlink", jlink_section)


def _jlink_variable_row(variable: DebugVariable, *, expression: str | None = None) -> dict[str, object]:
    return {
        "expression": expression or variable.name,
        "value": variable.value,
        "type": variable.type_name,
        "address": f"0x{variable.address:08X}",
        "raw": variable.raw_hex,
        "status": variable.status,
    }


def _jlink_function_rows(function_names: dict[int, str], function_locations: dict[str, object], name_filter: str, limit: int) -> tuple[list[dict[str, object]], int]:
    deduped: dict[str, int | None] = {}
    for address, name in function_names.items():
        current = deduped.get(name)
        if current is None or (address & 1 and not current & 1):
            deduped[name] = address
    for name, location in function_locations.items():
        deduped.setdefault(name, getattr(location, "address", 0) or None)
    items = sorted(deduped.items(), key=lambda item: (item[0].lower(), item[1] or 0))
    matched_count = sum(1 for name, _ in items if name_filter in name.lower())
    rows = []
    for name, address in items:
        if name_filter and name_filter not in name.lower():
            continue
        location = function_locations.get(name)
        source = f"{getattr(location, 'file')}:{getattr(location, 'line')}" if location is not None else ""
        rows.append({"function": name, "address": f"0x{address:08X}" if address else "-", "source": source})
        if len(rows) >= limit:
            break
    return rows, matched_count


def _jlink_top_level_variables(variables: list[DebugVariable], name_filter: str) -> list[DebugVariable]:
    filtered = [variable for variable in variables if name_filter in variable.name.lower()]
    top_level = [variable for variable in filtered if "." not in variable.name and "[" not in variable.name]
    return top_level or filtered


def _jlink_child_templates(variable: DebugVariable, service: JLinkVariableService) -> tuple[DebugVariable, ...]:
    if variable.child_templates:
        return variable.child_templates
    if "*" not in variable.type_name:
        return ()
    templates = service.type_templates.get(jlink_type_template_key(variable.type_name))
    if templates:
        return templates
    normalized = " ".join(variable.type_name.replace("const", "").replace("volatile", "").replace("*", "").split())
    return service.type_templates.get(jlink_type_template_key(normalized), ())


def _jlink_is_function_pointer(type_name: str) -> bool:
    normalized = type_name.replace("const", "").replace("volatile", "").strip().lower()
    return "*" in normalized and ("subroutine" in normalized or "function" in normalized or "func" in normalized)


def _looks_like_function_name(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]*", text)) and "." not in text.strip(".")


def _looks_like_int_literal(text: str) -> bool:
    try:
        int(text, 0)
    except ValueError:
        return False
    return True


def _jlink_symbol_address(symbol: str, symbol_names: dict[int, str]) -> int | None:
    for address, name in symbol_names.items():
        if name == symbol:
            return address
    return None


def _source_context_lines(path: Path, line: int, context: int) -> list[str]:
    if not path.is_file():
        return [f"(source file not found: {path})"]
    source_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not source_lines:
        return ["(source file is empty)"]
    target = max(line, 1)
    start = max(1, target - context)
    end = min(len(source_lines), target + context)
    width = len(str(end))
    rows = []
    for number in range(start, end + 1):
        marker = ">" if number == target else " "
        rows.append(f"{marker} {number:>{width}} | {source_lines[number - 1]}")
    return rows


def _source_function_lines(path: Path, line: int, symbol: str = "") -> list[str]:
    if not path.is_file():
        return [f"(source file not found: {path})"]
    source_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not source_lines:
        return ["(source file is empty)"]
    target_index = max(0, min(len(source_lines) - 1, line - 1))
    named_brace_index = _find_named_function_open_brace(source_lines, symbol, target_index) if symbol else None
    brace_index = named_brace_index if named_brace_index is not None else _find_function_open_brace(source_lines, target_index)
    if brace_index is None:
        return _source_context_lines(path, line, 8)
    start_index = _find_function_signature_start(source_lines, brace_index)
    end_index = _find_matching_brace_line(source_lines, brace_index)
    if end_index is None:
        end_index = min(len(source_lines) - 1, brace_index + 80)
    width = len(str(end_index + 1))
    rows = []
    for index in range(start_index, end_index + 1):
        marker = ">" if index == target_index else " "
        rows.append(f"{marker} {index + 1:>{width}} | {source_lines[index]}")
    return rows


def _find_named_function_open_brace(lines: list[str], symbol: str, target_index: int) -> int | None:
    clean_symbol = symbol.strip()
    if not clean_symbol or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", clean_symbol):
        return None
    pattern = re.compile(rf"\b{re.escape(clean_symbol)}\s*\(")
    start = max(0, target_index - 80)
    end = min(len(lines), target_index + 80)
    for index in range(start, end):
        if not pattern.search(_strip_line_comment(lines[index])):
            continue
        for brace_index in range(index, min(len(lines), index + 20)):
            line = _strip_line_comment(lines[brace_index])
            if "{" in line:
                return brace_index
            if line.strip().endswith(";"):
                break
    return None


def _find_function_open_brace(lines: list[str], target_index: int) -> int | None:
    for index in range(target_index, min(len(lines), target_index + 20)):
        if "{" in _strip_line_comment(lines[index]):
            return index
        stripped = lines[index].strip()
        if stripped.endswith(";"):
            return None
    for index in range(target_index, max(-1, target_index - 20), -1):
        if "{" in _strip_line_comment(lines[index]):
            return index
    return None


def _find_function_signature_start(lines: list[str], brace_index: int) -> int:
    start = brace_index
    if _strip_line_comment(lines[brace_index]).strip() == "{":
        start = max(0, brace_index - 1)
    while start > 0:
        previous = lines[start - 1].strip()
        if not previous:
            break
        if previous.endswith("*/") or previous.startswith("*") or previous.startswith("//"):
            break
        if previous.endswith(";") or previous.endswith("}"):
            break
        start -= 1
        if "(" in previous:
            break
    return start


def _find_matching_brace_line(lines: list[str], brace_index: int) -> int | None:
    depth = 0
    in_block_comment = False
    seen_open = False
    for index in range(brace_index, len(lines)):
        sanitized, in_block_comment = _sanitize_c_line(lines[index], in_block_comment)
        for char in sanitized:
            if char == "{":
                depth += 1
                seen_open = True
            elif char == "}":
                depth -= 1
                if seen_open and depth == 0:
                    return index
    return None


def _strip_line_comment(line: str) -> str:
    return line.split("//", 1)[0]


def _sanitize_c_line(line: str, in_block_comment: bool) -> tuple[str, bool]:
    output = []
    index = 0
    in_string = False
    quote = ""
    while index < len(line):
        char = line[index]
        next_char = line[index + 1] if index + 1 < len(line) else ""
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
            else:
                index += 1
            continue
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                in_string = False
            index += 1
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue
        if char == "/" and next_char == "/":
            break
        if char in {"'", '"'}:
            in_string = True
            quote = char
            index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output), in_block_comment


def _resolve_jlink_shell_read_args(args: list[str]) -> tuple[Path | None, Path | None, str, int, str, int]:
    elf_path, map_path, device, speed = _load_saved_jlink_shell_config()
    name_filter = ""
    limit = 200
    remaining = list(args)

    if remaining and _looks_like_symbol_path(remaining[0]):
        elf_path = Path(remaining.pop(0))
        if remaining and remaining[0] not in {"-", ""} and _looks_like_symbol_path(remaining[0]):
            map_path = Path(remaining.pop(0))
        elif remaining and remaining[0] in {"-", ""}:
            map_path = None
            remaining.pop(0)
        if remaining and _looks_like_jlink_device(remaining[0]):
            device = remaining.pop(0)
    elif remaining and remaining[0] in {"-", ""}:
        elf_path = None
        remaining.pop(0)

    if remaining:
        name_filter = remaining.pop(0).lower()
    if remaining:
        limit = int(remaining.pop(0), 0)

    if elf_path is None and map_path is None:
        raise SerialCliError("J-Link read needs an ELF and/or MAP file. Provide a path, or load symbol files once in the GUI so FRAME can reuse the saved config.")
    _validate_optional_file(elf_path, "ELF/AXF")
    _validate_optional_file(map_path, "MAP")
    if not device:
        device = infer_jlink_device(elf_path=elf_path, map_path=map_path)
    if not device:
        raise SerialCliError("J-Link device is empty. Provide <device>, or set Target / Device once in the GUI.")
    return elf_path, map_path, device, speed, name_filter, limit


def _load_saved_jlink_shell_config() -> tuple[Path | None, Path | None, str, int]:
    config_file = get_app_paths().app_config_file
    ui_section = load_config_section(config_file, "ui_settings")
    ui_values_raw = ui_section.get("values")
    ui_values = ui_values_raw if isinstance(ui_values_raw, dict) else {}
    jlink_section = load_config_section(config_file, "jlink")
    files_raw = jlink_section.get("files")
    file_values = files_raw if isinstance(files_raw, dict) else {}

    def config_text(*keys: str) -> str:
        for key in keys:
            value = ui_values.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            value = file_values.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def config_int(key: str, default: int) -> int:
        value = ui_values.get(key)
        if isinstance(value, str) and value.strip():
            try:
                return int(value.strip(), 0)
            except ValueError:
                return default
        if isinstance(value, int):
            return value
        return default

    elf_path = _path_or_none(config_text("jlink.elf_path", "elf_path"))
    map_path = _path_or_none(config_text("jlink.map_path", "map_path"))
    device = config_text("jlink.target_device")
    speed = config_int("jlink.speed_khz", 4000)
    return elf_path, map_path, device, speed


def _path_or_none(text: str) -> Path | None:
    return Path(text) if text else None


def _validate_optional_file(path: Path | None, label: str) -> None:
    if path is not None and not path.is_file():
        raise SerialCliError(f"Saved J-Link {label} file does not exist: {path}. Provide a valid path or reload symbol files in the GUI.")


def _looks_like_symbol_path(text: str) -> bool:
    suffix = Path(text).suffix.lower()
    return suffix in {".elf", ".axf", ".map"} or "\\" in text or "/" in text or Path(text).is_file()


def _looks_like_jlink_device(text: str) -> bool:
    upper = text.upper()
    prefixes = ("GD32", "HC32", "STM32", "AT32", "MM32", "N32", "CH32", "APM32", "PY32", "CW32", "HK32", "LPC", "MSPM0", "EFM32", "EFR32", "NRF", "RP2040")
    return upper.startswith(prefixes)


def _perf_summary_from_rows(rows: list[dict[str, object]]) -> dict[str, float | str]:
    task_load = 0.0
    task_peak = 0.0
    interrupt_load = 0.0
    interrupt_peak = 0.0
    for row in rows:
        record_type = int(row.get("record_type", 0))
        load = float(row.get("load_percent", 0.0))
        peak = float(row.get("peak_percent", 0.0))
        if record_type == PERF_RECORD_TASK:
            task_load += load
            task_peak += peak
        elif record_type == PERF_RECORD_INTERRUPT:
            interrupt_load += load
            interrupt_peak += peak
    return {
        "source": "sample",
        "task_load_percent": task_load,
        "task_peak_percent": task_peak,
        "interrupt_load_percent": interrupt_load,
        "interrupt_peak_percent": interrupt_peak,
    }


def _strip_matching_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _normalize_command_name(text: str) -> str:
    normalized = text.strip().lower()
    command = "".join(ch for ch in normalized if ch.isascii() and (ch.isalnum() or ch in {"_", "-"}))
    known = _terminal_command_names()
    aliases = {item[1:]: item for item in known if len(item) > 1}
    return aliases.get(command, command)


def _terminal_command_names() -> set[str]:
    return {
        "help",
        "ports",
        "connect",
        "disconnect",
        "status",
        "raw",
        "home",
        "param",
        "wave",
        "upgrade",
        "blackbox",
        "factory",
        "perf",
        "scope",
        "sfra",
        "trace",
        "jlink",
        "exit",
        "quit",
        "q",
    }


def _remembered_command_prefix(args: list[str]) -> tuple[str, ...]:
    if not args:
        return ()
    command = _normalize_command_name(args[0])
    if command in {"help", "ports", "disconnect", "status", "exit", "quit", "q"}:
        return ()
    subcommand_prefix_commands = {
        "raw",
        "home",
        "param",
        "wave",
        "upgrade",
        "blackbox",
        "factory",
        "perf",
        "scope",
        "sfra",
        "trace",
        "jlink",
    }
    if command in subcommand_prefix_commands and len(args) >= 2:
        return (command, args[1])
    if len(args) >= 2:
        return (command,)
    return ()


def _parse_on_off(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized in {"on", "1", "true", "yes", "start", "enable"}:
        return True
    if normalized in {"off", "0", "false", "no", "stop", "disable"}:
        return False
    raise ValueError(f"expected on/off, got: {text}")


def _parse_update_type(text: str) -> int:
    normalized = text.strip().lower()
    if normalized in {"normal", "1"}:
        return UPDATE_TYPE_NORMAL
    if normalized in {"force", "2"}:
        return UPDATE_TYPE_FORCE
    raise ValueError(f"expected normal/force, got: {text}")


def _firmware_image_to_dict(image: FirmwareImage) -> dict[str, object]:
    return {
        "path": image.path,
        "module": module_name(image.footer.module_id),
        "fw_type": image.footer.fw_type,
        "version": format_version(image.footer.version),
        "file_size": image.footer.file_size,
        "actual_size": len(image.data),
        "commit_id": image.footer.commit_id,
        "build_time": format_unix_time(image.footer.unix_time),
        "footer_crc_ok": image.footer_crc_ok,
        "payload_crc16": f"0x{image.payload_crc16:04X}",
    }


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
