from __future__ import annotations

import struct

from serial_debug_assistant.models import ProtocolFrame


SOP = 0xE8
EOP_BYTE = b"\x0D"
EOP_BYTES_ALT = b"\x0D\x0A"
PROTOCOL_VERSION = 0x01
PC_SRC = 0x01
PC_DYN_SRC = 0x00

TYPE_NAMES = {
    0: "INT8",
    1: "UINT8",
    2: "INT16",
    3: "UINT16",
    4: "INT32",
    5: "UINT32",
    6: "FP32",
    7: "CMD",
}


def crc16_ccitt(data: bytes, init: int = 0xFFFF, poly: int = 0x1021) -> int:
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def build_frame(
    *,
    dst: int,
    d_dst: int,
    cmd_set: int,
    cmd_word: int,
    is_ack: int = 0,
    payload: bytes = b"",
    version: int = PROTOCOL_VERSION,
    src: int = PC_SRC,
    d_src: int = PC_DYN_SRC,
) -> bytes:
    header = struct.pack(
        "<BBBBBBBBBH",
        SOP,
        version,
        src,
        d_src,
        dst,
        d_dst,
        cmd_set,
        cmd_word,
        is_ack,
        len(payload),
    )
    body = header + payload
    crc = crc16_ccitt(body)
    return body + struct.pack("<H", crc) + EOP_BYTES_ALT


class FrameParser:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[ProtocolFrame]:
        self.buffer.extend(data)
        frames: list[ProtocolFrame] = []

        while True:
            frame = self._extract_one()
            if frame is None:
                break
            frames.append(frame)

        return frames

    def _extract_one(self) -> ProtocolFrame | None:
        while self.buffer and self.buffer[0] != SOP:
            del self.buffer[0]

        min_len = 14
        if len(self.buffer) < min_len:
            return None

        payload_len = int.from_bytes(self.buffer[9:11], "little")
        body_len = 11 + payload_len
        crc_start = body_len
        total_len_1 = body_len + 2 + 1
        total_len_2 = body_len + 2 + 2
        if len(self.buffer) < total_len_1:
            return None

        if len(self.buffer) >= total_len_2 and bytes(self.buffer[crc_start + 2 : total_len_2]) == EOP_BYTES_ALT:
            raw = bytes(self.buffer[:total_len_2])
            eop_len = 2
        elif bytes(self.buffer[crc_start + 2 : total_len_1]) == EOP_BYTE:
            raw = bytes(self.buffer[:total_len_1])
            eop_len = 1
        else:
            del self.buffer[0]
            return self._extract_one()

        body = raw[:body_len]
        recv_crc = int.from_bytes(raw[crc_start : crc_start + 2], "little")
        calc_crc = crc16_ccitt(body)
        if recv_crc != calc_crc:
            del self.buffer[0]
            return self._extract_one()

        del self.buffer[: body_len + 2 + eop_len]
        return ProtocolFrame(
            sop=raw[0],
            version=raw[1],
            src=raw[2],
            d_src=raw[3],
            dst=raw[4],
            d_dst=raw[5],
            cmd_set=raw[6],
            cmd_word=raw[7],
            is_ack=raw[8],
            payload=raw[11 : 11 + payload_len],
            crc=recv_crc,
        )


def u32_to_value(raw: int, type_id: int) -> int | float:
    raw &= 0xFFFFFFFF
    if type_id == 0:
        return struct.unpack("<b", struct.pack("<B", raw & 0xFF))[0]
    if type_id == 1:
        return raw & 0xFF
    if type_id == 2:
        return struct.unpack("<h", struct.pack("<H", raw & 0xFFFF))[0]
    if type_id == 3:
        return raw & 0xFFFF
    if type_id == 4:
        return struct.unpack("<i", struct.pack("<I", raw))[0]
    if type_id == 5:
        return raw
    if type_id == 6:
        return struct.unpack("<f", struct.pack("<I", raw))[0]
    return raw


def value_to_u32(value_text: str, type_id: int) -> int:
    if type_id == 6:
        return struct.unpack("<I", struct.pack("<f", float(value_text)))[0]
    if type_id in {0, 1, 2, 3, 4, 5, 7}:
        return int(float(value_text)) & 0xFFFFFFFF
    raise ValueError(f"Unsupported type: {type_id}")


def format_value(raw: int, type_id: int) -> str:
    value = u32_to_value(raw, type_id)
    if type_id == 6:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)
