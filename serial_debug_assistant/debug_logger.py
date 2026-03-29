from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable


class DebugLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._subscribers: list[Callable[[str], None]] = []

    def subscribe(self, callback: Callable[[str], None]) -> None:
        self._subscribers.append(callback)

    def log(self, category: str, message: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S.%f}"[:-3] + f" [{category}] {message}"
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        for callback in self._subscribers:
            callback(line)
