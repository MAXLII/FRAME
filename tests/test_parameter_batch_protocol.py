from __future__ import annotations

import struct

import pytest

from serial_debug_assistant.parameter_protocol import (
    parse_parameter_list_batch_payload,
    parse_parameter_wave_batch_payload,
)
from serial_debug_assistant.protocol import FrameParser, build_frame
from serial_debug_assistant.ui.wave_tab import WaveformTab


def _item(name: str, *, type_id: int = 5, value: int = 1, status: int = 0) -> bytes:
    name_bytes = name.encode("utf-8")
    return (
        bytes((len(name_bytes), type_id))
        + value.to_bytes(4, "little")
        + (100).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + bytes((status,))
        + name_bytes
    )


def test_parse_parameter_list_batch() -> None:
    payload = struct.pack("<IIH", 2, 0, 2) + _item("RUN", status=1) + _item("VOLT_REF", type_id=6)

    batch = parse_parameter_list_batch_payload(payload)

    assert batch.total_count == 2
    assert batch.first_index == 0
    assert [entry.name for entry in batch.entries] == ["RUN", "VOLT_REF"]
    assert batch.entries[0].auto_report is True


def test_parse_parameter_list_batch_rejects_truncated_item() -> None:
    payload = struct.pack("<IIH", 1, 0, 1) + _item("CURRENT")[:-1]

    with pytest.raises(ValueError, match="truncated"):
        parse_parameter_list_batch_payload(payload)


def test_frame_parser_accepts_ten_kib_payload() -> None:
    payload = bytes(10 * 1024)
    encoded = build_frame(dst=0x01, d_dst=0x01, cmd_set=0x01, cmd_word=0x3F, payload=payload)

    frames = FrameParser().feed(encoded)

    assert len(frames) == 1
    assert frames[0].payload == payload


def test_parse_parameter_wave_batch_with_simulation_tick() -> None:
    name = b"SIM_OUTPUT"
    item = bytes((len(name), 6)) + struct.pack("<I", 0x3FC00000) + name
    payload = struct.pack("<IIIH", 12345, 1, 0, 1) + item

    batch = parse_parameter_wave_batch_payload(payload)

    assert batch.simulation_tick_100us == 12345
    assert batch.total_count == 1
    assert batch.first_index == 0
    assert batch.values[0].name == "SIM_OUTPUT"
    assert batch.values[0].data_raw == 0x3FC00000


def test_parse_parameter_wave_batch_rejects_discontinuous_range() -> None:
    payload = struct.pack("<IIIH", 1, 2, 2, 1)

    with pytest.raises(ValueError, match="index range"):
        parse_parameter_wave_batch_payload(payload)


def test_simulation_time_axis_uses_elapsed_time() -> None:
    tab = object.__new__(WaveformTab)
    tab._time_axis_mode = "simulation"

    assert tab._format_time_axis_value(0.0, milliseconds=True) == "0:000"
    assert tab._format_time_axis_value(61.234, milliseconds=True) == "61:234"
    assert tab._format_time_axis_value(3661.234) == "3661:234"
