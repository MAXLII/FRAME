from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from serial_debug_assistant.models import ProtocolFrame


ProtocolHandler = Callable[[ProtocolFrame], bool | None]


@dataclass(frozen=True, slots=True)
class RouteKey:
    cmd_set: int | None
    cmd_word: int | None
    is_ack: int | None

    def matches(self, frame: ProtocolFrame) -> bool:
        if self.cmd_set is not None and self.cmd_set != frame.cmd_set:
            return False
        if self.cmd_word is not None and self.cmd_word != frame.cmd_word:
            return False
        if self.is_ack is not None and self.is_ack != frame.is_ack:
            return False
        return True


class ProtocolRouter:
    """Dispatch complete protocol frames to feature/page handlers."""

    def __init__(self, *, logger=None) -> None:
        self._routes: list[tuple[RouteKey, ProtocolHandler]] = []
        self._fallback_handlers: list[ProtocolHandler] = []
        self.logger = logger

    def clear(self) -> None:
        self._routes.clear()
        self._fallback_handlers.clear()

    def register(
        self,
        handler: ProtocolHandler,
        *,
        cmd_set: int | None = None,
        cmd_word: int | None = None,
        is_ack: int | None = None,
    ) -> None:
        self._routes.append((RouteKey(cmd_set, cmd_word, is_ack), handler))

    def register_fallback(self, handler: ProtocolHandler) -> None:
        self._fallback_handlers.append(handler)

    def dispatch(self, frame: ProtocolFrame) -> bool:
        for key, handler in list(self._routes):
            if not key.matches(frame):
                continue
            if self._call_handler(handler, frame):
                return True

        for handler in list(self._fallback_handlers):
            if self._call_handler(handler, frame):
                return True

        if self.logger is not None:
            self.logger.log(
                "ROUTER",
                f"unhandled cmd_set=0x{frame.cmd_set:02X} cmd_word=0x{frame.cmd_word:02X} "
                f"is_ack={frame.is_ack} len={len(frame.payload)}",
            )
        return False

    def _call_handler(self, handler: ProtocolHandler, frame: ProtocolFrame) -> bool:
        try:
            handled = handler(frame)
        except Exception as exc:
            if self.logger is not None:
                self.logger.log(
                    "ERROR",
                    "protocol handler failed "
                    f"cmd_set=0x{frame.cmd_set:02X} cmd_word=0x{frame.cmd_word:02X} "
                    f"is_ack={frame.is_ack} err={exc}",
                )
            return True
        return handled is not False
