from __future__ import annotations

import serial

from serial_debug_assistant.comm.protocol_parser import ProtocolParser
from serial_debug_assistant.comm.protocol_router import ProtocolRouter
from serial_debug_assistant.comm.protocol_sender import ProtocolSender
from serial_debug_assistant.data_pool import RuntimeStatePool
from serial_debug_assistant.framework import ProtocolRuntime, RxProcessResult
from serial_debug_assistant.platform import TransportBinding, TransportRegistry
from serial_debug_assistant.services.can_service import CANService
from serial_debug_assistant.services.ethernet_service import EthernetService
from serial_debug_assistant.services.serial_service import SerialService


class CommunicationManager:
    """Compatibility facade over data-pool, framework, and platform layers."""

    def __init__(
        self,
        *,
        serial_service: SerialService,
        can_service: CANService,
        ethernet_service: EthernetService,
        logger=None,
    ) -> None:
        self.serial_service = serial_service
        self.can_service = can_service
        self.ethernet_service = ethernet_service
        self.logger = logger
        self._state_pool = RuntimeStatePool()
        self._state = self._state_pool.business
        self._state_exchange = self._state_pool.exchange
        self._transports = TransportRegistry()
        self._transports.register(TransportBinding("serial", serial_service, serial_service.write))
        self._transports.register(TransportBinding("demo", serial_service, serial_service.write))
        self._transports.register(TransportBinding("can", can_service, can_service.send_bytes))
        self._transports.register(TransportBinding("ethernet", ethernet_service, ethernet_service.write))
        self._protocol = ProtocolRuntime(self.write_bytes, logger=logger)

        # Preserve the established backend facade consumed by the unchanged UI.
        self.parser: ProtocolParser = self._protocol.parser
        self.router: ProtocolRouter = self._protocol.router
        self.sender: ProtocolSender = self._protocol.sender

    @property
    def connected_transport(self) -> str | None:
        return self._state.connection().transport

    @property
    def endpoint(self) -> str | None:
        return self._state.connection().endpoint

    def set_frame_logger(self, frame_logger) -> None:
        self._protocol.set_frame_logger(frame_logger)

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
        self._state_exchange.publish_connection(transport="serial", endpoint=port)
        self._protocol.reset()
        self._log("COMM", f"open serial endpoint={port} baud={baudrate}")

    def configure_serial(
        self,
        *,
        baudrate: int,
        data_bits: str,
        parity: str,
        stop_bits: str,
    ) -> None:
        if self.connected_transport != "serial":
            raise RuntimeError("Serial transport is not open.")
        self.serial_service.configure(
            baudrate=baudrate,
            data_bits=data_bits,
            parity=parity,
            stop_bits=stop_bits,
        )
        self._log(
            "COMM",
            f"configure serial endpoint={self.endpoint} baud={baudrate} "
            f"data_bits={data_bits} parity={parity} stop_bits={stop_bits}",
        )

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
        self._state_exchange.publish_connection(transport="can", endpoint=channel)
        self._protocol.reset()
        self._log("COMM", f"open can interface={interface} channel={channel} bitrate={bitrate} tx=0x100 rx=0x101")

    def open_ethernet(self, *, host: str, port: int, error_callback) -> None:
        self.close()
        self.ethernet_service.open(host=host, port=port)
        self.ethernet_service.start_reader(error_callback=error_callback)
        endpoint = f"{host}:{port}"
        self._state_exchange.publish_connection(transport="ethernet", endpoint=endpoint)
        self._protocol.reset()
        self._log("COMM", f"open ethernet endpoint={self.endpoint} protocol=tcp")

    def enable_demo(self) -> None:
        self.close()
        self.serial_service.enable_demo_connection()
        self._state_exchange.publish_connection(transport="demo", endpoint="DEMO")
        self._protocol.reset()
        self._log("COMM", "open demo")

    def disable_demo(self) -> None:
        self.serial_service.disable_demo_connection()
        if self.connected_transport == "demo":
            self._state_exchange.clear_connection()
        self._protocol.reset()
        self._log("COMM", "close demo")

    def close(self) -> None:
        transport = self.connected_transport
        self._transports.close_all()
        self._state_exchange.clear_connection()
        self._protocol.reset()
        if transport is not None:
            self._log("COMM", f"close {transport}")

    def is_open(self) -> bool:
        service = self.active_service()
        return bool(service and service.is_open())

    def protocol_available(self) -> bool:
        binding = self._transports.get(self.connected_transport)
        return bool(binding and binding.protocol_enabled)

    def active_service(self):
        binding = self._transports.get(self.connected_transport)
        return None if binding is None else binding.service

    def write_bytes(self, payload: bytes) -> int:
        return self._transports.require(self.connected_transport).write(payload)

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
        raw_chunk_handler=None,
    ) -> RxProcessResult:
        return self._protocol.process_rx(
            service=self.active_service(),
            transport=self.connected_transport,
            protocol_available=self.protocol_available(),
            max_chunks=max_chunks,
            max_bytes=max_bytes,
            raw_chunk_handler=raw_chunk_handler,
        )

    def _log(self, category: str, message: str) -> None:
        if self.logger is not None:
            self.logger.log(category, message)
