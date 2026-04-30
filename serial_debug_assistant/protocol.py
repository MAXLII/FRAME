from __future__ import annotations

import struct

from serial_debug_assistant.models import ProtocolFrame


SOP = 0xE8
EOP_BYTE = b"\x0D"
EOP_BYTES_ALT = b"\x0D\x0A"
PROTOCOL_VERSION = 0x01
PC_SRC = 0x01
PC_DYN_SRC = 0x00
MAX_PAYLOAD_LEN = 2048
PC_DST = 0x01
PC_BROADCAST_DST = 0x00
PC_DYN_DST = 0x01
PC_DYN_BROADCAST_DST = 0x00
VALID_COMMANDS = {
    0x01: set(range(0x01, 0x2F)),
    0x02: {0x01, 0x02},
}


def is_frame_addressed_to_pc(dst: int, d_dst: int) -> bool:
    if dst == PC_BROADCAST_DST:
        return d_dst == PC_DYN_BROADCAST_DST
    if dst == PC_DST:
        return d_dst in {PC_DYN_BROADCAST_DST, PC_DYN_DST}
    return False

STA_SOP = 0
STA_VER = 1
STA_SRC = 2
STA_DST = 3
STA_CMD = 4
STA_ACK = 5
STA_LEN = 6
STA_DATA = 7
STA_CRC = 8
STA_EOP = 9

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
        crc = crc16_update(crc, byte, poly=poly)
    return crc & 0xFFFF


def crc16_update(crc: int, data: int, poly: int = 0x1021) -> int:
    crc ^= (data & 0xFF) << 8
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
        self.dropped_incomplete_frames = 0
        self.last_drop_reason = ""
        self.last_drop_state = ""
        self.last_drop_expected_payload_len = 0
        self.last_drop_received_payload_len = 0
        self.last_drop_preview = b""
        self.reset()

    def reset(self) -> None:
        self.buffer = bytearray()
        self.status = STA_SOP
        self.index = 0
        self.remaining_len = 0
        self.crc = 0
        self.sop = 0
        self.version = 0
        self.src = 0
        self.d_src = 0
        self.dst = 0
        self.d_dst = 0
        self.cmd_set = 0
        self.cmd_word = 0
        self.is_ack = 0
        self.payload_len = 0
        self.payload = bytearray()
        self.recv_crc = 0
        self.eop = 0
        self.src_flag = 0
        self.dst_flag = 0
        self.cmd_flag = 0
        self.len_flag = 0
        self.eop_flag = 0

    def feed(self, data: bytes) -> list[ProtocolFrame]:
        frames: list[ProtocolFrame] = []
        for byte in data:
            frames.extend(self._run_byte(byte))
        return frames

    def _start_frame(self, data: int) -> None:
        self.reset()
        self.sop = data
        self.buffer.append(data)
        self.crc = crc16_update(0xFFFF, data)
        self.status = STA_VER

    def _reset_after_error(self, reason: str) -> list[ProtocolFrame]:
        discarded = bytes(self.buffer)
        self._drop_incomplete_frame(reason)
        self.reset()
        next_sop = discarded.find(bytes([SOP]), 1)
        if next_sop == -1:
            return []
        return self.feed(discarded[next_sop:])

    def _drop_incomplete_frame(self, reason: str) -> None:
        self.dropped_incomplete_frames += 1
        self.last_drop_reason = reason
        self.last_drop_state = self._status_name()
        self.last_drop_expected_payload_len = self.payload_len
        self.last_drop_received_payload_len = len(self.payload)
        self.last_drop_preview = bytes(self.buffer[:48])

    def _status_name(self) -> str:
        names = {
            STA_SOP: "SOP",
            STA_VER: "VER",
            STA_SRC: "SRC",
            STA_DST: "DST",
            STA_CMD: "CMD",
            STA_ACK: "ACK",
            STA_LEN: "LEN",
            STA_DATA: "DATA",
            STA_CRC: "CRC",
            STA_EOP: "EOP",
        }
        return names.get(self.status, f"UNKNOWN({self.status})")

    def _run_byte(self, data: int) -> list[ProtocolFrame]:
        data &= 0xFF
        frames: list[ProtocolFrame] = []

        if self.status == STA_SOP:
            if data == SOP:
                self._start_frame(data)
            return frames

        self.buffer.append(data)

        if self.status == STA_VER:
            self.version = data
            self.crc = crc16_update(self.crc, data)
            if self.version != PROTOCOL_VERSION:
                return self._reset_after_error("invalid version")
            self.src_flag = 0
            self.status = STA_SRC
            return frames

        if self.status == STA_SRC:
            self.crc = crc16_update(self.crc, data)
            if self.src_flag == 0:
                self.src = data
                self.src_flag = 1
            else:
                self.d_src = data
                self.dst_flag = 0
                self.status = STA_DST
            return frames

        if self.status == STA_DST:
            self.crc = crc16_update(self.crc, data)
            if self.dst_flag == 0:
                self.dst = data
                if self.dst not in {PC_BROADCAST_DST, PC_DST}:
                    return self._reset_after_error("invalid destination")
                self.dst_flag = 1
            else:
                self.d_dst = data
                if not is_frame_addressed_to_pc(self.dst, self.d_dst):
                    return self._reset_after_error("invalid dynamic destination")
                self.cmd_flag = 0
                self.status = STA_CMD
            return frames

        if self.status == STA_CMD:
            self.crc = crc16_update(self.crc, data)
            if self.cmd_flag == 0:
                self.cmd_set = data
                if self.cmd_set not in VALID_COMMANDS:
                    return self._reset_after_error("invalid command set")
                self.cmd_flag = 1
            else:
                self.cmd_word = data
                if self.cmd_word not in VALID_COMMANDS[self.cmd_set]:
                    return self._reset_after_error("invalid command word")
                self.status = STA_ACK
            return frames

        if self.status == STA_ACK:
            self.is_ack = data
            self.crc = crc16_update(self.crc, data)
            self.payload_len = 0
            self.len_flag = 0
            self.status = STA_LEN
            return frames

        if self.status == STA_LEN:
            self.crc = crc16_update(self.crc, data)
            if self.len_flag == 0:
                self.payload_len = data
                self.len_flag = 1
            else:
                self.payload_len |= data << 8
                if self.payload_len > MAX_PAYLOAD_LEN:
                    return self._reset_after_error("payload too long")
                self.remaining_len = self.payload_len
                self.index = 0
                self.payload = bytearray()
                self.status = STA_DATA
            return frames

        if self.status == STA_DATA:
            if self.remaining_len != 0:
                self.payload.append(data)
                self.index += 1
                self.remaining_len -= 1
                self.crc = crc16_update(self.crc, data)
            else:
                self.recv_crc = data
                self.status = STA_CRC
            return frames

        if self.status == STA_CRC:
            self.recv_crc |= data << 8
            if self.crc != self.recv_crc:
                return self._reset_after_error("crc mismatch")
            self.eop = 0
            self.eop_flag = 0
            self.status = STA_EOP
            return frames

        if self.status == STA_EOP:
            if self.eop_flag == 0:
                self.eop = data
                self.eop_flag = 1
                return frames

            self.eop |= data << 8
            if self.eop != 0x0A0D:
                return self._reset_after_error("invalid eop")

            frame = ProtocolFrame(
                sop=self.sop,
                version=self.version,
                src=self.src,
                d_src=self.d_src,
                dst=self.dst,
                d_dst=self.d_dst,
                cmd_set=self.cmd_set,
                cmd_word=self.cmd_word,
                is_ack=self.is_ack,
                payload=bytes(self.payload),
                crc=self.recv_crc,
            )
            self.reset()
            frames.append(frame)
            return frames

        return self._reset_after_error("invalid parser state")


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
