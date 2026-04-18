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


@dataclass(slots=True)
class FirmwareFooter:
    unix_time: int
    fw_type: int
    version: int
    file_size: int
    commit_id: str
    module_id: int
    crc32: int


@dataclass(slots=True)
class FirmwareImage:
    path: str
    data: bytes
    footer: FirmwareFooter
    footer_crc_ok: bool
    payload_crc16: int
    warnings: list[str]


@dataclass(slots=True)
class FirmwareUpdateSession:
    image: FirmwareImage
    target_addr: int
    target_dynamic_addr: int
    update_type: int
    packet_size: int = 1024
    active: bool = True
    stage: str = "send_info"
    offset: int = 0
    sent_bytes: int = 0
    current_packet_offset: int = 0
    last_tx_at: float = 0.0
    timeout_error_since: float | None = None
    data_error_since: float | None = None
    stop_requested: bool = False
    result_message: str = ""
    error_code: str = ""
    detail_message: str = ""
    llc_forward_query_interval_seconds: float = 1.0
    llc_forward_progress_sent_bytes: int = 0
    llc_forward_progress_total_bytes: int = 0
    llc_forward_progress_permille: int = 0
