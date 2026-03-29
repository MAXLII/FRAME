from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SerialChunk:
    timestamp: float
    data: bytes


@dataclass(slots=True)
class ProtocolFrame:
    sop: int
    version: int
    src: int
    d_src: int
    dst: int
    d_dst: int
    cmd_set: int
    cmd_word: int
    is_ack: int
    payload: bytes
    crc: int


@dataclass(slots=True)
class ParameterEntry:
    name: str
    type_id: int
    data_raw: int
    min_raw: int
    max_raw: int
    status: int = 0
    auto_report: bool = False
    important: bool = False
    dirty: bool = False

    @property
    def is_command(self) -> bool:
        return self.type_id == 7
