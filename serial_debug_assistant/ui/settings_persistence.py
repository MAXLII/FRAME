from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SETTINGS_FILE_VERSION = 1


def load_ui_settings(path: Path) -> dict[str, str | bool | int | float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    values = data.get("values")
    if not isinstance(values, dict):
        return {}
    settings: dict[str, str | bool | int | float] = {}
    for key, value in values.items():
        if not isinstance(key, str):
            continue
        normalized = _normalize_setting_value(value)
        if normalized is not None:
            settings[key] = normalized
    return settings


def save_ui_settings(path: Path, values: dict[str, Any]) -> None:
    payload = {
        "version": SETTINGS_FILE_VERSION,
        "values": {
            key: normalized
            for key, value in sorted(values.items())
            if isinstance(key, str) and (normalized := _normalize_setting_value(value)) is not None
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _normalize_setting_value(value: Any) -> str | bool | int | float | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    return None
