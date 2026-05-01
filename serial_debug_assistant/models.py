from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SerialChunk:
    timestamp: float
    data: bytes
    synthetic: bool = False


@dataclass(slots=True)
class ScopeListItem:
    scope_id: int
    name: str


@dataclass(slots=True)
class ScopeInfo:
    scope_id: int
    status: int
    state: int
    data_ready: bool
    var_count: int
    sample_count: int
    write_index: int
    trigger_index: int
    trigger_post_cnt: int
    trigger_display_index: int
    sample_period_us: int
    capture_tag: int


@dataclass(slots=True)
class ScopeCapture:
    scope_id: int
    scope_name: str
    capture_tag: int
    read_mode: int
    sample_period_us: int
    sample_count: int
    trigger_display_index: int
    var_names: list[str]
    samples: list[list[float]]
    capture_index: int
    capture_changed_during_pull: bool = False


@dataclass(slots=True)
class ScopePullSession:
    scope_id: int
    scope_name: str
    read_mode: int
    expected_capture_tag: int
    sample_count: int
    pull_interval_ms: int = 50
    next_sample_index: int = 0
    waiting_ack: bool = False
    completed: bool = False
    failed: bool = False
    fail_reason: str = ""
    samples: list[list[float]] | None = None
    last_request_at: float = 0.0
    timeout_seconds: float = 1.5
    retry_count: int = 0
    max_retries: int = 3


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

    @property
    def is_readonly(self) -> bool:
        return not self.is_command and self.min_raw == self.max_raw


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
