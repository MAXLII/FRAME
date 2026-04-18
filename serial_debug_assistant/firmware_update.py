from __future__ import annotations

from datetime import datetime
from pathlib import Path
import struct

from serial_debug_assistant.models import FirmwareFooter, FirmwareImage
from serial_debug_assistant.protocol import crc16_ccitt


CMD_SET_UPDATE = 0x01
CMD_WORD_UPDATE_INFO = 0x08
CMD_WORD_UPDATE_READY = 0x09
CMD_WORD_UPDATE_FW = 0x0A
CMD_WORD_UPDATE_END = 0x0B
CMD_WORD_LLC_PFC_UPGRADE_PROGRESS_QUERY = 0x0D

UPDATE_TYPE_NORMAL = 1
UPDATE_TYPE_FORCE = 2
UPDATE_PACKET_SIZE = 1024
FOOTER_SIZE = 34
FW_TYPE_IAP = 1

LLC_PFC_UPGRADE_STAGE_NAMES = {
    0: "idle",
    1: "queued",
    2: "enter_boot",
    3: "erasing",
    4: "forwarding",
    5: "verifying",
    6: "switching_app",
    7: "done",
    8: "failed",
}

LLC_PFC_UPGRADE_RESULT_NAMES = {
    0: "in_progress",
    1: "success",
    2: "failed",
}

LLC_PFC_UPGRADE_ERROR_NAMES = {
    0x0000: "none",
    0x0001: "busy",
    0x0002: "invalid_state",
    0x0004: "offset_mismatch",
    0x0008: "write_fail",
    0x0010: "crc_fail",
    0x0020: "timeout",
    0x0040: "jump_fail",
}

MODULE_NAMES = {
    0x01: "HOST",
    0x02: "LLC",
    0x03: "PFC",
}


def calculate_crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
    return crc & 0xFFFFFFFF


def format_version(version: int) -> str:
    return ".".join(
        str((version >> shift) & 0xFF)
        for shift in (24, 16, 8, 0)
    )


def format_unix_time(unix_time: int) -> str:
    try:
        return datetime.fromtimestamp(unix_time).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return f"Invalid ({unix_time})"


def module_name(module_id: int) -> str:
    return f"{MODULE_NAMES.get(module_id, 'Unknown')} (0x{module_id:02X})"


def describe_reject_reason(raw: int) -> str:
    reasons: list[str] = []
    if raw & 0x0001:
        reasons.append("oversize")
    if raw & 0x0002:
        reasons.append("version_err")
    if raw & 0x0004:
        reasons.append("module_err")
    if not reasons:
        reasons.append("unknown")
    return "|".join(reasons)


def load_firmware_image(path: str | Path) -> FirmwareImage:
    file_path = Path(path)
    data = file_path.read_bytes()
    if len(data) < FOOTER_SIZE:
        raise ValueError("Firmware file is too short to parse the footer.")

    footer_raw = data[-FOOTER_SIZE:]
    unix_time, fw_type, version, file_size, commit_raw, module_id, crc32 = struct.unpack(
        "<IBII16sBI",
        footer_raw,
    )
    footer = FirmwareFooter(
        unix_time=unix_time,
        fw_type=fw_type,
        version=version,
        file_size=file_size,
        commit_id=commit_raw.decode("ascii", errors="replace").rstrip("\x00"),
        module_id=module_id,
        crc32=crc32,
    )

    footer_crc = calculate_crc32(footer_raw[:-4])
    warnings: list[str] = []
    if footer.fw_type != FW_TYPE_IAP:
        warnings.append(f"fw_type={footer.fw_type}; only fw_type=1 IAP firmware supports online upgrade.")
    expected_body_size = max(len(data) - FOOTER_SIZE, 0)
    if footer.file_size not in {expected_body_size, len(data)}:
        warnings.append(
            f"footer.file_size={footer.file_size} does not match the actual file length {len(data)}."
        )

    return FirmwareImage(
        path=str(file_path),
        data=data,
        footer=footer,
        footer_crc_ok=(footer_crc == footer.crc32),
        payload_crc16=crc16_ccitt(data),
        warnings=warnings,
    )


def build_update_info_payload(image: FirmwareImage, update_type: int) -> bytes:
    return struct.pack(
        "<BIIB",
        image.footer.module_id,
        image.footer.version,
        len(image.data),
        update_type,
    )


def build_update_ready_payload() -> bytes:
    return b""


def build_update_packet_payload(image: FirmwareImage, offset: int, packet_size: int = UPDATE_PACKET_SIZE) -> bytes:
    chunk = image.data[offset : offset + packet_size]
    packet_data = chunk + (b"\xFF" * (packet_size - len(chunk)))
    body = struct.pack("<IBH", offset, image.footer.module_id, len(chunk)) + packet_data
    packet_crc = crc16_ccitt(body)
    return body + struct.pack("<H", packet_crc)


def build_update_end_payload(image: FirmwareImage) -> bytes:
    return struct.pack("<H", image.payload_crc16)


def build_llc_pfc_upgrade_progress_query_payload() -> bytes:
    return b""


def llc_pfc_upgrade_stage_name(stage: int) -> str:
    return LLC_PFC_UPGRADE_STAGE_NAMES.get(stage, f"unknown_stage_{stage}")


def llc_pfc_upgrade_result_name(result: int) -> str:
    return LLC_PFC_UPGRADE_RESULT_NAMES.get(result, f"unknown_result_{result}")


def describe_llc_pfc_upgrade_error(error_code: int) -> str:
    if error_code == 0:
        return "none"
    errors = [
        name
        for bit, name in LLC_PFC_UPGRADE_ERROR_NAMES.items()
        if bit != 0 and (error_code & bit)
    ]
    if errors:
        return "|".join(errors)
    return f"0x{error_code:04X}"


def parse_llc_pfc_upgrade_progress_ack(payload: bytes) -> dict[str, int | str]:
    if len(payload) < struct.calcsize("<BBBBIIIHHH"):
        raise ValueError(f"Invalid LLC->PFC progress ACK length: {len(payload)}")

    (
        source_module_id,
        target_module_id,
        stage,
        result,
        forwarded_bytes,
        total_bytes,
        packet_offset,
        packet_length,
        progress_permille,
        error_code,
    ) = struct.unpack("<BBBBIIIHHH", payload[: struct.calcsize("<BBBBIIIHHH")])

    return {
        "source_module_id": source_module_id,
        "target_module_id": target_module_id,
        "stage": stage,
        "result": result,
        "forwarded_bytes": forwarded_bytes,
        "total_bytes": total_bytes,
        "packet_offset": packet_offset,
        "packet_length": packet_length,
        "progress_permille": progress_permille,
        "error_code": error_code,
        "stage_name": llc_pfc_upgrade_stage_name(stage),
        "result_name": llc_pfc_upgrade_result_name(result),
        "error_name": describe_llc_pfc_upgrade_error(error_code),
    }
