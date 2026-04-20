from __future__ import annotations

import os
from pathlib import Path
import sys


DEFAULT_APP_NAME = "FRAME"
BRAND_MARKER_FILE = "app_brand.txt"


def resolve_runtime_app_name(default_name: str = DEFAULT_APP_NAME) -> str:
    override = os.environ.get("FRAME_APP_NAME", "").strip()
    if override:
        return override

    if getattr(sys, "frozen", False):
        marker_path = Path(sys.executable).resolve().parent / BRAND_MARKER_FILE
        try:
            brand_name = marker_path.read_text(encoding="utf-8").strip()
        except OSError:
            brand_name = ""
        if brand_name:
            return brand_name

    return default_name
