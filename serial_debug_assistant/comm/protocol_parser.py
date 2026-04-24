from __future__ import annotations

from serial_debug_assistant.models import ProtocolFrame
from serial_debug_assistant.protocol import FrameParser


class ProtocolParser:
    """Byte-stream parser for the custom protocol.

    Hardware layers must feed raw bytes here. The parser owns protocol framing
    and resynchronization, so CAN/serial/future transports stay byte pipes.
    """

    def __init__(self) -> None:
        self._parser = FrameParser()

    def reset(self) -> None:
        self._parser.reset()

    @property
    def buffer_len(self) -> int:
        return len(self._parser.buffer)

    @property
    def dropped_incomplete_frames(self) -> int:
        return self._parser.dropped_incomplete_frames

    @property
    def last_drop_reason(self) -> str:
        return self._parser.last_drop_reason

    @property
    def last_drop_state(self) -> str:
        return self._parser.last_drop_state

    @property
    def last_drop_expected_payload_len(self) -> int:
        return self._parser.last_drop_expected_payload_len

    @property
    def last_drop_received_payload_len(self) -> int:
        return self._parser.last_drop_received_payload_len

    @property
    def last_drop_preview(self) -> bytes:
        return self._parser.last_drop_preview

    def buffer_preview(self, limit: int = 24) -> bytes:
        return bytes(self._parser.buffer[:limit])

    def feed(self, data: bytes) -> list[ProtocolFrame]:
        return self._parser.feed(data)

    def feed_byte(self, byte: int) -> list[ProtocolFrame]:
        return self._parser.feed(bytes([byte & 0xFF]))
