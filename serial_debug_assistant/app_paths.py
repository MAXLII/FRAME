from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys


APP_DIR_NAME = "FRAME"


@dataclass(frozen=True)
class AppPaths:
    install_root: Path
    data_root: Path
    config_dir: Path
    exports_dir: Path
    logs_dir: Path
    quick_send_config: Path
    app_log_file: Path


def get_app_paths() -> AppPaths:
    install_root = _get_install_root()
    data_root = _get_data_root(install_root)
    config_dir = data_root / "config"
    exports_dir = data_root / "exports"
    logs_dir = data_root / "logs"
    return AppPaths(
        install_root=install_root,
        data_root=data_root,
        config_dir=config_dir,
        exports_dir=exports_dir,
        logs_dir=logs_dir,
        quick_send_config=config_dir / "quick_send.cfg",
        app_log_file=logs_dir / "app_debug.log",
    )


def ensure_runtime_dirs(paths: AppPaths) -> None:
    for directory in (paths.config_dir, paths.exports_dir, paths.logs_dir):
        directory.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data(paths: AppPaths) -> list[str]:
    if not getattr(sys, "frozen", False):
        return []

    legacy_root = paths.install_root
    if legacy_root == paths.data_root:
        return []

    notes: list[str] = []
    legacy_config = legacy_root / "config" / "quick_send.cfg"
    if legacy_config.is_file() and not paths.quick_send_config.exists():
        paths.config_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_config, paths.quick_send_config)
        notes.append(f"migrated preset config to {paths.quick_send_config}")

    legacy_exports = legacy_root / "exports"
    copied_exports = _copy_missing_tree(legacy_exports, paths.exports_dir)
    if copied_exports:
        notes.append(f"migrated {copied_exports} export file(s) to {paths.exports_dir}")

    legacy_log = legacy_root / "logs" / "app_debug.log"
    if legacy_log.is_file() and not paths.app_log_file.exists():
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_log, paths.app_log_file)
        notes.append(f"migrated debug log to {paths.app_log_file}")

    return notes


def _copy_missing_tree(source_dir: Path, target_dir: Path) -> int:
    if not source_dir.is_dir():
        return 0

    copied_files = 0
    for source_path in sorted(source_dir.rglob("*")):
        relative_path = source_path.relative_to(source_dir)
        target_path = target_dir / relative_path
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        if target_path.exists():
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied_files += 1
    return copied_files


def _get_install_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _get_data_root(install_root: Path) -> Path:
    if not getattr(sys, "frozen", False):
        return install_root

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"
