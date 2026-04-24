from __future__ import annotations

import queue
from dataclasses import dataclass, field
from typing import Callable

import serial

from serial_debug_assistant.comm.protocol_parser import ProtocolParser
from serial_debug_assistant.comm.protocol_router import ProtocolRouter
from serial_debug_assistant.comm.protocol_sender import ProtocolSender
from serial_debug_assistant.models import ProtocolFrame, SerialChunk
from serial_debug_assistant.services.can_service import CANService
from serial_debug_assistant.services.serial_service import SerialService


RawChunkHandler = Callable[[SerialChunk], None]
FrameLogger = Callable[[ProtocolFrame], None]


@dataclass(slots=True)
class RxProcessResult:
    updated: bool = False
    processed_chunks: int = 0
    processed_bytes: int = 0
    has_more: bool = False
    raw_chunks: list[SerialChunk] = field(default_factory=list)


class CommunicationManager:
    """Owns the hardware -> parser -> router communication chain."""

    def __init__(self, *, serial_service: SerialService, can_service: CANService, logger=None) -> None:
        self.serial_service = serial_service
        self.can_service = can_service
        self.logger = logger
        self.parser = ProtocolParser()
        self.router = ProtocolRouter(logger=logger)
        self.sender = ProtocolSender(self.write_bytes, logger=logger)
        self.connected_transport: str | None = None
        self.endpoint: str | None = None
        self._frame_logger: FrameLogger | None = None
        self._rx_idle_polls = 0

    def set_frame_logger(self, frame_logger: FrameLogger | None) -> None:
        self._frame_logger = frame_logger

    def open_serial(
        self,
        *,
        port: str,
        baudrate: int,
        data_bits: str,
        parity: str,
        stop_bits: str,
        auto_break_enabled_supplier,
        break_ms_supplier,
        error_callback,
    ) -> None:
        self.close()
        self.serial_service.open(
            port=port,
            baudrate=baudrate,
            data_bits=data_bits,
            parity=parity,
            stop_bits=stop_bits,
        )
        self.serial_service.start_reader(
            auto_break_enabled_supplier=auto_break_enabled_supplier,
            break_ms_supplier=break_ms_supplier,
            error_callback=error_callback,
        )
        self.connected_transport = "serial"
        self.endpoint = port
        self.parser.reset()
        self._log("COMM", f"open serial endpoint={port} baud={baudrate}")

    def open_can(
        self,
        *,
        interface: str,
        channel: str,
        bitrate: int,
        error_callback,
    ) -> None:
        self.close()
        self.can_service.open(interface=interface, channel=channel, bitrate=bitrate)
        self.can_service.configure_tx_arbitration(0x100, is_extended_id=False)
        self.can_service.configure_rx_filter(0x101, is_extended_id=False)
        self.can_service.start_reader(error_callback=error_callback)
        self.connected_transport = "can"
        self.endpoint = channel
        self.parser.reset()
        self._log("COMM", f"open can interface={interface} channel={channel} bitrate={bitrate} tx=0x100 rx=0x101")

    def enable_demo(self) -> None:
        self.close()
        self.serial_service.enable_demo_connection()
        self.connected_transport = "demo"
        self.endpoint = "DEMO"
        self.parser.reset()
        self._log("COMM", "open demo")

    def disable_demo(self) -> None:
        self.serial_service.disable_demo_connection()
        if self.connected_transport == "demo":
            self.connected_transport = None
            self.endpoint = None
        self.parser.reset()
        self._log("COMM", "close demo")

    def close(self) -> None:
        transport = self.connected_transport
        self.can_service.close()
        self.serial_service.close()
        self.connected_transport = None
        self.endpoint = None
        self.parser.reset()
        if transport is not None:
            self._log("COMM", f"close {transport}")

    def is_open(self) -> bool:
        service = self.active_service()
        return bool(service and service.is_open())

    def protocol_available(self) -> bool:
        return self.connected_transport in {"serial", "can", "demo"}

    def active_service(self):
        if self.connected_transport in {"serial", "demo"}:
            return self.serial_service
        if self.connected_transport == "can":
            return self.can_service
        return None

    def write_bytes(self, payload: bytes) -> int:
        if self.connected_transport == "can":
            return self.can_service.send_bytes(payload)
        if self.connected_transport in {"serial", "demo"}:
            return self.serial_service.write(payload)
        raise RuntimeError("No hardware transport is open.")

    def send_protocol(
        self,
        *,
        dst: int,
        d_dst: int,
        cmd_set: int,
        cmd_word: int,
        payload: bytes = b"",
        is_ack: int = 0,
    ) -> tuple[int, bytes]:
        if not self.protocol_available():
            raise RuntimeError("Protocol transport is not available.")
        return self.sender.send(
            dst=dst,
            d_dst=d_dst,
            cmd_set=cmd_set,
            cmd_word=cmd_word,
            payload=payload,
            is_ack=is_ack,
        )

    def send_raw_debug_bytes(self, payload: bytes) -> int:
        if not self.is_open():
            raise RuntimeError("No hardware transport is open.")
        sent = self.write_bytes(payload)
        self._log("TX", f"raw transport={self.connected_transport} len={len(payload)} sent={sent} bytes={payload.hex(' ').upper()}")
        return sent

    def process_rx(
        self,
        *,
        max_chunks: int,
        max_bytes: int,
        raw_chunk_handler: RawChunkHandler | None = None,
    ) -> RxProcessResult:
        service = self.active_service()
        result = RxProcessResult()
        if service is None:
            return result

        while result.processed_chunks < max_chunks and result.processed_bytes < max_bytes:
            try:
                chunk = service.rx_queue.get_nowait()
            except queue.Empty:
                break

            result.updated = True
            result.raw_chunks.append(chunk)
            if raw_chunk_handler is not None:
                raw_chunk_handler(chunk)

            if chunk.synthetic and chunk.data == b"\n":
                continue

            result.processed_chunks += 1
            result.processed_bytes += len(chunk.data)
            if self.protocol_available():
                self._feed_protocol_bytes(chunk.data)

        if result.processed_chunks:
            self._rx_idle_polls = 0
        elif service.rx_queue.empty():
            self._rx_idle_polls += 1

        result.has_more = not service.rx_queue.empty()
        return result

    def _feed_protocol_bytes(self, data: bytes) -> None:
        buffer_before = self.parser.buffer_len
        dropped_before = self.parser.dropped_incomplete_frames
        try:
            frames = self.parser.feed(data)
        except Exception as exc:
            self._log("ERROR", f"protocol parser error: {exc}")
            self.parser.reset()
            return

        buffer_after = self.parser.buffer_len
        dropped_after = self.parser.dropped_incomplete_frames
        if self.connected_transport == "can":
            if frames:
                self._log(
                    "CANPARSE",
                    f"chunk_len={len(data)} parsed={len(frames)} "
                    f"buffer_before={buffer_before} buffer_after={buffer_after} "
                    f"chunk={data.hex(' ').upper()}",
                )
            elif dropped_after != dropped_before:
                self._log(
                    "CANPARSE",
                    f"dropped_incomplete={dropped_after - dropped_before} total_dropped={dropped_after} "
                    f"reason={self.parser.last_drop_reason} state={self.parser.last_drop_state} "
                    f"payload={self.parser.last_drop_received_payload_len}/{self.parser.last_drop_expected_payload_len} "
                    f"dropped_head={self.parser.last_drop_preview.hex(' ').upper()} "
                    f"buffer_before={buffer_before} buffer_after={buffer_after} chunk={data.hex(' ').upper()}",
                )
            elif buffer_after or 0xE8 in data or b"\r\n" in data:
                self._log(
                    "CANPARSE",
                    f"chunk_len={len(data)} parsed=0 "
                    f"buffer_before={buffer_before} buffer_after={buffer_after} "
                    f"chunk={data.hex(' ').upper()} buffer_head={self.parser.buffer_preview().hex(' ').upper()}",
                )

        for frame in frames:
            self._dispatch_frame(frame)

    def _dispatch_frame(self, frame: ProtocolFrame) -> None:
        if self._frame_logger is not None:
            self._frame_logger(frame)
        self.router.dispatch(frame)

    def _log(self, category: str, message: str) -> None:
        if self.logger is not None:
            self.logger.log(category, message)
