from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import struct


CMD_SET_FACTORY_TIME_QUERY = 0x01
CMD_WORD_FACTORY_TIME_QUERY = 0x12
CMD_SET_FACTORY_TIME_WRITE = 0x01
CMD_WORD_FACTORY_TIME_WRITE = 0x13
CMD_SET_FACTORY_CALI_READ = 0x01
CMD_WORD_FACTORY_CALI_READ = 0x14
CMD_SET_FACTORY_CALI_WRITE = 0x01
CMD_WORD_FACTORY_CALI_WRITE = 0x15
CMD_SET_FACTORY_CALI_SAVE = 0x01
CMD_WORD_FACTORY_CALI_SAVE = 0x16

FACTORY_TIME_PAYLOAD_FORMAT = "<Ib"
FACTORY_TIME_PAYLOAD_SIZE = struct.calcsize(FACTORY_TIME_PAYLOAD_FORMAT)
CALI_QUERY_PAYLOAD_FORMAT = "<B"
CALI_QUERY_PAYLOAD_SIZE = struct.calcsize(CALI_QUERY_PAYLOAD_FORMAT)
CALI_INFO_PAYLOAD_FORMAT = "<Bff"
CALI_INFO_PAYLOAD_SIZE = struct.calcsize(CALI_INFO_PAYLOAD_FORMAT)
TIMEZONE_HALF_HOUR_MIN = -24
TIMEZONE_HALF_HOUR_MAX = 28
CALI_ID_LABELS: list[tuple[int, str]] = [
    (0, "Grid Voltage"),
    (1, "Inverter Voltage"),
    (2, "Inverter Current"),
    (3, "Battery Voltage"),
    (4, "Battery Current"),
    (5, "PV Voltage"),
    (6, "PV Current"),
]


def build_factory_time_query_payload() -> bytes:
    return b""


def build_factory_time_write_payload(unix_time_utc: int, timezone_half_hour: int) -> bytes:
    return struct.pack(
        FACTORY_TIME_PAYLOAD_FORMAT,
        int(unix_time_utc) & 0xFFFFFFFF,
        int(timezone_half_hour),
    )


def parse_factory_time_payload(payload: bytes) -> dict[str, int]:
    if len(payload) < FACTORY_TIME_PAYLOAD_SIZE:
        raise ValueError(f"Invalid factory time payload length: {len(payload)}")
    unix_time_utc, timezone_half_hour = struct.unpack(
        FACTORY_TIME_PAYLOAD_FORMAT,
        payload[:FACTORY_TIME_PAYLOAD_SIZE],
    )
    return {
        "unix_time_utc": unix_time_utc,
        "timezone_half_hour": timezone_half_hour,
    }


def build_factory_cali_read_payload(cali_id: int) -> bytes:
    return struct.pack(CALI_QUERY_PAYLOAD_FORMAT, int(cali_id) & 0xFF)


def build_factory_cali_write_payload(cali_id: int, gain: float, bias: float) -> bytes:
    return struct.pack(
        CALI_INFO_PAYLOAD_FORMAT,
        int(cali_id) & 0xFF,
        float(gain),
        float(bias),
    )


def build_factory_cali_save_payload() -> bytes:
    return b""


def parse_factory_cali_payload(payload: bytes) -> dict[str, float | int]:
    if len(payload) < CALI_INFO_PAYLOAD_SIZE:
        raise ValueError(f"Invalid calibration payload length: {len(payload)}")
    cali_id, gain, bias = struct.unpack(
        CALI_INFO_PAYLOAD_FORMAT,
        payload[:CALI_INFO_PAYLOAD_SIZE],
    )
    return {
        "cali_id": int(cali_id),
        "gain": float(gain),
        "bias": float(bias),
    }


def get_factory_cali_label_pairs() -> list[tuple[int, str]]:
    return list(CALI_ID_LABELS)


def format_timezone_label(timezone_half_hour: int) -> str:
    sign = "+" if timezone_half_hour >= 0 else "-"
    absolute_half_hours = abs(timezone_half_hour)
    hours = absolute_half_hours // 2
    minutes = (absolute_half_hours % 2) * 30
    if minutes == 0:
        return f"UTC{sign}{hours}"
    return f"UTC{sign}{hours}:{minutes:02d}"


def format_factory_time_string(unix_time_utc: int, timezone_half_hour: int) -> str:
    tz = timezone(timedelta(minutes=int(timezone_half_hour) * 30))
    local_time = datetime.fromtimestamp(int(unix_time_utc), tz=timezone.utc).astimezone(tz)
    return f"{local_time.strftime('%Y-%m-%d %H:%M:%S')} {format_timezone_label(timezone_half_hour)}"


def parse_timezone_input(text: str) -> int:
    normalized = text.strip().upper().replace("UTC", "")
    if not normalized:
        raise ValueError("Timezone is required.")

    colon_match = re.fullmatch(r"([+-]?)(\d{1,2}):([03]0)", normalized)
    if colon_match:
        sign_text, hour_text, minute_text = colon_match.groups()
        sign = -1 if sign_text == "-" else 1
        half_hours = int(hour_text) * 2 + (1 if minute_text == "30" else 0)
        value = sign * half_hours
    else:
        numeric_value = float(normalized)
        half_hours_float = numeric_value * 2.0
        if abs(half_hours_float - round(half_hours_float)) > 1e-6:
            raise ValueError("Timezone must be in 0.5-hour increments.")
        value = int(round(half_hours_float))

    if not (TIMEZONE_HALF_HOUR_MIN <= value <= TIMEZONE_HALF_HOUR_MAX):
        raise ValueError(
            f"Timezone must be between {format_timezone_label(TIMEZONE_HALF_HOUR_MIN)} and {format_timezone_label(TIMEZONE_HALF_HOUR_MAX)}."
        )
    return value
