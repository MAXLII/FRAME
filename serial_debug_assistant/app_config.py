from __future__ import annotations

import json
from pathlib import Path
from typing import Any


APP_CONFIG_VERSION = 1


def load_app_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": APP_CONFIG_VERSION}
    if not isinstance(data, dict):
        return {"version": APP_CONFIG_VERSION}
    data.setdefault("version", APP_CONFIG_VERSION)
    return data


def save_app_config(path: Path, data: dict[str, Any]) -> None:
    payload = dict(data)
    payload["version"] = APP_CONFIG_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def load_config_section(path: Path, section: str) -> dict[str, Any]:
    data = load_app_config(path)
    value = data.get(section)
    return value if isinstance(value, dict) else {}


def save_config_section(path: Path, section: str, value: dict[str, Any]) -> None:
    data = load_app_config(path)
    data[section] = value
    save_app_config(path, data)


def normalized_scalar(value: Any) -> str | bool | int | float | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    return None
