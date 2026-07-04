from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import serial

from serial_debug_assistant.app_config import load_config_section
from serial_debug_assistant.app_paths import get_app_paths
from serial_debug_assistant.jlink_debug import DebugVariable, JLinkDebugError, JLinkSettings, JLinkVariableService
from serial_debug_assistant.serial_cli import (
    SerialCliError,
    SerialOptions,
    black_box_read,
    format_output,
    list_serial_ports,
    param_list,
    param_read,
    param_write,
    parse_perf_filter,
    perf_dict,
    perf_info,
    perf_reset_peak,
    perf_sample,
    perf_summary,
    protocol_request,
    raw_serial,
    scope_control,
    scope_info,
    scope_list,
    scope_sample,
    scope_vars,
    sfra_config,
    sfra_control,
    sfra_info,
    sfra_list,
    sfra_point,
    trace_control,
    write_or_print,
)
from serial_debug_assistant.terminal_shell import run_terminal_shell


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "shell"):
        return run_terminal_shell()
    if args.command == "gui":
        from serial_debug_assistant.ui.app import launch_app

        launch_app(demo_mode=getattr(args, "demo", False))
        return 0
    if args.command == "jlink":
        return _run_jlink_command(args)
    if args.command in {"serial", "proto", "param", "scope", "sfra", "perf", "trace", "blackbox"}:
        return _run_serial_protocol_command(args)
    parser.error(f"unknown command: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="frame",
        description="FRAME serial debug assistant and J-Link variable reader.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("shell", help="start interactive terminal mode")

    gui = subparsers.add_parser("gui", help="start FRAME GUI")
    gui.add_argument("--demo", action="store_true", help="start GUI in demo mode")

    jlink = subparsers.add_parser("jlink", help="load ELF/MAP symbols and read variables through J-Link")
    jlink.add_argument("--elf", type=Path, help="ELF/AXF file with symbols; defaults to saved GUI J-Link config")
    jlink.add_argument("--map", dest="map_path", type=Path, help="linker MAP file; defaults to saved GUI J-Link config")
    jlink.add_argument("--jlink", default="", help="JLink.exe/JLinkExe.exe path, or command name in PATH")
    jlink.add_argument("--device", default="", help="SEGGER device name; defaults to saved GUI J-Link config")
    jlink.add_argument("--interface", choices=("SWD", "JTAG"), help="debug interface; defaults to saved GUI J-Link config or SWD")
    jlink.add_argument("--speed", type=int, help="J-Link speed in kHz; defaults to saved GUI J-Link config or 4000")
    jlink.add_argument("--no-read", action="store_true", help="only list variables parsed from ELF/MAP")
    jlink.add_argument("--filter", default="", help="case-insensitive name/section filter")
    jlink.add_argument("--limit", type=int, default=0, help="maximum variables to print/read, 0 means all")
    jlink.add_argument("--format", choices=("table", "csv", "json"), default="table", help="output format")
    jlink.add_argument("--output", type=Path, help="write output to a file instead of stdout")
    _add_serial_commands(subparsers)
    return parser


def _add_common_serial_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", "-p", default="", help="serial port, for example COM6; omit with 'serial ports'")
    parser.add_argument("--baud", "-b", type=int, default=921600, help="baudrate")
    parser.add_argument("--timeout", "-t", type=float, default=1.5, help="response timeout in seconds")
    parser.add_argument("--dst", type=lambda value: int(value, 0), default=2, help="protocol target address")
    parser.add_argument("--d-dst", type=lambda value: int(value, 0), default=0, help="protocol dynamic target address")
    parser.add_argument("--format", choices=("table", "csv", "json"), default="table", help="output format")
    parser.add_argument("--output", type=Path, help="write output to a file")


def _add_serial_commands(subparsers) -> None:
    serial_parser = subparsers.add_parser("serial", help="raw serial utilities")
    serial_sub = serial_parser.add_subparsers(dest="serial_cmd", required=True)
    serial_sub.add_parser("ports", help="list serial ports")
    raw = serial_sub.add_parser("raw", help="send raw bytes/text and read the response")
    _add_common_serial_options(raw)
    raw.add_argument("--send-hex", default="", help="hex bytes to send, e.g. '01 02 03'")
    raw.add_argument("--send-text", default="", help="text to send")
    raw.add_argument("--read-seconds", type=float, default=1.0, help="read duration")
    raw.add_argument("--rx-hex", action="store_true", help="print received bytes as hex")

    proto = subparsers.add_parser("proto", help="send a custom protocol frame")
    _add_common_serial_options(proto)
    proto.add_argument("--cmd-set", required=True, type=lambda value: int(value, 0))
    proto.add_argument("--cmd-word", required=True, type=lambda value: int(value, 0))
    proto.add_argument("--payload", default="", help="payload hex bytes")

    param = subparsers.add_parser("param", help="parameter page commands")
    param_sub = param.add_subparsers(dest="param_cmd", required=True)
    param_list_parser = param_sub.add_parser("list", help="read parameter list")
    _add_common_serial_options(param_list_parser)
    param_read_parser = param_sub.add_parser("read", help="read one parameter")
    _add_common_serial_options(param_read_parser)
    param_read_parser.add_argument("name")
    param_write_parser = param_sub.add_parser("write", help="write one parameter")
    _add_common_serial_options(param_write_parser)
    param_write_parser.add_argument("name")
    param_write_parser.add_argument("type_id", type=lambda value: int(value, 0))
    param_write_parser.add_argument("value")
    param_write_parser.add_argument("--min", dest="min_value")
    param_write_parser.add_argument("--max", dest="max_value")

    scope = subparsers.add_parser("scope", help="scope page commands")
    scope_sub = scope.add_subparsers(dest="scope_cmd", required=True)
    for name in ("list",):
        parser = scope_sub.add_parser(name, help=f"scope {name}")
        _add_common_serial_options(parser)
    parser = scope_sub.add_parser("info", help="read scope info")
    _add_common_serial_options(parser)
    parser.add_argument("scope_id", type=lambda value: int(value, 0))
    parser = scope_sub.add_parser("vars", help="read scope variable names")
    _add_common_serial_options(parser)
    parser.add_argument("scope_id", type=lambda value: int(value, 0))
    parser.add_argument("--count", type=int, default=0, help="variable count; 0 queries scope info first")
    for action in ("start", "trigger", "stop", "reset"):
        parser = scope_sub.add_parser(action, help=f"scope {action}")
        _add_common_serial_options(parser)
        parser.add_argument("scope_id", type=lambda value: int(value, 0))
    parser = scope_sub.add_parser("sample", help="read one scope sample")
    _add_common_serial_options(parser)
    parser.add_argument("scope_id", type=lambda value: int(value, 0))
    parser.add_argument("index", type=lambda value: int(value, 0))
    parser.add_argument("--tag", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--force", action="store_true")

    sfra = subparsers.add_parser("sfra", help="SFRA page commands")
    sfra_sub = sfra.add_subparsers(dest="sfra_cmd", required=True)
    parser = sfra_sub.add_parser("list", help="list SFRA loops")
    _add_common_serial_options(parser)
    parser = sfra_sub.add_parser("info", help="read SFRA info")
    _add_common_serial_options(parser)
    parser.add_argument("sfra_id", type=lambda value: int(value, 0))
    for action in ("start", "stop", "reset"):
        parser = sfra_sub.add_parser(action, help=f"SFRA {action}")
        _add_common_serial_options(parser)
        parser.add_argument("sfra_id", type=lambda value: int(value, 0))
    parser = sfra_sub.add_parser("config", help="set SFRA range/amplitude")
    _add_common_serial_options(parser)
    parser.add_argument("sfra_id", type=lambda value: int(value, 0))
    parser.add_argument("--start-hz", type=float)
    parser.add_argument("--stop-hz", type=float)
    parser.add_argument("--amplitude", type=float)
    parser = sfra_sub.add_parser("point", help="read one SFRA point")
    _add_common_serial_options(parser)
    parser.add_argument("sfra_id", type=lambda value: int(value, 0))
    parser.add_argument("index", type=lambda value: int(value, 0))
    parser.add_argument("--tag", type=lambda value: int(value, 0), default=0)

    perf = subparsers.add_parser("perf", help="performance page commands")
    perf_sub = perf.add_subparsers(dest="perf_cmd", required=True)
    for name in ("info", "summary", "reset-peak"):
        parser = perf_sub.add_parser(name, help=f"perf {name}")
        _add_common_serial_options(parser)
    for name in ("dict", "sample"):
        parser = perf_sub.add_parser(name, help=f"perf {name}")
        _add_common_serial_options(parser)
        parser.add_argument("--filter", default="all", help="all/task/interrupt/code")

    trace = subparsers.add_parser("trace", help="trace page commands")
    trace_sub = trace.add_subparsers(dest="trace_cmd", required=True)
    for name, enable in (("start", True), ("stop", False)):
        parser = trace_sub.add_parser(name, help=f"trace {name}")
        _add_common_serial_options(parser)
        parser.add_argument("--listen", type=float, default=0.5 if enable else 0.0, help="listen seconds after command")

    blackbox = subparsers.add_parser("blackbox", help="black box page commands")
    blackbox_sub = blackbox.add_subparsers(dest="blackbox_cmd", required=True)
    parser = blackbox_sub.add_parser("read", help="read black box range")
    _add_common_serial_options(parser)
    parser.add_argument("--start", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--length", type=lambda value: int(value, 0), required=True)


def _run_jlink_command(args: argparse.Namespace) -> int:
    service = JLinkVariableService()
    try:
        jlink_args = _jlink_args_with_saved_config(args)
        if jlink_args.elf is None and jlink_args.map_path is None:
            raise JLinkDebugError("Please provide --elf and/or --map, or load symbol files once in the GUI so FRAME can reuse the saved J-Link config.")
        variables = service.load_variables(elf_path=jlink_args.elf, map_path=jlink_args.map_path)
        variables = _filter_variables(variables, query=args.filter, limit=args.limit)
        if not args.no_read:
            settings = JLinkSettings(
                executable=jlink_args.jlink,
                device=jlink_args.device,
                interface=jlink_args.interface,
                speed_khz=jlink_args.speed,
            )
            variables = service.read_variables(variables, settings)
    except (OSError, JLinkDebugError, ValueError) as exc:
        print(f"frame jlink: {exc}", file=sys.stderr)
        return 1

    output_text = _format_variables(variables, output_format=args.format)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8", newline="")
    else:
        print(output_text)
    return 0


def _jlink_args_with_saved_config(args: argparse.Namespace) -> argparse.Namespace:
    config = load_config_section(get_app_paths().app_config_file, "ui_settings")
    values = config.get("values")
    ui_values = values if isinstance(values, dict) else {}
    jlink_config = load_config_section(get_app_paths().app_config_file, "jlink")
    files = jlink_config.get("files")
    file_values = files if isinstance(files, dict) else {}

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

    elf = args.elf or _path_from_config(config_text("jlink.elf_path", "elf_path"))
    map_path = args.map_path or _path_from_config(config_text("jlink.map_path", "map_path"))
    device = args.device.strip() or config_text("jlink.target_device")
    interface = args.interface or config_text("jlink.interface") or "SWD"
    speed = args.speed if args.speed is not None else config_int("jlink.speed_khz", 4000)
    return argparse.Namespace(
        elf=elf,
        map_path=map_path,
        jlink=args.jlink,
        device=device,
        interface=interface,
        speed=speed,
    )


def _path_from_config(value: str) -> Path | None:
    return Path(value) if value else None


def _run_serial_protocol_command(args: argparse.Namespace) -> int:
    try:
        result: object
        if args.command == "serial" and args.serial_cmd == "ports":
            result = list_serial_ports()
            write_or_print(format_output(result, output_format="table"), None)
            return 0

        options = _serial_options_from_args(args)
        if args.command == "serial" and args.serial_cmd == "raw":
            text = raw_serial(
                options,
                send_hex=args.send_hex,
                send_text=args.send_text,
                read_seconds=args.read_seconds,
                receive_hex=args.rx_hex,
            )
            write_or_print(text, args.output)
            return 0

        if args.command == "proto":
            result = protocol_request(options, cmd_set=args.cmd_set, cmd_word=args.cmd_word, payload_hex=args.payload)
        elif args.command == "param":
            result = _run_param_command(args, options)
        elif args.command == "scope":
            result = _run_scope_command(args, options)
        elif args.command == "sfra":
            result = _run_sfra_command(args, options)
        elif args.command == "perf":
            result = _run_perf_command(args, options)
        elif args.command == "trace":
            result = trace_control(options, enable=args.trace_cmd == "start", listen_seconds=args.listen)
        elif args.command == "blackbox":
            result = black_box_read(options, start_offset=args.start, length=args.length)
        else:
            raise SerialCliError(f"unsupported command: {args.command}")
        write_or_print(format_output(result, output_format=args.format), args.output)
        return 0
    except (OSError, serial.SerialException, SerialCliError, ValueError) as exc:
        print(f"frame {args.command}: {exc}", file=sys.stderr)
        return 1


def _serial_options_from_args(args: argparse.Namespace) -> SerialOptions:
    port = str(getattr(args, "port", "")).strip()
    if not port:
        raise SerialCliError("serial port is required; run 'frame serial ports' first")
    return SerialOptions(
        port=port,
        baudrate=int(args.baud),
        timeout=float(args.timeout),
        dst=int(args.dst),
        d_dst=int(args.d_dst),
    )


def _run_param_command(args: argparse.Namespace, options: SerialOptions) -> object:
    if args.param_cmd == "list":
        return param_list(options)
    if args.param_cmd == "read":
        return param_read(options, name=args.name)
    if args.param_cmd == "write":
        return param_write(options, name=args.name, type_id=args.type_id, value=args.value, min_value=args.min_value, max_value=args.max_value)
    raise SerialCliError(f"unsupported param command: {args.param_cmd}")


def _run_scope_command(args: argparse.Namespace, options: SerialOptions) -> object:
    if args.scope_cmd == "list":
        return scope_list(options)
    if args.scope_cmd == "info":
        return scope_info(options, scope_id=args.scope_id)
    if args.scope_cmd == "vars":
        count = args.count
        if count <= 0:
            info = scope_info(options, scope_id=args.scope_id)
            count = int(info["var_count"])
        return scope_vars(options, scope_id=args.scope_id, count=count)
    if args.scope_cmd in {"start", "trigger", "stop", "reset"}:
        return scope_control(options, scope_id=args.scope_id, action=args.scope_cmd)
    if args.scope_cmd == "sample":
        return scope_sample(options, scope_id=args.scope_id, index=args.index, tag=args.tag, force=args.force)
    raise SerialCliError(f"unsupported scope command: {args.scope_cmd}")


def _run_sfra_command(args: argparse.Namespace, options: SerialOptions) -> object:
    if args.sfra_cmd == "list":
        return sfra_list(options)
    if args.sfra_cmd == "info":
        return sfra_info(options, sfra_id=args.sfra_id)
    if args.sfra_cmd in {"start", "stop", "reset"}:
        return sfra_control(options, sfra_id=args.sfra_id, action=args.sfra_cmd)
    if args.sfra_cmd == "config":
        return sfra_config(
            options,
            sfra_id=args.sfra_id,
            start_hz=args.start_hz,
            stop_hz=args.stop_hz,
            amplitude=args.amplitude,
        )
    if args.sfra_cmd == "point":
        return sfra_point(options, sfra_id=args.sfra_id, index=args.index, tag=args.tag)
    raise SerialCliError(f"unsupported sfra command: {args.sfra_cmd}")


def _run_perf_command(args: argparse.Namespace, options: SerialOptions) -> object:
    if args.perf_cmd == "info":
        return perf_info(options)
    if args.perf_cmd == "summary":
        return perf_summary(options)
    if args.perf_cmd == "dict":
        return perf_dict(options, type_filter=parse_perf_filter(args.filter))
    if args.perf_cmd == "sample":
        return perf_sample(options, type_filter=parse_perf_filter(args.filter))
    if args.perf_cmd == "reset-peak":
        return perf_reset_peak(options)
    raise SerialCliError(f"unsupported perf command: {args.perf_cmd}")


def _filter_variables(variables: list[DebugVariable], *, query: str, limit: int) -> list[DebugVariable]:
    query = query.strip().lower()
    if query:
        variables = [item for item in variables if query in item.name.lower() or query in item.section.lower()]
    if limit > 0:
        variables = variables[:limit]
    return variables


def _format_variables(variables: list[DebugVariable], *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps([_variable_to_dict(item) for item in variables], ensure_ascii=False, indent=2)
    if output_format == "csv":
        return _format_csv(variables)
    return _format_table(variables)


def _format_csv(variables: list[DebugVariable]) -> str:
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=("name", "address", "size", "type", "section", "value", "raw_hex", "status", "source"))
    writer.writeheader()
    for variable in variables:
        row = _variable_to_dict(variable)
        row["address"] = f"0x{variable.address:08X}"
        writer.writerow(row)
    return buffer.getvalue()


def _format_table(variables: list[DebugVariable]) -> str:
    headers = ("Name", "Address", "Size", "Type", "Section", "Value", "Raw", "Status")
    rows = [
        (
            item.name,
            f"0x{item.address:08X}",
            str(item.size),
            item.type_name,
            item.section,
            item.value,
            item.raw_hex,
            item.status,
        )
        for item in variables
    ]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = min(max(widths[index], len(cell)), 48)

    def trim(cell: str, width: int) -> str:
        if len(cell) <= width:
            return cell
        return cell[: max(width - 3, 1)] + "..."

    lines = []
    lines.append("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(trim(cell, widths[index]).ljust(widths[index]) for index, cell in enumerate(row)))
    lines.append(f"{len(rows)} variable(s)")
    return "\n".join(lines)


def _variable_to_dict(variable: DebugVariable) -> dict[str, object]:
    return {
        "name": variable.name,
        "address": variable.address,
        "size": variable.size,
        "type": variable.type_name,
        "section": variable.section,
        "value": variable.value,
        "raw_hex": variable.raw_hex,
        "status": variable.status,
        "source": variable.source,
    }


if __name__ == "__main__":
    raise SystemExit(main())
