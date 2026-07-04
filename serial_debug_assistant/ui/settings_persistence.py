from __future__ import annotations

from pathlib import Path
from typing import Any

from serial_debug_assistant.app_config import load_app_config, normalized_scalar, save_config_section


SETTINGS_FILE_VERSION = 1


def load_ui_settings(path: Path) -> dict[str, str | bool | int | float]:
    data = load_app_config(path)
    if not isinstance(data, dict):
        return {}
    section = data.get("ui_settings")
    values = section.get("values") if isinstance(section, dict) else data.get("values")
    if not isinstance(values, dict):
        return {}
    settings: dict[str, str | bool | int | float] = {}
    for key, value in values.items():
        if not isinstance(key, str):
            continue
        normalized = normalized_scalar(value)
        if normalized is not None:
            settings[key] = normalized
    return settings


def save_ui_settings(path: Path, values: dict[str, Any]) -> None:
    payload = {
        "version": SETTINGS_FILE_VERSION,
        "values": {
            key: normalized
            for key, value in sorted(values.items())
            if isinstance(key, str) and (normalized := normalized_scalar(value)) is not None
        },
    }
    save_config_section(path, "ui_settings", payload)
