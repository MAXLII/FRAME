from __future__ import annotations

from collections.abc import Callable

from serial_debug_assistant.protocol import build_frame


class ProtocolSender:
    """Build custom protocol frames and write them through the active transport."""

    def __init__(self, write_bytes: Callable[[bytes], int], *, logger=None) -> None:
        self._write_bytes = write_bytes
        self.logger = logger

    def send(
        self,
        *,
        dst: int,
        d_dst: int,
        cmd_set: int,
        cmd_word: int,
        payload: bytes = b"",
        is_ack: int = 0,
    ) -> tuple[int, bytes]:
        frame = build_frame(
            dst=dst,
            d_dst=d_dst,
            cmd_set=cmd_set,
            cmd_word=cmd_word,
            is_ack=is_ack,
            payload=payload,
        )
        if self.logger is not None:
            self.logger.log(
                "TX",
                f"protocol dst=0x{dst:02X} d_dst=0x{d_dst:02X} "
                f"cmd_set=0x{cmd_set:02X} cmd_word=0x{cmd_word:02X} "
                f"is_ack={is_ack} len={len(payload)} frame={frame.hex(' ').upper()}",
            )
        return self._write_bytes(frame), frame
