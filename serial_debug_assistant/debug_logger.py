from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading
from typing import Callable


class DebugLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._subscribers: list[Callable[[str], None]] = []
        self._lock = threading.Lock()
        # Keep a buffered handle open to avoid re-opening the log file for every line.
        self._handle = self.log_path.open("a", encoding="utf-8", buffering=64 * 1024)

    def subscribe(self, callback: Callable[[str], None]) -> None:
        self._subscribers.append(callback)

    def log(self, category: str, message: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S.%f}"[:-3] + f" [{category}] {message}"
        with self._lock:
            self._handle.write(line + "\n")
        for callback in self._subscribers:
            callback(line)

    def flush(self) -> None:
        with self._lock:
            self._handle.flush()

    def close(self) -> None:
        with self._lock:
            if self._handle.closed:
                return
            self._handle.flush()
            self._handle.close()
