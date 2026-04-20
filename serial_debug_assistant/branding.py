from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import sys


DEFAULT_APP_NAME = "FRAME"
BRAND_MARKER_FILE = "app_brand.txt"
DEFAULT_HIDDEN_TABS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RuntimeBranding:
    app_name: str = DEFAULT_APP_NAME
    app_version: str | None = None
    hidden_tabs: frozenset[str] = DEFAULT_HIDDEN_TABS


def _parse_hidden_tabs(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def _read_brand_marker() -> RuntimeBranding:
    if not getattr(sys, "frozen", False):
        return RuntimeBranding()

    marker_path = Path(sys.executable).resolve().parent / BRAND_MARKER_FILE
    try:
        raw_text = marker_path.read_text(encoding="utf-8").strip()
    except OSError:
        raw_text = ""
    if not raw_text:
        return RuntimeBranding()

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if lines and all("=" not in line for line in lines):
        return RuntimeBranding(app_name=lines[0])

    values: dict[str, str] = {}
    for line in lines:
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lower()] = value.strip()

    return RuntimeBranding(
        app_name=values.get("app_name", DEFAULT_APP_NAME) or DEFAULT_APP_NAME,
        app_version=values.get("app_version") or None,
        hidden_tabs=_parse_hidden_tabs(values.get("hidden_tabs", "")),
    )


@lru_cache(maxsize=1)
def get_runtime_branding() -> RuntimeBranding:
    branding = _read_brand_marker()

    env_name = os.environ.get("FRAME_APP_NAME", "").strip()
    env_version = os.environ.get("FRAME_APP_VERSION", "").strip()
    env_hidden_tabs = os.environ.get("FRAME_HIDDEN_TABS", "").strip()

    app_name = env_name or branding.app_name
    app_version = env_version or branding.app_version
    hidden_tabs = _parse_hidden_tabs(env_hidden_tabs) if env_hidden_tabs else branding.hidden_tabs

    return RuntimeBranding(
        app_name=app_name or DEFAULT_APP_NAME,
        app_version=app_version or None,
        hidden_tabs=hidden_tabs,
    )


def resolve_runtime_app_name(default_name: str = DEFAULT_APP_NAME) -> str:
    return get_runtime_branding().app_name or default_name
