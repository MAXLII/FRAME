from __future__ import annotations

import queue
import re
import threading
import time

from serial_debug_assistant.models import SerialChunk


CAN_FRAME_RE = re.compile(
    r"^\s*(?P<arbitration_id>[0-9A-Fa-f]{1,8})\s*#\s*(?:(?P<remote>[Rr])\s*(?P<dlc>\d{0,2})|(?P<data>[0-9A-Fa-f][0-9A-Fa-f\s,]*))\s*$"
)


class CANService:
    def __init__(self) -> None:
        self.bus = None
        self.reader_thread: threading.Thread | None = None
        self.reader_stop = threading.Event()
        self.rx_queue: queue.Queue[SerialChunk] = queue.Queue()
        self.tx_arbitration_id = 0x100
        self.tx_is_extended_id = False
        self.rx_arbitration_id = 0x101
        self.rx_is_extended_id = False

    def list_common_channels(self, interface: str) -> list[str]:
        interface_key = interface.lower().strip()
        if interface_key == "pcan":
            return [f"PCAN_USBBUS{i}" for i in range(1, 9)]
        if interface_key == "vector":
            return [f"0:{i}" for i in range(4)]
        if interface_key == "kvaser":
            return [str(i) for i in range(4)]
        if interface_key == "slcan":
            return [f"COM{i}" for i in range(1, 17)]
        if interface_key == "serial":
            return [f"COM{i}" for i in range(1, 17)]
        if interface_key == "socketcan":
            return ["can0", "can1", "vcan0"]
        if interface_key == "usb2can":
            return ["USB2CAN"]
        return []

    def open(self, *, interface: str, channel: str, bitrate: int) -> None:
        try:
            import can
        except ImportError as exc:
            raise RuntimeError("python-can is not installed. Please install dependencies again.") from exc

        self.close()
        interface_key = interface.lower().strip()
        channel = channel.strip()
        kwargs = {
            "interface": interface_key,
            "channel": channel,
            "bitrate": bitrate,
        }
        if interface_key in {"pcan", "vector", "kvaser", "usb2can", "socketcan"}:
            kwargs["receive_own_messages"] = False

        try:
            self.bus = can.Bus(**kwargs)
        except Exception as exc:
            self.bus = None
            self.reader_stop.set()
            message = f"CAN open failed ({interface_key}/{channel}, {bitrate}): {exc}"
            if interface_key == "pcan":
                message += " | Close PCAN-View or other tools using this channel, then unplug/replug PCAN-USB if needed."
            raise RuntimeError(message) from exc

        self.reader_stop.clear()

    def configure_tx_arbitration(self, arbitration_id: int, *, is_extended_id: bool = False) -> None:
        self.tx_arbitration_id = arbitration_id
        self.tx_is_extended_id = is_extended_id

    def configure_rx_filter(self, arbitration_id: int, *, is_extended_id: bool = False) -> None:
        self.rx_arbitration_id = arbitration_id
        self.rx_is_extended_id = is_extended_id

    def start_reader(self, *, error_callback) -> None:
        self.reader_thread = threading.Thread(
            target=self._reader_loop,
            kwargs={"error_callback": error_callback},
            daemon=True,
        )
        self.reader_thread.start()

    def _reader_loop(self, *, error_callback) -> None:
        bus = self.bus
        while not self.reader_stop.is_set() and bus is not None:
            try:
                message = bus.recv(timeout=0.1)
            except Exception as exc:
                if self.reader_stop.is_set():
                    break
                error_callback(str(exc))
                break

            if message is None:
                continue
            if bool(getattr(message, "is_remote_frame", False)):
                continue
            if int(getattr(message, "arbitration_id", -1)) != self.rx_arbitration_id:
                continue
            if bool(getattr(message, "is_extended_id", False)) != self.rx_is_extended_id:
                continue
            payload = bytes(getattr(message, "data", b""))
            if not payload:
                continue
            self.rx_queue.put(
                SerialChunk(
                    timestamp=getattr(message, "timestamp", time.time()) or time.time(),
                    data=payload,
                )
            )

    def close(self) -> None:
        self.reader_stop.set()
        bus = self.bus
        self.bus = None
        if bus is not None:
            try:
                bus.shutdown()
            except Exception:
                pass
        reader_thread = self.reader_thread
        self.reader_thread = None
        if reader_thread is not None and reader_thread.is_alive() and reader_thread is not threading.current_thread():
            reader_thread.join(timeout=0.5)

    def is_open(self) -> bool:
        return self.bus is not None

    def send_text_frames(self, raw_text: str) -> int:
        try:
            import can
        except ImportError as exc:
            raise RuntimeError("python-can is not installed. Please install dependencies again.") from exc

        if self.bus is None:
            raise RuntimeError("CAN bus is not open.")

        total_payload_bytes = 0
        frame_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if not frame_lines:
            return 0

        for line in frame_lines:
            message = self._parse_frame_text(line, can.Message)
            self.bus.send(message)
            total_payload_bytes += len(message.data)
        return total_payload_bytes

    def send_bytes(self, payload: bytes) -> int:
        try:
            import can
        except ImportError as exc:
            raise RuntimeError("python-can is not installed. Please install dependencies again.") from exc

        if self.bus is None:
            raise RuntimeError("CAN bus is not open.")

        if not payload:
            return 0

        sent_bytes = 0
        for offset in range(0, len(payload), 8):
            chunk = payload[offset : offset + 8]
            if len(chunk) < 8:
                chunk = chunk + (b"\xFF" * (8 - len(chunk)))
            message = can.Message(
                arbitration_id=self.tx_arbitration_id,
                is_extended_id=self.tx_is_extended_id,
                data=chunk,
            )
            self.bus.send(message)
            sent_bytes += len(chunk)
        return sent_bytes

    def _parse_frame_text(self, line: str, message_type):
        match = CAN_FRAME_RE.match(line)
        if not match:
            raise ValueError("CAN send format is invalid. Example: 123#11223344 or 18FF50E5#11 22 33 44")

        arbitration_id = int(match.group("arbitration_id"), 16)
        is_extended_id = arbitration_id > 0x7FF
        remote_flag = match.group("remote")
        if remote_flag:
            dlc_text = (match.group("dlc") or "").strip()
            dlc = int(dlc_text) if dlc_text else 0
            if dlc < 0 or dlc > 8:
                raise ValueError("CAN remote frame DLC must be between 0 and 8.")
            return message_type(
                arbitration_id=arbitration_id,
                is_extended_id=is_extended_id,
                is_remote_frame=True,
                dlc=dlc,
            )

        data_text = (match.group("data") or "").replace(" ", "").replace(",", "")
        if len(data_text) % 2 != 0:
            raise ValueError("CAN data bytes must contain an even number of hex digits.")
        payload = bytes.fromhex(data_text) if data_text else b""
        if len(payload) > 8:
            raise ValueError("Only classic CAN frames up to 8 bytes are supported right now.")
        return message_type(
            arbitration_id=arbitration_id,
            is_extended_id=is_extended_id,
            data=payload,
        )

    def _format_message(self, message) -> str:
        arbitration_id = int(getattr(message, "arbitration_id", 0))
        is_extended_id = bool(getattr(message, "is_extended_id", False))
        is_remote_frame = bool(getattr(message, "is_remote_frame", False))
        prefix = f"{arbitration_id:08X}" if is_extended_id else f"{arbitration_id:03X}"
        if is_remote_frame:
            dlc = int(getattr(message, "dlc", 0))
            return f"{prefix}#R{dlc}\r\n"
        data = bytes(getattr(message, "data", b""))
        return f"{prefix}#{data.hex(' ').upper()}\r\n"
