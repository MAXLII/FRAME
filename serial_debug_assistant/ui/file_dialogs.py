from __future__ import annotations

from pathlib import Path
from tkinter import filedialog


_LAST_DIRS: dict[str, Path] = {}


def ask_open_file(
    *,
    key: str,
    title: str,
    initialdir: str | Path | None = None,
    initialfile: str | None = None,
    filetypes=None,
) -> str:
    options = _dialog_options(
        key=key,
        title=title,
        initialdir=initialdir,
        initialfile=initialfile,
        filetypes=filetypes,
    )
    path = filedialog.askopenfilename(**options)
    _remember_dir(key, path)
    return path


def ask_save_file(
    *,
    key: str,
    title: str,
    initialdir: str | Path | None = None,
    initialfile: str | None = None,
    defaultextension: str | None = None,
    filetypes=None,
) -> str:
    options = _dialog_options(
        key=key,
        title=title,
        initialdir=initialdir,
        initialfile=initialfile,
        filetypes=filetypes,
    )
    if defaultextension:
        options["defaultextension"] = defaultextension
    path = filedialog.asksaveasfilename(**options)
    _remember_dir(key, path)
    return path


def preferred_dir(*paths: str | Path | None, fallback: str | Path | None = None) -> Path | None:
    for item in paths:
        if not item:
            continue
        path = Path(item)
        if path.is_file():
            return path.parent
        if path.is_dir():
            return path
    if fallback:
        fallback_path = Path(fallback)
        if fallback_path.exists():
            return fallback_path if fallback_path.is_dir() else fallback_path.parent
    return None


def _dialog_options(
    *,
    key: str,
    title: str,
    initialdir: str | Path | None,
    initialfile: str | None,
    filetypes,
) -> dict[str, object]:
    options: dict[str, object] = {"title": title}
    directory = _resolve_initial_dir(key, initialdir)
    if directory is not None:
        options["initialdir"] = str(directory)
    if initialfile:
        options["initialfile"] = initialfile
    if filetypes:
        options["filetypes"] = filetypes
    return options


def _resolve_initial_dir(key: str, initialdir: str | Path | None) -> Path | None:
    remembered = _LAST_DIRS.get(key)
    if remembered is not None and remembered.is_dir():
        return remembered
    if initialdir:
        directory = Path(initialdir)
        if directory.is_file():
            directory = directory.parent
        if directory.is_dir():
            return directory
    return None


def _remember_dir(key: str, path_text: str) -> None:
    if not path_text:
        return
    path = Path(path_text)
    directory = path.parent if path.suffix or path.is_file() else path
    if directory.is_dir():
        _LAST_DIRS[key] = directory
