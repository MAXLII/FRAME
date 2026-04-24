from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ByteTransport(Protocol):
    name: str

    def close(self) -> None: ...

    def is_open(self) -> bool: ...

    def write_bytes(self, payload: bytes) -> int: ...


@dataclass(slots=True)
class TransportEndpoint:
    transport: str
    endpoint: str
