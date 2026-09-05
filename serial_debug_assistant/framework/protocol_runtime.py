from __future__ import annotations

import queue
from collections.abc import Callable
from dataclasses import dataclass, field

from serial_debug_assistant.comm.protocol_parser import ProtocolParser
from serial_debug_assistant.comm.protocol_router import ProtocolRouter
from serial_debug_assistant.comm.protocol_sender import ProtocolSender
from serial_debug_assistant.models import ProtocolFrame, SerialChunk


RawChunkHandler = Callable[[SerialChunk], None]
FrameLogger = Callable[[ProtocolFrame], None]


@dataclass(slots=True)
class RxProcessResult:
    updated: bool = False
    processed_chunks: int = 0
    processed_bytes: int = 0
    has_more: bool = False
    raw_chunks: list[SerialChunk] = field(default_factory=list)


class ProtocolRuntime:
    """Run the byte -> frame -> route framework independently of transports."""

    def __init__(self, write_bytes: Callable[[bytes], int], *, logger=None) -> None:
        self.logger = logger
        self.parser = ProtocolParser()
        self.router = ProtocolRouter(logger=logger)
        self.sender = ProtocolSender(write_bytes, logger=logger)
        self._frame_logger: FrameLogger | None = None
        self._rx_idle_polls = 0

    def set_frame_logger(self, frame_logger: FrameLogger | None) -> None:
        self._frame_logger = frame_logger

    def reset(self) -> None:
        self.parser.reset()

    def process_rx(
        self,
        *,
        service,
        transport: str | None,
        protocol_available: bool,
        max_chunks: int,
        max_bytes: int,
        raw_chunk_handler: RawChunkHandler | None = None,
    ) -> RxProcessResult:
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
            if protocol_available:
                self._feed_protocol_bytes(chunk.data, transport=transport)

        if result.processed_chunks:
            self._rx_idle_polls = 0
        elif service.rx_queue.empty():
            self._rx_idle_polls += 1

        result.has_more = not service.rx_queue.empty()
        return result

    def _feed_protocol_bytes(self, data: bytes, *, transport: str | None) -> None:
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
        if transport == "can":
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
            if self._frame_logger is not None:
                self._frame_logger(frame)
            self.router.dispatch(frame)

    def _log(self, category: str, message: str) -> None:
        if self.logger is not None:
            self.logger.log(category, message)
