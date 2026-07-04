from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile


MAX_VARIABLE_READ_BYTES = 16
MAX_DWARF_ARRAY_EXPAND_COUNT = 4096
MAX_DWARF_EXPANDED_FIELDS_PER_VARIABLE = 4096
RAM_WRITE_RANGES = ((0x20000000, 0x40000000),)
JLINK_POINTER_EXPAND_RANGES = ((0x00000000, 0x20000000), (0x20000000, 0x40000000))
OBJECT_SYMBOL_TYPE = 1
FUNCTION_SYMBOL_TYPE = 2
SHT_SYMTAB = 2
SHT_DYNSYM = 11
SHF_ALLOC = 0x02
DEVICE_TEXT_SCAN_BYTES = 2 * 1024 * 1024
DEVICE_TOKEN_RE = re.compile(
    r"(?<![A-Z0-9])("
    r"GD32[A-Z0-9]{4,}|"
    r"HC32[A-Z0-9]{4,}|"
    r"STM32[A-Z0-9]{4,}|"
    r"AT32[A-Z0-9]{4,}|"
    r"MM32[A-Z0-9]{4,}|"
    r"N32[A-Z0-9]{4,}|"
    r"CH32[A-Z0-9]{4,}|"
    r"APM32[A-Z0-9]{4,}|"
    r"PY32[A-Z0-9]{4,}|"
    r"CW32[A-Z0-9]{4,}|"
    r"HK32[A-Z0-9]{4,}|"
    r"LPC[A-Z0-9]{4,}|"
    r"MSPM0[A-Z0-9]{3,}|"
    r"EFM32[A-Z0-9]{4,}|"
    r"EFR32[A-Z0-9]{4,}|"
    r"NRF[A-Z0-9]{4,}|"
    r"RP2040"
    r")(?![A-Z0-9])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DebugVariable:
    name: str
    address: int
    size: int
    section: str
    source: str
    type_name: str = ""
    parent_types: tuple[tuple[str, str], ...] = ()
    child_templates: tuple["DebugVariable", ...] = ()
    pointer_value: int | None = None
    raw_hex: str = ""
    value: str = ""
    status: str = "未读取"


@dataclass(frozen=True)
class JLinkSettings:
    executable: str
    device: str
    interface: str
    speed_khz: int


@dataclass(frozen=True)
class JLinkMemoryRange:
    name: str
    start: int
    end: int

    def contains(self, address: int) -> bool:
        return self.start <= address < self.end


@dataclass(frozen=True)
class SourceLocation:
    address: int
    symbol: str
    file: Path
    line: int
    column: int = 0


class JLinkDebugError(RuntimeError):
    pass


class JLinkVariableService:
    def __init__(self) -> None:
        self.symbol_names: dict[int, str] = {}
        self.function_names: dict[int, str] = {}
        self.function_locations: dict[str, SourceLocation] = {}
        self.memory_ranges: list[JLinkMemoryRange] = []
        self.type_templates: dict[str, tuple[DebugVariable, ...]] = {}

    def load_variables(self, *, elf_path: Path | None, map_path: Path | None) -> list[DebugVariable]:
        elf_variables: list[DebugVariable] = []
        map_variables: list[DebugVariable] = []
        type_templates: dict[str, tuple[DebugVariable, ...]] = {}
        self.symbol_names = {}
        self.function_names = {}
        self.function_locations = {}
        self.memory_ranges = []
        self.type_templates = {}
        if elf_path is not None:
            elf_variables.extend(_load_elf_variables(elf_path))
            self.symbol_names.update(_load_elf_symbol_names(elf_path))
            self.function_names.update(_load_elf_function_names(elf_path))
            self.function_names.update(_load_dwarf_function_names(elf_path))
            self.function_locations.update(_load_dwarf_function_locations(elf_path, self.symbol_names))
            self.memory_ranges.extend(_load_elf_memory_ranges(elf_path))
            type_templates = _load_dwarf_type_templates(elf_path)
        if map_path is not None:
            map_variables.extend(_load_map_variables(map_path))
            if elf_path is not None:
                map_variables = _apply_map_type_templates(map_variables, type_templates)
            _merge_symbol_names(self.symbol_names, _symbol_names_from_variables(map_variables))
            self.memory_ranges.extend(_load_map_memory_ranges(map_path))
        variables = _merge_symbol_sources(elf_variables, map_variables)
        _merge_symbol_names(self.symbol_names, _symbol_names_from_variables(variables))
        self.memory_ranges = _deduplicate_memory_ranges(self.memory_ranges)
        self.type_templates = dict(type_templates)
        if not variables:
            raise JLinkDebugError("No variable symbols were parsed from ELF/MAP. Check that the ELF has symbols or provide a GNU ld MAP file.")
        return _deduplicate_variables(variables)

    def read_variables(self, variables: list[DebugVariable], settings: JLinkSettings) -> list[DebugVariable]:
        if not variables:
            return []
        executable = _resolve_jlink_executable(settings.executable)
        if executable is None:
            raise JLinkDebugError("未找到 J-Link 命令行工具。请填写 JLink.exe/JLinkExe.exe 路径，或把它加入 PATH。")
        if not settings.device.strip():
            raise JLinkDebugError("请填写 J-Link Device，例如 HC32F334K8TA、STM32F407VE。")

        read_ranges = _build_read_ranges(variables)
        output = _run_jlink_read(
            executable=executable,
            device=settings.device.strip(),
            interface=settings.interface.strip() or "SWD",
            speed_khz=settings.speed_khz,
            read_ranges=read_ranges,
        )
        memory = _parse_jlink_mem32_output(output)
        string_ranges = _build_string_read_ranges(variables, memory)
        string_memory: dict[int, int] = {}
        if string_ranges:
            string_output = _run_jlink_read(
                executable=executable,
                device=settings.device.strip(),
                interface=settings.interface.strip() or "SWD",
                speed_khz=settings.speed_khz,
                read_ranges=string_ranges,
            )
            string_memory = _parse_jlink_mem32_output(string_output)
        return [_with_memory_value(variable, memory, symbol_names=self.symbol_names, string_memory=string_memory) for variable in variables]

    def write_variable(self, variable: DebugVariable, value_text: str, settings: JLinkSettings) -> DebugVariable:
        executable = _resolve_jlink_executable(settings.executable)
        if executable is None:
            raise JLinkDebugError("未找到 J-Link 命令行工具。请填写 JLink.exe/JLinkExe.exe 路径，或把它加入 PATH。")
        if not settings.device.strip():
            raise JLinkDebugError("请填写 J-Link Device，例如 HC32F334K8TA、STM32F407VE。")
        payload = _encode_write_value(variable, value_text)
        _validate_ram_write(variable.address, len(payload))
        _run_jlink_write(
            executable=executable,
            device=settings.device.strip(),
            interface=settings.interface.strip() or "SWD",
            speed_khz=settings.speed_khz,
            address=variable.address,
            payload=payload,
        )
        return self.read_variables([variable], settings)[0]

    def test_connection(self, settings: JLinkSettings) -> str:
        executable = _resolve_jlink_executable(settings.executable)
        if executable is None:
            raise JLinkDebugError("J-Link command line tool was not found. Install SEGGER J-Link or add JLink.exe/JLinkExe.exe to PATH.")
        device = settings.device.strip()
        if not device:
            raise JLinkDebugError("J-Link Device is required, for example GD32G553RCT6.")
        output = _run_jlink_read(
            executable=executable,
            device=device,
            interface=settings.interface.strip() or "SWD",
            speed_khz=settings.speed_khz,
            read_ranges={},
        )
        return f"Connected with {Path(executable).name} ({device})\n{_tail_output(output, max_lines=8)}"

    def select_device_with_native_dialog(self, settings: JLinkSettings) -> tuple[str, str]:
        executable = _resolve_jlink_executable(settings.executable)
        if executable is None:
            raise JLinkDebugError("J-Link command line tool was not found. Install SEGGER J-Link or add JLink.exe/JLinkExe.exe to PATH.")
        output = _run_jlink_script(
            executable=executable,
            script_lines=[
                "device ?",
                f"if {settings.interface.strip() or 'SWD'}",
                f"speed {max(settings.speed_khz, 1)}",
                "connect",
                "exit",
            ],
            timeout=300,
        )
        device = infer_jlink_device_from_text(output)
        if not device:
            raise JLinkDebugError(
                "J-Link target selection finished, but FRAME could not parse the selected device name. "
                "Please type the target once, then it will be saved in the history list."
            )
        return device, f"Connected with {Path(executable).name} ({device})\n{_tail_output(output, max_lines=8)}"


def infer_jlink_device(*, elf_path: Path | None, map_path: Path | None) -> str:
    candidates: list[str] = []
    for path in (elf_path, map_path):
        if path is None:
            continue
        candidates.extend(_device_candidates_from_text(path.name))
        try:
            data = path.read_bytes()
        except OSError:
            continue
        candidates.extend(_device_candidates_from_bytes(data[:DEVICE_TEXT_SCAN_BYTES]))
    return _choose_device_candidate(candidates)


def jlink_type_template_key(type_name: str) -> str:
    return _normalized_type_key(type_name)


def jlink_symbol_name_for_address(address: int, symbol_names: dict[int, str]) -> str:
    return _symbol_name_for_address(address, symbol_names)


def resolve_elf_source_location(path: Path, address: int, symbol_names: dict[int, str] | None = None) -> SourceLocation:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError as exc:
        raise JLinkDebugError("pyelftools is required to resolve ELF source locations.") from exc

    query_address = address & ~1
    best: SourceLocation | None = None
    best_delta: int | None = None
    try:
        with path.open("rb") as handle:
            elf = ELFFile(handle)
            if not elf.has_dwarf_info():
                raise JLinkDebugError(f"{path} does not contain DWARF debug information.")
            dwarf = elf.get_dwarf_info()
            for cu in dwarf.iter_CUs():
                line_program = dwarf.line_program_for_CU(cu)
                if line_program is None:
                    continue
                previous_state = None
                for entry in line_program.get_entries():
                    state = entry.state
                    if state is None:
                        continue
                    if state.end_sequence:
                        previous_state = None
                        continue
                    if previous_state is not None and previous_state.address <= query_address < state.address:
                        candidate_address = previous_state.address
                        delta = query_address - candidate_address
                        if best_delta is None or delta < best_delta:
                            best = _source_location_from_line_state(
                                cu=cu,
                                line_program=line_program,
                                state=previous_state,
                                query_address=query_address,
                                symbol_names=symbol_names or {},
                            )
                            best_delta = delta
                    if state.address == query_address:
                        best = _source_location_from_line_state(
                            cu=cu,
                            line_program=line_program,
                            state=state,
                            query_address=query_address,
                            symbol_names=symbol_names or {},
                        )
                        best_delta = 0
                    previous_state = state
    except JLinkDebugError:
        raise
    except Exception as exc:
        raise JLinkDebugError(f"Failed to resolve ELF source location: {exc}") from exc
    if best is None:
        raise JLinkDebugError(f"No DWARF source line found for address 0x{address:08X}.")
    return best


def resolve_elf_function_source_location(path: Path, function_name: str, symbol_names: dict[int, str] | None = None) -> SourceLocation:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError as exc:
        raise JLinkDebugError("pyelftools is required to resolve ELF source locations.") from exc

    try:
        with path.open("rb") as handle:
            elf = ELFFile(handle)
            if not elf.has_dwarf_info():
                raise JLinkDebugError(f"{path} does not contain DWARF debug information.")
            dwarf = elf.get_dwarf_info()
            for cu in dwarf.iter_CUs():
                line_program = dwarf.line_program_for_CU(cu)
                if line_program is None:
                    continue
                for die in cu.iter_DIEs():
                    if die.tag != "DW_TAG_subprogram":
                        continue
                    name = _dwarf_die_name(die)
                    linkage_name = _dwarf_linkage_name(die)
                    if function_name not in {name, linkage_name}:
                        continue
                    decl_file_attr = die.attributes.get("DW_AT_decl_file")
                    decl_line_attr = die.attributes.get("DW_AT_decl_line")
                    if decl_file_attr is None or decl_line_attr is None:
                        continue
                    address = _dwarf_low_pc(die)
                    if address is None:
                        address = _symbol_address_by_name(function_name, symbol_names or {})
                    if address is None:
                        address = 0
                    return SourceLocation(
                        address=address,
                        symbol=function_name,
                        file=_line_state_file_path(cu, line_program, int(decl_file_attr.value)),
                        line=int(decl_line_attr.value),
                    )
    except JLinkDebugError:
        raise
    except Exception as exc:
        raise JLinkDebugError(f"Failed to resolve ELF function source: {exc}") from exc
    raise JLinkDebugError(f"No DWARF function source found for: {function_name}")


def infer_jlink_device_from_text(text: str) -> str:
    for pattern in (
        r"Device\s+\"?([A-Za-z0-9_+\-/.]+)\"?\s+selected",
        r"device\s*=\s*\"?([A-Za-z0-9_+\-/.]+)\"?",
        r"Device\s+\"?([A-Za-z0-9_+\-/.]+)\"?",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _normalize_device_candidate(match.group(1))
    return _choose_device_candidate(_device_candidates_from_text(text))


def _load_elf_variables(path: Path) -> list[DebugVariable]:
    dwarf_variables = _load_dwarf_variables(path)
    if dwarf_variables:
        return dwarf_variables

    data = path.read_bytes()
    if len(data) < 16 or data[:4] != b"\x7fELF":
        raise JLinkDebugError(f"{path} 不是有效 ELF 文件。")

    is_64_bit = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    sections = _read_elf_sections(data, is_64_bit=is_64_bit, endian=endian)
    names = _read_section_names(data, sections)
    variables: list[DebugVariable] = []

    for index, section in enumerate(sections):
        if section["type"] not in (SHT_SYMTAB, SHT_DYNSYM):
            continue
        strtab_index = section["link"]
        if strtab_index >= len(sections):
            continue
        strtab = _section_bytes(data, sections[strtab_index])
        symbol_bytes = _section_bytes(data, section)
        entry_size = section["entsize"] or (24 if is_64_bit else 16)
        for offset in range(0, len(symbol_bytes), entry_size):
            entry = symbol_bytes[offset : offset + entry_size]
            if len(entry) < entry_size:
                continue
            name_offset, info, value, size, shndx = _read_elf_symbol(entry, is_64_bit=is_64_bit, endian=endian)
            if (info & 0x0F) != OBJECT_SYMBOL_TYPE or shndx == 0 or size <= 0:
                continue
            name = _read_c_string(strtab, name_offset)
            if not _is_variable_name(name):
                continue
            section_name = names[shndx] if shndx < len(names) else ""
            if _is_debug_or_metadata_section(section_name):
                continue
            variables.append(
                DebugVariable(
                    name=name,
                    address=value,
                    size=size,
                    section=section_name,
                    source=path.name,
                    type_name="",
                )
            )

    return variables


def _load_elf_symbol_names(path: Path) -> dict[int, str]:
    data = path.read_bytes()
    if len(data) < 16 or data[:4] != b"\x7fELF":
        return {}

    is_64_bit = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    sections = _read_elf_sections(data, is_64_bit=is_64_bit, endian=endian)
    names = _read_section_names(data, sections)
    symbols: dict[int, str] = {}
    for section in sections:
        if section["type"] not in (SHT_SYMTAB, SHT_DYNSYM):
            continue
        strtab_index = section["link"]
        if strtab_index >= len(sections):
            continue
        strtab = _section_bytes(data, sections[strtab_index])
        symbol_bytes = _section_bytes(data, section)
        entry_size = section["entsize"] or (24 if is_64_bit else 16)
        for offset in range(0, len(symbol_bytes), entry_size):
            entry = symbol_bytes[offset : offset + entry_size]
            if len(entry) < entry_size:
                continue
            name_offset, info, value, size, shndx = _read_elf_symbol(entry, is_64_bit=is_64_bit, endian=endian)
            symbol_type = info & 0x0F
            if symbol_type not in (OBJECT_SYMBOL_TYPE, FUNCTION_SYMBOL_TYPE) or shndx == 0 or value == 0:
                continue
            name = _read_c_string(strtab, name_offset)
            if not _is_variable_name(name):
                continue
            section_name = names[shndx] if shndx < len(names) else ""
            if _is_debug_or_metadata_section(section_name):
                continue
            if not _looks_like_mcu_address(value):
                continue
            symbols.setdefault(value, name)
    return symbols


def _load_elf_function_names(path: Path) -> dict[int, str]:
    data = path.read_bytes()
    if len(data) < 16 or data[:4] != b"\x7fELF":
        return {}

    is_64_bit = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    sections = _read_elf_sections(data, is_64_bit=is_64_bit, endian=endian)
    names = _read_section_names(data, sections)
    functions: dict[int, str] = {}
    for section in sections:
        if section["type"] not in (SHT_SYMTAB, SHT_DYNSYM):
            continue
        strtab_index = section["link"]
        if strtab_index >= len(sections):
            continue
        strtab = _section_bytes(data, sections[strtab_index])
        symbol_bytes = _section_bytes(data, section)
        entry_size = section["entsize"] or (24 if is_64_bit else 16)
        for offset in range(0, len(symbol_bytes), entry_size):
            entry = symbol_bytes[offset : offset + entry_size]
            if len(entry) < entry_size:
                continue
            name_offset, info, value, size, shndx = _read_elf_symbol(entry, is_64_bit=is_64_bit, endian=endian)
            if (info & 0x0F) != FUNCTION_SYMBOL_TYPE or shndx == 0 or value == 0:
                continue
            name = _read_c_string(strtab, name_offset)
            if not _is_variable_name(name):
                continue
            section_name = names[shndx] if shndx < len(names) else ""
            if _is_debug_or_metadata_section(section_name):
                continue
            if not _looks_like_mcu_address(value):
                continue
            functions.setdefault(value, name)
    return functions


def _load_dwarf_function_names(path: Path) -> dict[int, str]:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return {}

    functions: dict[int, str] = {}
    try:
        with path.open("rb") as handle:
            elf = ELFFile(handle)
            if not elf.has_dwarf_info():
                return {}
            dwarf = elf.get_dwarf_info()
            for cu in dwarf.iter_CUs():
                for die in cu.iter_DIEs():
                    if die.tag != "DW_TAG_subprogram":
                        continue
                    name = _dwarf_die_name(die)
                    if not _is_variable_name(name):
                        continue
                    address = _dwarf_low_pc(die)
                    if address is None or not _looks_like_mcu_address(address):
                        continue
                    functions.setdefault(address, name)
    except Exception:
        return {}
    return functions


def _load_dwarf_function_locations(path: Path, symbol_names: dict[int, str]) -> dict[str, SourceLocation]:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return {}

    locations: dict[str, SourceLocation] = {}
    try:
        with path.open("rb") as handle:
            elf = ELFFile(handle)
            if not elf.has_dwarf_info():
                return {}
            dwarf = elf.get_dwarf_info()
            for cu in dwarf.iter_CUs():
                line_program = dwarf.line_program_for_CU(cu)
                if line_program is None:
                    continue
                for die in cu.iter_DIEs():
                    if die.tag != "DW_TAG_subprogram":
                        continue
                    name = _dwarf_die_name(die)
                    if not _is_variable_name(name):
                        continue
                    decl_file_attr = die.attributes.get("DW_AT_decl_file")
                    decl_line_attr = die.attributes.get("DW_AT_decl_line")
                    if decl_file_attr is None or decl_line_attr is None:
                        continue
                    address = _dwarf_low_pc(die)
                    if address is None:
                        address = _symbol_address_by_name(name, symbol_names) or 0
                    locations.setdefault(
                        name,
                        SourceLocation(
                            address=address,
                            symbol=name,
                            file=_line_state_file_path(cu, line_program, int(decl_file_attr.value)),
                            line=int(decl_line_attr.value),
                        ),
                    )
    except Exception:
        return {}
    return locations


def _load_elf_memory_ranges(path: Path) -> list[JLinkMemoryRange]:
    data = path.read_bytes()
    if len(data) < 16 or data[:4] != b"\x7fELF":
        return []
    is_64_bit = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    sections = _read_elf_sections(data, is_64_bit=is_64_bit, endian=endian)
    names = _read_section_names(data, sections)
    ranges: list[JLinkMemoryRange] = []
    for index, section in enumerate(sections):
        address = section.get("addr", 0)
        size = section.get("size", 0)
        flags = section.get("flags", 0)
        name = names[index] if index < len(names) else ""
        if not address or not size or not (flags & SHF_ALLOC) or _is_debug_or_metadata_section(name):
            continue
        ranges.append(JLinkMemoryRange(name=name or f"section_{index}", start=address, end=address + size))
    return _deduplicate_memory_ranges(ranges)


def _load_map_memory_ranges(path: Path) -> list[JLinkMemoryRange]:
    return _parse_map_memory_ranges(path.read_text(encoding="utf-8", errors="ignore"))


def _parse_map_memory_ranges(text: str) -> list[JLinkMemoryRange]:
    ranges: list[JLinkMemoryRange] = []
    in_memory_config = False
    line_re = re.compile(r"^\s*(\S+)\s+0x([0-9A-Fa-f]+)\s+0x([0-9A-Fa-f]+)(?:\s+\S+)?\s*$")
    for line in text.splitlines():
        if line.strip() == "Memory Configuration":
            in_memory_config = True
            continue
        if not in_memory_config:
            continue
        if not line.strip():
            if ranges:
                break
            continue
        match = line_re.match(line)
        if match is None:
            continue
        name = match.group(1)
        if name == "*default*":
            continue
        start = int(match.group(2), 16)
        length = int(match.group(3), 16)
        if length <= 0:
            continue
        ranges.append(JLinkMemoryRange(name=name, start=start, end=start + length))
    return _deduplicate_memory_ranges(ranges)


def _symbol_names_from_variables(variables: list[DebugVariable]) -> dict[int, str]:
    symbols: dict[int, str] = {}
    parent_addresses: dict[str, int] = {}
    for variable in variables:
        for expression, _type_name in variable.parent_types:
            if not expression or not _looks_like_mcu_address(variable.address):
                continue
            previous = parent_addresses.get(expression)
            if previous is None or variable.address < previous:
                parent_addresses[expression] = variable.address
    for expression, address in sorted(parent_addresses.items(), key=lambda item: (item[1], item[0].lower())):
        symbols.setdefault(address, expression)
    for variable in variables:
        if _looks_like_mcu_address(variable.address):
            symbols.setdefault(variable.address, variable.name)
    return symbols


def _merge_symbol_names(target: dict[int, str], source: dict[int, str]) -> None:
    for address, name in source.items():
        target.setdefault(address, name)


def _deduplicate_memory_ranges(ranges: list[JLinkMemoryRange]) -> list[JLinkMemoryRange]:
    by_key: dict[tuple[int, int, str], JLinkMemoryRange] = {}
    for item in ranges:
        if item.start < item.end:
            by_key[(item.start, item.end, item.name.lower())] = item
    return sorted(by_key.values(), key=lambda item: (item.start, item.end, item.name.lower()))


def _device_candidates_from_bytes(data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="ignore")
    if not text:
        text = data.decode("latin-1", errors="ignore")
    return _device_candidates_from_text(text)


def _device_candidates_from_text(text: str) -> list[str]:
    return [_normalize_device_candidate(match.group(1)) for match in DEVICE_TOKEN_RE.finditer(text)]


def _normalize_device_candidate(text: str) -> str:
    return text.strip().strip("_-.").upper()


def _choose_device_candidate(candidates: list[str]) -> str:
    counts: dict[str, int] = {}
    first_index: dict[str, int] = {}
    for candidate in candidates:
        if not candidate:
            continue
        first_index.setdefault(candidate, len(first_index))
        counts[candidate] = counts.get(candidate, 0) + 1
    if not counts:
        return ""
    return max(counts, key=lambda item: (counts[item], len(item), -first_index[item]))


def _load_dwarf_variables(path: Path) -> list[DebugVariable]:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return []

    try:
        with path.open("rb") as handle:
            elf = ELFFile(handle)
            if not elf.has_dwarf_info():
                return []
            dwarf = elf.get_dwarf_info()
            section_ranges = _elf_section_ranges(elf)
            variables: list[DebugVariable] = []
            for cu in dwarf.iter_CUs():
                for die in cu.iter_DIEs():
                    if die.tag != "DW_TAG_variable":
                        continue
                    name = _dwarf_die_name(die)
                    if not _is_variable_name(name):
                        continue
                    display_name = _dwarf_scoped_variable_name(die, name)
                    address = _dwarf_location_address(die)
                    if address is None or not _looks_like_mcu_address(address):
                        continue
                    section = _section_name_for_address(address, section_ranges)
                    if _is_debug_or_metadata_section(section):
                        continue
                    type_die = _dwarf_type_die(die)
                    expanded = _expand_dwarf_type(
                        type_die,
                        base_name=display_name,
                        base_address=address,
                        section=section,
                        source=path.name,
                        depth=0,
                        field_budget=MAX_DWARF_EXPANDED_FIELDS_PER_VARIABLE,
                        parent_types=(),
                    )
                    if expanded:
                        variables.extend(expanded)
                    else:
                        size = _dwarf_type_size(type_die) or 1
                        variables.append(
                            DebugVariable(
                                name=display_name,
                                address=address,
                                size=size,
                                section=section,
                                source=path.name,
                                type_name=_dwarf_type_name(type_die),
                            )
                        )
            return _deduplicate_variables(variables)
    except Exception:
        return []


def _load_dwarf_type_templates(path: Path) -> dict[str, tuple[DebugVariable, ...]]:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return {}

    templates: dict[str, tuple[DebugVariable, ...]] = {}
    try:
        with path.open("rb") as handle:
            elf = ELFFile(handle)
            if not elf.has_dwarf_info():
                return {}
            dwarf = elf.get_dwarf_info()
            for cu in dwarf.iter_CUs():
                for die in cu.iter_DIEs():
                    if die.tag not in {"DW_TAG_typedef", "DW_TAG_structure_type", "DW_TAG_union_type"}:
                        continue
                    type_name = _dwarf_type_name(die)
                    if not type_name:
                        continue
                    child_templates = _dwarf_pointee_templates(die)
                    if child_templates:
                        templates.setdefault(_normalized_type_key(type_name), child_templates)
    except Exception:
        return {}
    return templates


def _source_location_from_line_state(cu, line_program, state, query_address: int, symbol_names: dict[int, str]) -> SourceLocation:
    file_path = _line_state_file_path(cu, line_program, state.file)
    return SourceLocation(
        address=query_address,
        symbol=_symbol_name_for_address(query_address, symbol_names),
        file=file_path,
        line=int(state.line or 0),
        column=int(state.column or 0),
    )


def _line_state_file_path(cu, line_program, file_index: int) -> Path:
    files = line_program["file_entry"]
    if file_index <= 0 or file_index > len(files):
        return Path("")
    file_entry = files[file_index - 1]
    file_name = _dwarf_bytes_to_text(file_entry.name)
    file_path = Path(file_name)
    if file_path.is_absolute():
        return file_path

    comp_dir = _cu_comp_dir(cu)
    directory = _line_file_directory(line_program, int(file_entry.dir_index), comp_dir)
    if directory:
        return Path(directory) / file_name
    return Path(file_name)


def _line_file_directory(line_program, dir_index: int, comp_dir: str) -> str:
    if dir_index == 0:
        return comp_dir
    directories = line_program["include_directory"]
    if 0 < dir_index <= len(directories):
        directory = _dwarf_bytes_to_text(directories[dir_index - 1])
        path = Path(directory)
        if path.is_absolute() or not comp_dir:
            return directory
        return str(Path(comp_dir) / path)
    return comp_dir


def _cu_comp_dir(cu) -> str:
    top_die = cu.get_top_DIE()
    attr = top_die.attributes.get("DW_AT_comp_dir")
    if attr is None:
        return ""
    return _dwarf_bytes_to_text(attr.value)


def _dwarf_bytes_to_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _apply_map_type_templates(
    variables: list[DebugVariable],
    type_templates: dict[str, tuple[DebugVariable, ...]],
) -> list[DebugVariable]:
    if not type_templates:
        return variables
    enriched: list[DebugVariable] = []
    for variable in variables:
        if variable.type_name or variable.child_templates:
            enriched.append(variable)
            continue
        type_name = _infer_map_pointer_type_name(variable.name, type_templates)
        if not type_name:
            enriched.append(variable)
            continue
        enriched.append(replace(variable, size=4, type_name=f"{type_name} *", child_templates=type_templates[_normalized_type_key(type_name)]))
    return enriched


def _infer_map_pointer_type_name(name: str, type_templates: dict[str, tuple[DebugVariable, ...]]) -> str:
    for candidate in _map_pointer_type_candidates(name):
        key = _normalized_type_key(candidate)
        if key in type_templates:
            return candidate
    return ""


def _map_pointer_type_candidates(name: str) -> list[str]:
    base = name.strip()
    if not base:
        return []
    candidates: list[str] = []
    for prefix in ("g_", "p_", "s_"):
        if base.startswith(prefix):
            candidates.append(base[len(prefix) :])
    candidates.append(base)
    expanded: list[str] = []
    for item in candidates:
        expanded.append(item)
        for suffix in ("_first", "_head", "_tail", "_current", "_next"):
            if item.endswith(suffix):
                expanded.append(item[: -len(suffix)])
    result: list[str] = []
    for item in expanded:
        if not item:
            continue
        result.append(item)
        if not item.endswith("_t"):
            result.append(f"{item}_t")
    unique: list[str] = []
    for item in result:
        if item not in unique:
            unique.append(item)
    return unique


def _normalized_type_key(type_name: str) -> str:
    return " ".join(type_name.replace("const", "").replace("volatile", "").replace("*", " ").split()).strip().lower()


def _elf_section_ranges(elf) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    for section in elf.iter_sections():
        address = int(section["sh_addr"])
        size = int(section["sh_size"])
        if address and size:
            ranges.append((address, address + size, section.name))
    return ranges


def _section_name_for_address(address: int, ranges: list[tuple[int, int, str]]) -> str:
    for start, end, name in ranges:
        if start <= address < end:
            return name
    return ""


def _dwarf_die_name(die) -> str:
    attr = die.attributes.get("DW_AT_name")
    if attr is None:
        return ""
    value = attr.value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _dwarf_linkage_name(die) -> str:
    for attr_name in ("DW_AT_linkage_name", "DW_AT_MIPS_linkage_name"):
        attr = die.attributes.get(attr_name)
        if attr is None:
            continue
        return _dwarf_bytes_to_text(attr.value)
    return ""


def _dwarf_low_pc(die) -> int | None:
    attr = die.attributes.get("DW_AT_low_pc")
    if attr is None:
        return None
    try:
        return int(attr.value)
    except (TypeError, ValueError):
        return None


def _dwarf_scoped_variable_name(die, name: str) -> str:
    scope = _dwarf_subprogram_scope_name(die)
    return f"{scope}::{name}" if scope else name


def _dwarf_subprogram_scope_name(die) -> str:
    try:
        parent = die.get_parent()
    except Exception:
        return ""
    while parent is not None:
        if getattr(parent, "tag", "") == "DW_TAG_subprogram":
            return _dwarf_die_name(parent)
        try:
            parent = parent.get_parent()
        except Exception:
            return ""
    return ""


def _dwarf_location_address(die) -> int | None:
    attr = die.attributes.get("DW_AT_location")
    if attr is None:
        return None
    value = attr.value
    if isinstance(value, list) and len(value) >= 5 and value[0] == 0x03:
        return int.from_bytes(bytes(value[1:5]), "little")
    if isinstance(value, bytes) and len(value) >= 5 and value[0] == 0x03:
        return int.from_bytes(value[1:5], "little")
    return None


def _dwarf_type_die(die):
    if "DW_AT_type" not in die.attributes:
        return None
    try:
        return die.get_DIE_from_attribute("DW_AT_type")
    except Exception:
        return None


def _dwarf_unwrap_type(die):
    while die is not None and die.tag in {
        "DW_TAG_typedef",
        "DW_TAG_const_type",
        "DW_TAG_volatile_type",
        "DW_TAG_restrict_type",
    }:
        next_die = _dwarf_type_die(die)
        if next_die is None:
            return die
        die = next_die
    return die


def _dwarf_type_name(die) -> str:
    if die is None:
        return ""
    name = _dwarf_die_name(die)
    if name:
        return _normalize_mcu_type_name(name, _dwarf_type_size(die))
    unwrapped = _dwarf_unwrap_type(die)
    if unwrapped is None:
        return ""
    if unwrapped is not die:
        return _dwarf_type_name(unwrapped)
    if unwrapped.tag == "DW_TAG_pointer_type":
        return _normalize_mcu_type_name(f"{_dwarf_type_name(_dwarf_type_die(unwrapped)) or 'void'} *")
    if unwrapped.tag == "DW_TAG_array_type":
        return _normalize_mcu_type_name(f"{_dwarf_type_name(_dwarf_type_die(unwrapped))}[]")
    if unwrapped.tag == "DW_TAG_structure_type":
        return "struct"
    if unwrapped.tag == "DW_TAG_union_type":
        return "union"
    return _normalize_mcu_type_name(unwrapped.tag.replace("DW_TAG_", ""), _dwarf_type_size(unwrapped))


def _normalize_mcu_type_name(type_name: str, byte_size: int = 0) -> str:
    text = " ".join(type_name.replace("\t", " ").split()).strip()
    if not text:
        return ""
    if "*" in text:
        base, stars = text.split("*", 1)
        return f"{_normalize_mcu_type_name(base, byte_size).strip()} *{stars}".strip()
    if text.endswith("[]"):
        return f"{_normalize_mcu_type_name(text[:-2], byte_size)}[]"

    lower = text.lower()
    if lower in {"int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t"}:
        return lower
    tokens = [token for token in lower.split() if token not in {"const", "volatile", "restrict"}]
    if not tokens:
        return text
    unsigned = "unsigned" in tokens
    signed = "signed" in tokens
    long_count = tokens.count("long")

    if "char" in tokens:
        if unsigned:
            return "uint8_t"
        if signed:
            return "int8_t"
        return "char"
    if "short" in tokens:
        return "uint16_t" if unsigned else "int16_t"
    if long_count >= 2:
        return "uint64_t" if unsigned else "int64_t"
    if long_count == 1:
        return "uint32_t" if unsigned else "int32_t"
    if "int" in tokens or tokens in (["unsigned"], ["signed"]):
        return "uint32_t" if unsigned else "int32_t"
    if byte_size == 4 and unsigned and "int" not in tokens:
        return "uint32_t"
    return text


def _dwarf_type_size(die) -> int:
    die = _dwarf_unwrap_type(die)
    if die is None:
        return 0
    attr = die.attributes.get("DW_AT_byte_size")
    if attr is not None:
        return int(attr.value)
    if die.tag == "DW_TAG_pointer_type":
        return 4
    if die.tag == "DW_TAG_array_type":
        element_size = _dwarf_type_size(_dwarf_type_die(die))
        count = _dwarf_array_count(die)
        return element_size * count if element_size and count else 0
    return 0


def _expand_dwarf_type(
    die,
    *,
    base_name: str,
    base_address: int,
    section: str,
    source: str,
    depth: int,
    field_budget: int,
    parent_types: tuple[tuple[str, str], ...],
    template_seen: tuple[int, ...] = (),
) -> list[DebugVariable]:
    source_type_name = _dwarf_type_name(die)
    die = _dwarf_unwrap_type(die)
    if die is None or field_budget <= 0 or depth > 8:
        return []
    if die.tag in {"DW_TAG_base_type", "DW_TAG_enumeration_type", "DW_TAG_pointer_type"}:
        size = _dwarf_type_size(die)
        child_templates = _dwarf_pointee_templates(_dwarf_type_die(die), template_seen) if die.tag == "DW_TAG_pointer_type" else ()
        return [
            DebugVariable(
                name=base_name,
                address=base_address,
                size=max(size, 1),
                section=section,
                source=source,
                type_name=_dwarf_type_name(die),
                parent_types=parent_types,
                child_templates=child_templates,
            )
        ]
    if die.tag in {"DW_TAG_structure_type", "DW_TAG_union_type"}:
        aggregate_type = source_type_name or _dwarf_type_name(die) or die.tag.replace("DW_TAG_", "")
        child_parent_types = (*parent_types, (base_name, aggregate_type))
        fields: list[DebugVariable] = []
        for member in die.iter_children():
            if member.tag != "DW_TAG_member":
                continue
            member_name = _dwarf_die_name(member)
            if not member_name:
                continue
            member_type = _dwarf_type_die(member)
            offset = 0 if die.tag == "DW_TAG_union_type" else _dwarf_member_offset(member)
            child = _expand_dwarf_type(
                member_type,
                base_name=f"{base_name}.{member_name}",
                base_address=base_address + offset,
                section=section,
                source=source,
                depth=depth + 1,
                field_budget=field_budget - len(fields),
                parent_types=child_parent_types,
                template_seen=template_seen,
            )
            if child:
                fields.extend(child)
            else:
                size = _dwarf_type_size(member_type)
                fields.append(
                    DebugVariable(
                        name=f"{base_name}.{member_name}",
                        address=base_address + offset,
                        size=max(size, 1),
                        section=section,
                        source=source,
                        type_name=_dwarf_type_name(member_type),
                        parent_types=child_parent_types,
                    )
                )
            if len(fields) >= field_budget:
                break
        return fields
    if die.tag == "DW_TAG_array_type":
        dimensions = _dwarf_array_dimensions(die)
        count = _array_element_count(dimensions)
        element_type = _dwarf_type_die(die)
        element_size = _dwarf_type_size(element_type)
        total_size = _dwarf_type_size(die)
        if not dimensions or count <= 0 or element_size <= 0 or count > MAX_DWARF_ARRAY_EXPAND_COUNT:
            return [
                DebugVariable(
                    name=base_name,
                    address=base_address,
                    size=max(total_size, 1),
                section=section,
                source=source,
                type_name=_dwarf_type_name(die),
                parent_types=parent_types,
            )
        ]
        array_type = source_type_name or _dwarf_type_name(die)
        return _expand_dwarf_array_elements(
            element_type,
            dimensions=dimensions,
            element_size=element_size,
            base_name=base_name,
            base_address=base_address,
            section=section,
            source=source,
            depth=depth,
            field_budget=field_budget,
            parent_types=(*parent_types, (base_name, array_type)),
            template_seen=template_seen,
        )
    return []


def _dwarf_member_offset(member) -> int:
    attr = member.attributes.get("DW_AT_data_member_location")
    if attr is None:
        return 0
    value = attr.value
    if isinstance(value, int):
        return value
    if isinstance(value, list) and value and value[0] == 0x23:
        offset, _used = _read_uleb128(value, 1)
        return offset
    if isinstance(value, bytes) and value and value[0] == 0x23:
        offset, _used = _read_uleb128(list(value), 1)
        return offset
    return 0


def _dwarf_pointee_templates(pointee_die, seen: tuple[int, ...] = ()) -> tuple[DebugVariable, ...]:
    aggregate_die = _dwarf_unwrap_type(pointee_die)
    if aggregate_die is None or aggregate_die.tag not in {"DW_TAG_structure_type", "DW_TAG_union_type"}:
        return ()
    die_key = int(getattr(aggregate_die, "offset", id(aggregate_die)))
    if die_key in seen:
        return ()
    next_seen = (*seen, die_key)
    aggregate_type = _dwarf_type_name(pointee_die) or _dwarf_type_name(aggregate_die) or aggregate_die.tag.replace("DW_TAG_", "")
    templates: list[DebugVariable] = []
    for member in aggregate_die.iter_children():
        if member.tag != "DW_TAG_member":
            continue
        member_name = _dwarf_die_name(member)
        if not member_name:
            continue
        member_type = _dwarf_type_die(member)
        offset = 0 if aggregate_die.tag == "DW_TAG_union_type" else _dwarf_member_offset(member)
        child = _expand_dwarf_type(
            member_type,
            base_name=member_name,
            base_address=offset,
            section="",
            source="",
            depth=1,
            field_budget=MAX_DWARF_EXPANDED_FIELDS_PER_VARIABLE,
            parent_types=(("", aggregate_type),),
            template_seen=next_seen,
        )
        if child:
            templates.extend(child)
        else:
            templates.append(
                DebugVariable(
                    name=member_name,
                    address=offset,
                    size=max(_dwarf_type_size(member_type), 1),
                    section="",
                    source="",
                    type_name=_dwarf_type_name(member_type),
                )
            )
    return tuple(templates)


def _expand_dwarf_array_elements(
    element_type,
    *,
    dimensions: list[int],
    element_size: int,
    base_name: str,
    base_address: int,
    section: str,
    source: str,
    depth: int,
    field_budget: int,
    parent_types: tuple[tuple[str, str], ...],
    template_seen: tuple[int, ...] = (),
) -> list[DebugVariable]:
    if not dimensions or field_budget <= 0:
        return []
    current_count = dimensions[0]
    remaining = dimensions[1:]
    stride = element_size * (_array_element_count(remaining) or 1)
    fields: list[DebugVariable] = []
    for index in range(current_count):
        child_name = f"{base_name}[{index}]"
        child_address = base_address + index * stride
        if remaining:
            child_parent_types = (*parent_types, (child_name, "array element"))
            child = _expand_dwarf_array_elements(
                element_type,
                dimensions=remaining,
                element_size=element_size,
                base_name=child_name,
                base_address=child_address,
                section=section,
                source=source,
                depth=depth + 1,
                field_budget=field_budget - len(fields),
                parent_types=child_parent_types,
                template_seen=template_seen,
            )
        else:
            child = _expand_dwarf_type(
                element_type,
                base_name=child_name,
                base_address=child_address,
                section=section,
                source=source,
                depth=depth + 1,
                field_budget=field_budget - len(fields),
                parent_types=parent_types,
                template_seen=template_seen,
            )
        fields.extend(child)
        if len(fields) >= field_budget:
            break
    return fields


def _dwarf_array_count(array_die) -> int:
    return _array_element_count(_dwarf_array_dimensions(array_die))


def _dwarf_array_dimensions(array_die) -> list[int]:
    dimensions: list[int] = []
    for child in array_die.iter_children():
        if child.tag != "DW_TAG_subrange_type":
            continue
        count_attr = child.attributes.get("DW_AT_count")
        upper_attr = child.attributes.get("DW_AT_upper_bound")
        if count_attr is not None:
            dimensions.append(int(count_attr.value))
        elif upper_attr is not None and isinstance(upper_attr.value, int):
            dimensions.append(int(upper_attr.value) + 1)
        else:
            return []
    return dimensions


def _array_element_count(dimensions: list[int]) -> int:
    count = 1
    for dimension in dimensions:
        if dimension <= 0:
            return 0
        count *= dimension
    return count if dimensions else 0


def _read_uleb128(data: list[int], offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    index = offset
    while index < len(data):
        byte = data[index]
        index += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, index - offset


def _read_elf_sections(data: bytes, *, is_64_bit: bool, endian: str) -> list[dict[str, int]]:
    if is_64_bit:
        shoff = struct.unpack_from(endian + "Q", data, 40)[0]
        shentsize = struct.unpack_from(endian + "H", data, 58)[0]
        shnum = struct.unpack_from(endian + "H", data, 60)[0]
    else:
        shoff = struct.unpack_from(endian + "I", data, 32)[0]
        shentsize = struct.unpack_from(endian + "H", data, 46)[0]
        shnum = struct.unpack_from(endian + "H", data, 48)[0]

    sections: list[dict[str, int]] = []
    for index in range(shnum):
        offset = shoff + index * shentsize
        if is_64_bit:
            name, section_type, flags, addr, section_offset, size, link, _info, _align, entsize = struct.unpack_from(
                endian + "IIQQQQIIQQ", data, offset
            )
        else:
            name, section_type, flags, addr, section_offset, size, link, _info, _align, entsize = struct.unpack_from(
                endian + "IIIIIIIIII", data, offset
            )
        sections.append(
            {
                "name": name,
                "type": section_type,
                "flags": flags,
                "addr": addr,
                "offset": section_offset,
                "size": size,
                "link": link,
                "entsize": entsize,
            }
        )
    return sections


def _read_section_names(data: bytes, sections: list[dict[str, int]]) -> list[str]:
    if not sections:
        return []
    # e_shstrndx is not needed for symbol parsing, but it is useful for display.
    is_64_bit = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    shstrndx_offset = 62 if is_64_bit else 50
    shstrndx = struct.unpack_from(endian + "H", data, shstrndx_offset)[0]
    if shstrndx >= len(sections):
        return [""] * len(sections)
    name_table = _section_bytes(data, sections[shstrndx])
    return [_read_c_string(name_table, section["name"]) for section in sections]


def _read_elf_symbol(entry: bytes, *, is_64_bit: bool, endian: str) -> tuple[int, int, int, int, int]:
    if is_64_bit:
        name_offset, info, _other, shndx, value, size = struct.unpack_from(endian + "IBBHQQ", entry, 0)
        return name_offset, info, value, size, shndx
    name_offset, value, size, info, _other, shndx = struct.unpack_from(endian + "IIIBBH", entry, 0)
    return name_offset, info, value, size, shndx


def _section_bytes(data: bytes, section: dict[str, int]) -> bytes:
    start = section["offset"]
    end = start + section["size"]
    return data[start:end]


def _read_c_string(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\x00", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", errors="replace")


def _load_map_variables(path: Path) -> list[DebugVariable]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    candidates: list[tuple[int, str, str]] = []
    current_section = ""
    section_re = re.compile(r"^\s*(\.[A-Za-z0-9_.$]+)\s+0x([0-9A-Fa-f]+|\w+)")
    symbol_re = re.compile(r"^\s*(0x[0-9A-Fa-f]+)\s+([A-Za-z_.$][\w.$]*)\s*$")
    for line in lines:
        section_match = section_re.match(line)
        if section_match:
            current_section = section_match.group(1)
        symbol_match = symbol_re.match(line)
        if not symbol_match:
            continue
        address = int(symbol_match.group(1), 16)
        name = symbol_match.group(2)
        if _is_variable_name(name) and _looks_like_mcu_address(address) and _is_map_variable_section(current_section):
            candidates.append((address, name, current_section))

    candidates.sort(key=lambda item: item[0])
    variables: list[DebugVariable] = []
    for index, (address, name, section) in enumerate(candidates):
        next_address = candidates[index + 1][0] if index + 1 < len(candidates) else address + 4
        size = max(1, min(next_address - address, MAX_VARIABLE_READ_BYTES))
        variables.append(DebugVariable(name=name, address=address, size=size, section=section, source=path.name))
    return variables


def _merge_symbol_sources(elf_variables: list[DebugVariable], map_variables: list[DebugVariable]) -> list[DebugVariable]:
    if not elf_variables:
        return list(map_variables)
    elf_names = {variable.name for variable in elf_variables}
    merged = list(elf_variables)
    for variable in map_variables:
        if variable.name in elf_names:
            continue
        prefix = f"{variable.name}."
        array_prefix = f"{variable.name}["
        if any(name.startswith(prefix) or name.startswith(array_prefix) for name in elf_names):
            continue
        merged.append(variable)
    return merged


def _deduplicate_variables(variables: list[DebugVariable]) -> list[DebugVariable]:
    by_key: dict[tuple[int, str], DebugVariable] = {}
    for variable in variables:
        key = (variable.address, variable.name)
        previous = by_key.get(key)
        if previous is None or _prefer_variable(variable, previous):
            by_key[key] = variable
    return sorted(by_key.values(), key=lambda item: (item.address, item.name.lower()))


def _prefer_variable(candidate: DebugVariable, previous: DebugVariable) -> bool:
    if bool(candidate.type_name) != bool(previous.type_name):
        return bool(candidate.type_name)
    return candidate.size > previous.size


def _resolve_jlink_executable(configured: str) -> str | None:
    configured = configured.strip().strip('"')
    if configured:
        configured_path = Path(configured)
        if configured_path.is_file():
            return str(configured_path)
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        return None

    for name in ("JLink.exe", "JLinkExe.exe", "JLink", "JLinkExe"):
        resolved = shutil.which(name)
        if resolved:
            return resolved

    for candidate in (
        Path(os.environ.get("ProgramFiles", "")) / "SEGGER" / "JLink" / "JLink.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "SEGGER" / "JLink" / "JLink.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    for root in (Path(os.environ.get("ProgramFiles", "")) / "SEGGER", Path(os.environ.get("ProgramFiles(x86)", "")) / "SEGGER"):
        if not root.is_dir():
            continue
        for candidate in sorted(root.glob("JLink*/JLink.exe"), reverse=True):
            if candidate.is_file():
                return str(candidate)
    return None


def _build_read_ranges(variables: list[DebugVariable]) -> dict[int, int]:
    read_ranges: dict[int, int] = {}
    for variable in variables:
        read_size = min(max(variable.size, 1), MAX_VARIABLE_READ_BYTES)
        start = variable.address & ~0x03
        offset = variable.address - start
        word_count = max(1, math.ceil((offset + read_size) / 4))
        read_ranges[start] = max(read_ranges.get(start, 0), word_count)
    return read_ranges


def _build_string_read_ranges(variables: list[DebugVariable], memory: dict[int, int]) -> dict[int, int]:
    read_ranges: dict[int, int] = {}
    for variable in variables:
        if not _is_char_pointer_type(variable.type_name.strip().lower()):
            continue
        target = _pointer_value_from_memory(variable, memory)
        if target is None or target == 0 or not _looks_like_mcu_address(target):
            continue
        start = target & ~0x03
        offset = target - start
        word_count = math.ceil((offset + 64) / 4)
        read_ranges[start] = max(read_ranges.get(start, 0), word_count)
    return read_ranges


def _pointer_value_from_memory(variable: DebugVariable, memory: dict[int, int]) -> int | None:
    start = variable.address & ~0x03
    offset = variable.address - start
    raw = bytearray()
    for word_index in range(math.ceil((offset + 4) / 4)):
        word = memory.get(start + word_index * 4)
        if word is None:
            return None
        raw.extend(word.to_bytes(4, "little", signed=False))
    return int.from_bytes(bytes(raw[offset : offset + 4]), "little", signed=False)


def _validate_ram_write(address: int, size: int) -> None:
    if size <= 0:
        raise JLinkDebugError("Write size must be greater than 0.")
    end = address + size
    for start, stop in RAM_WRITE_RANGES:
        if start <= address and end <= stop:
            return
    raise JLinkDebugError(f"Refuse to write non-RAM address range 0x{address:08X}..0x{end - 1:08X}. Flash/code regions are protected.")


def is_ram_address(address: int) -> bool:
    return any(start <= address < stop for start, stop in RAM_WRITE_RANGES)


def is_jlink_expandable_address(address: int, ranges: list[JLinkMemoryRange] | None = None) -> bool:
    if ranges:
        return any(item.contains(address) for item in ranges)
    return any(start <= address < stop for start, stop in JLINK_POINTER_EXPAND_RANGES)


def _encode_write_value(variable: DebugVariable, value_text: str) -> bytes:
    text = value_text.strip()
    if not text:
        raise JLinkDebugError("Write value is empty.")
    size = max(variable.size, 1)
    if size > 8 and not _is_raw_hex_write(text):
        raise JLinkDebugError("Only scalar values up to 8 bytes can be written. Use hex: for explicit raw bytes.")
    type_text = variable.type_name.strip().lower()
    if _is_raw_hex_write(text):
        payload = _parse_raw_hex_write(text)
        if len(payload) > size:
            raise JLinkDebugError(f"Raw write has {len(payload)} byte(s), larger than variable size {size}.")
        if len(payload) > 64:
            raise JLinkDebugError("Raw write is limited to 64 bytes.")
        return payload
    if _is_prefixed_hex_write(text):
        write_size = size if size in (1, 2, 4, 8) else min(size, 8)
        return int(text, 16).to_bytes(write_size, "little", signed=False)
    if _is_pointer_type(type_text):
        return int(text, 0).to_bytes(min(size, 4), "little", signed=False)
    if type_text in {"float", "single"}:
        return struct.pack("<f", float(text))
    if type_text == "double":
        return struct.pack("<d", float(text))
    if _is_integer_type(type_text) or size in (1, 2, 4, 8):
        signed = _is_signed_integer_type(type_text) if type_text else False
        return int(text, 0).to_bytes(size if size in (1, 2, 4, 8) else 4, "little", signed=signed)
    raise JLinkDebugError(f"Unsupported J-Link RAM write type: {variable.type_name or 'unknown'}")


def _is_raw_hex_write(text: str) -> bool:
    return text.lower().startswith(("hex:", "raw:"))


def _is_prefixed_hex_write(text: str) -> bool:
    return text.lower().startswith("0x")


def _parse_raw_hex_write(text: str) -> bytes:
    payload = text.split(":", 1)[1]
    compact = re.sub(r"[^0-9A-Fa-f]", "", payload)
    if not compact or len(compact) % 2:
        raise JLinkDebugError("Raw hex write must contain full bytes, for example: hex: 01 02 03 04")
    return bytes.fromhex(compact)


def _run_jlink_read(
    *,
    executable: str,
    device: str,
    interface: str,
    speed_khz: int,
    read_ranges: dict[int, int],
) -> str:
    script_lines = [
        f"device {device}",
        f"if {interface}",
        f"speed {max(speed_khz, 1)}",
        "connect",
    ]
    for address, word_count in sorted(read_ranges.items()):
        script_lines.append(f"mem32 0x{address:08X}, {word_count}")
    script_lines.append("exit")
    return _run_jlink_script(executable=executable, script_lines=script_lines, timeout=30)


def _run_jlink_write(
    *,
    executable: str,
    device: str,
    interface: str,
    speed_khz: int,
    address: int,
    payload: bytes,
) -> str:
    script_lines = [
        f"device {device}",
        f"if {interface}",
        f"speed {max(speed_khz, 1)}",
        "connect",
    ]
    offset = 0
    while offset < len(payload):
        current_address = address + offset
        remaining = len(payload) - offset
        if current_address % 4 == 0 and remaining >= 4:
            value = int.from_bytes(payload[offset : offset + 4], "little", signed=False)
            script_lines.append(f"w4 0x{current_address:08X}, 0x{value:08X}")
            offset += 4
        elif current_address % 2 == 0 and remaining >= 2:
            value = int.from_bytes(payload[offset : offset + 2], "little", signed=False)
            script_lines.append(f"w2 0x{current_address:08X}, 0x{value:04X}")
            offset += 2
        else:
            script_lines.append(f"w1 0x{current_address:08X}, 0x{payload[offset]:02X}")
            offset += 1
    script_lines.append("exit")
    return _run_jlink_script(executable=executable, script_lines=script_lines, timeout=30)


def _run_jlink_script(*, executable: str, script_lines: list[str], timeout: int) -> str:
    script_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".jlink", delete=False, encoding="ascii") as handle:
            handle.write("\n".join(script_lines))
            handle.write("\n")
            script_path = handle.name
        result = subprocess.run(
            [executable, "-CommanderScript", script_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise JLinkDebugError(f"J-Link 读取失败: {exc}") from exc
    finally:
        if script_path:
            Path(script_path).unlink(missing_ok=True)

    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        raise JLinkDebugError(f"J-Link 返回错误码 {result.returncode}。\n{_tail_output(output)}")
    return output


def _hidden_subprocess_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _parse_jlink_mem32_output(output: str) -> dict[int, int]:
    memory: dict[int, int] = {}
    line_re = re.compile(r"^\s*([0-9A-Fa-f]{8})\s*=\s*((?:[0-9A-Fa-f]{8}\s*)+)")
    for line in output.splitlines():
        match = line_re.match(line)
        if not match:
            continue
        address = int(match.group(1), 16)
        for index, word_text in enumerate(match.group(2).split()):
            memory[address + index * 4] = int(word_text, 16)
    return memory


def _with_memory_value(
    variable: DebugVariable,
    memory: dict[int, int],
    *,
    symbol_names: dict[int, str] | None = None,
    string_memory: dict[int, int] | None = None,
) -> DebugVariable:
    read_size = min(max(variable.size, 1), MAX_VARIABLE_READ_BYTES)
    start = variable.address & ~0x03
    offset = variable.address - start
    byte_count = offset + read_size
    raw = bytearray()
    for word_index in range(math.ceil(byte_count / 4)):
        word_address = start + word_index * 4
        word = memory.get(word_address)
        if word is None:
            return replace(variable, raw_hex="", value="", status="读取失败")
        raw.extend(word.to_bytes(4, "little", signed=False))
    value_bytes = bytes(raw[offset : offset + read_size])
    suffix = " ..." if variable.size > MAX_VARIABLE_READ_BYTES else ""
    pointer_value = _pointer_value_from_bytes(value_bytes, variable.type_name)
    return replace(
        variable,
        pointer_value=pointer_value,
        raw_hex=value_bytes.hex(" ").upper() + suffix,
        value=_format_value(value_bytes, variable.type_name, symbol_names=symbol_names or {}, string_memory=string_memory or {}),
        status="OK",
    )


def _format_value(
    data: bytes,
    type_name: str,
    *,
    symbol_names: dict[int, str] | None = None,
    string_memory: dict[int, int] | None = None,
) -> str:
    type_text = type_name.strip().lower()
    if _is_pointer_type(type_text):
        pointer_value = int.from_bytes(data[:4], "little", signed=False)
        pointer_text = f"0x{pointer_value:08X}"
        ascii_text = _ascii_string_from_memory(pointer_value, string_memory or {}) if _is_char_pointer_type(type_text) else ""
        if ascii_text:
            return f'{pointer_text} "{ascii_text}"'
        symbol = _symbol_name_for_address(pointer_value, symbol_names or {})
        if symbol:
            return f"{symbol} ({pointer_text})"
        return pointer_text
    if _is_char_array_type(type_text):
        ascii_text = _ascii_string_from_bytes(data)
        if ascii_text:
            return f'"{ascii_text}"'
    if type_text in {"float", "single"} and len(data) >= 4:
        return f"{struct.unpack('<f', data[:4])[0]:.7g}"
    if type_text in {"double"} and len(data) >= 8:
        return f"{struct.unpack('<d', data[:8])[0]:.15g}"
    if _is_integer_type(type_text) and len(data) in (1, 2, 4, 8):
        signed = _is_signed_integer_type(type_text)
        return str(int.from_bytes(data, "little", signed=signed))
    if len(data) in (1, 2, 4, 8):
        return str(int.from_bytes(data, "little", signed=False))
    return f"{len(data)} bytes"


def _pointer_value_from_bytes(data: bytes, type_name: str) -> int | None:
    if len(data) < 4 or not _is_pointer_type(type_name.strip().lower()):
        return None
    return int.from_bytes(data[:4], "little", signed=False)


def _is_pointer_type(type_text: str) -> bool:
    return "*" in type_text or type_text in {"uintptr_t", "intptr_t"}


def _is_char_pointer_type(type_text: str) -> bool:
    normalized = type_text.replace("const", "").replace("volatile", "").replace("signed", "").strip()
    return "*" in normalized and ("char" in normalized or "int8_t" in normalized or "uint8_t" in normalized)


def _is_char_array_type(type_text: str) -> bool:
    normalized = type_text.replace("const", "").replace("volatile", "").replace("signed", "").strip()
    return normalized.endswith("[]") and ("char" in normalized or "int8_t" in normalized or "uint8_t" in normalized)


def _ascii_string_from_memory(address: int, memory: dict[int, int]) -> str:
    if not memory:
        return ""
    raw = bytearray()
    start = address & ~0x03
    offset = address - start
    for word_index in range(math.ceil((offset + 64) / 4)):
        word = memory.get(start + word_index * 4)
        if word is None:
            break
        raw.extend(word.to_bytes(4, "little", signed=False))
    return _ascii_string_from_bytes(bytes(raw[offset:]))


def _ascii_string_from_bytes(data: bytes) -> str:
    if not data:
        return ""
    raw = data.split(b"\x00", 1)[0]
    if not raw:
        return ""
    if any(byte < 0x20 or byte > 0x7E for byte in raw):
        return ""
    return raw.decode("ascii", errors="ignore")


def _symbol_name_for_address(address: int, symbol_names: dict[int, str]) -> str:
    if not symbol_names:
        return ""
    symbol = symbol_names.get(address)
    if symbol:
        return symbol
    if address & 1:
        return symbol_names.get(address & ~1, "")
    return ""


def _symbol_address_by_name(name: str, symbol_names: dict[int, str]) -> int | None:
    for address, symbol in symbol_names.items():
        if symbol == name:
            return address
    return None


def _is_integer_type(type_text: str) -> bool:
    tokens = {"char", "short", "int", "long", "bool", "uint", "int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t"}
    return any(token in type_text for token in tokens)


def _is_signed_integer_type(type_text: str) -> bool:
    if "unsigned" in type_text or "uint" in type_text or type_text in {"bool", "_bool"}:
        return False
    return True


def _is_variable_name(name: str) -> bool:
    if not name or name.startswith((".", "$")):
        return False
    if name in {"__bss_start__", "__bss_end__", "_edata", "_end", "end"}:
        return False
    return not name.startswith("__")


def _is_debug_or_metadata_section(section_name: str) -> bool:
    return section_name.startswith((".debug", ".comment", ".ARM.attributes", ".symtab", ".strtab"))


def _is_map_variable_section(section_name: str) -> bool:
    if not section_name:
        return False
    excluded_prefixes = (
        ".text",
        ".init",
        ".fini",
        ".isr_vector",
        ".ARM.exidx",
        ".ARM.extab",
        ".eh_frame",
    )
    if section_name.startswith(excluded_prefixes):
        return False
    included_prefixes = (
        ".data",
        ".bss",
        ".rodata",
        ".sdata",
        ".sbss",
        ".tdata",
        ".tbss",
        ".noinit",
        ".ram",
        ".ccm",
    )
    return section_name.startswith(included_prefixes)


def _looks_like_mcu_address(address: int) -> bool:
    return 0x00000000 <= address <= 0xFFFFFFFF


def _tail_output(output: str, max_lines: int = 12) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])
