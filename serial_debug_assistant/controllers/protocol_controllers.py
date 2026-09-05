from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from serial_debug_assistant.models import ProtocolFrame


ProtocolHandler = Callable[[ProtocolFrame], bool]
TransportSupplier = Callable[[], str | None]


@dataclass(slots=True)
class FeatureProtocolController:
    name: str
    handler: ProtocolHandler

    def handle(self, frame: ProtocolFrame) -> bool:
        return self.handler(frame)


@dataclass(frozen=True, slots=True)
class ProtocolControllerPorts:
    """Narrow business boundary exposed by the presentation composition root."""

    home_handler: ProtocolHandler
    feature_handlers: tuple[tuple[str, ProtocolHandler], ...]
    transport_supplier: TransportSupplier
    logger: object

    @classmethod
    def from_legacy_app(cls, app) -> ProtocolControllerPorts:
        return cls(
            home_handler=app._handle_home_protocol_frame,
            feature_handlers=(
                ("upgrade", app._handle_upgrade_protocol_frame),
                ("factory_mode", app._handle_factory_mode_protocol_frame),
                ("black_box", app._handle_black_box_protocol_frame),
                ("scope", app._handle_scope_protocol_frame),
                ("sfra", app._handle_sfra_protocol_frame),
                ("perf", app._handle_perf_protocol_frame),
                ("trace", app._handle_trace_protocol_frame),
                ("section_list", app._handle_section_list_protocol_frame),
                ("parameter_wave", app._handle_parameter_wave_protocol_frame),
            ),
            transport_supplier=lambda: app.connected_transport,
            logger=app.logger,
        )


class ProtocolControllerHub:
    """Owns application-level protocol dispatch order.

    The communication layer routes complete frames here. Each feature controller
    keeps one protocol responsibility, while the main Tk app remains the
    composition root for widgets, services, and shared scheduling.
    """

    def __init__(self, app=None, *, ports: ProtocolControllerPorts | None = None) -> None:
        if ports is None:
            if app is None:
                raise ValueError("app or ports must be provided")
            ports = ProtocolControllerPorts.from_legacy_app(app)
        self._ports = ports
        self._home_controller = FeatureProtocolController("home", ports.home_handler)
        self._controllers = [FeatureProtocolController(name, handler) for name, handler in ports.feature_handlers]

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
        if self._ports.transport_supplier() == "can":
            self._ports.logger.log(
                "PARAM",
                f"unhandled frame on CAN cmd_set=0x{frame.cmd_set:02X} cmd_word=0x{frame.cmd_word:02X} "
                f"is_ack={frame.is_ack} len={len(frame.payload)} payload={frame.payload.hex(' ').upper()}",
            )
            return True
        return False
