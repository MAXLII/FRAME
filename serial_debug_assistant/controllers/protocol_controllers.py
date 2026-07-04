from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from serial_debug_assistant.models import ProtocolFrame


ProtocolHandler = Callable[[ProtocolFrame], bool]


@dataclass(slots=True)
class FeatureProtocolController:
    name: str
    handler: ProtocolHandler

    def handle(self, frame: ProtocolFrame) -> bool:
        return self.handler(frame)


class ProtocolControllerHub:
    """Owns application-level protocol dispatch order.

    The communication layer routes complete frames here. Each feature controller
    keeps one protocol responsibility, while the main Tk app remains the
    composition root for widgets, services, and shared scheduling.
    """

    def __init__(self, app) -> None:
        self.app = app
        self._home_controller = FeatureProtocolController("home", app._handle_home_protocol_frame)
        self._controllers: list[FeatureProtocolController] = [
            FeatureProtocolController("upgrade", app._handle_upgrade_protocol_frame),
            FeatureProtocolController("factory_mode", app._handle_factory_mode_protocol_frame),
            FeatureProtocolController("black_box", app._handle_black_box_protocol_frame),
            FeatureProtocolController("scope", app._handle_scope_protocol_frame),
            FeatureProtocolController("sfra", app._handle_sfra_protocol_frame),
            FeatureProtocolController("perf", app._handle_perf_protocol_frame),
            FeatureProtocolController("trace", app._handle_trace_protocol_frame),
            FeatureProtocolController("parameter_wave", app._handle_parameter_wave_protocol_frame),
        ]

    def register_routes(self, router) -> None:
        router.register_fallback(self.handle_frame)

    def handle_frame(self, frame: ProtocolFrame) -> bool:
        if self._home_controller.handle(frame):
            return True
        if frame.cmd_set != 0x01:
            return False
        for controller in self._controllers:
            if controller.handle(frame):
                return True
        return self._log_unhandled(frame)

    def _log_unhandled(self, frame: ProtocolFrame) -> bool:
        if self.app.connected_transport == "can":
            self.app.logger.log(
                "PARAM",
                f"unhandled frame on CAN cmd_set=0x{frame.cmd_set:02X} cmd_word=0x{frame.cmd_word:02X} "
                f"is_ack={frame.is_ack} len={len(frame.payload)} payload={frame.payload.hex(' ').upper()}",
            )
            return True
        return False
