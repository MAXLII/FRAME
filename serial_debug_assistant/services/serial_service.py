from __future__ import annotations

import queue
import threading
import time

import serial
import serial.tools.list_ports

from serial_debug_assistant.constants import BYTE_SIZES, PARITY_OPTIONS, STOP_BITS_OPTIONS
from serial_debug_assistant.models import SerialChunk


class SerialService:
    def __init__(self) -> None:
        self.serial_port: serial.Serial | None = None
        self.reader_thread: threading.Thread | None = None
        self.reader_stop = threading.Event()
        self.rx_queue: queue.Queue[SerialChunk] = queue.Queue()
        self.demo_connected = False

    def list_ports(self) -> list[str]:
        return [port.device for port in serial.tools.list_ports.comports()]

    def list_ports_with_details(self) -> list[dict[str, str]]:
        ports: list[dict[str, str]] = []
        for port in serial.tools.list_ports.comports():
            description = (port.description or "").strip()
            display = port.device if not description or description == "n/a" else f"{port.device} - {description}"
            ports.append(
                {
                    "device": port.device,
                    "description": description,
                    "display": display,
                }
            )
        return ports

    def open(
        self,
        *,
        port: str,
        baudrate: int,
        data_bits: str,
        parity: str,
        stop_bits: str,
    ) -> None:
        bytesize = BYTE_SIZES[data_bits]
        parity_value = PARITY_OPTIONS[parity]
        stopbits = STOP_BITS_OPTIONS[stop_bits]

        self.close()
        self.serial_port = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity_value,
            stopbits=stopbits,
            timeout=0.1,
        )

        self.reader_stop.clear()

    def configure(
        self,
        *,
        baudrate: int,
        data_bits: str,
        parity: str,
        stop_bits: str,
    ) -> None:
        if not self.serial_port or not self.serial_port.is_open:
            raise serial.SerialException("Serial port is not open.")
        self.serial_port.baudrate = baudrate
        self.serial_port.bytesize = BYTE_SIZES[data_bits]
        self.serial_port.parity = PARITY_OPTIONS[parity]
        self.serial_port.stopbits = STOP_BITS_OPTIONS[stop_bits]

    def start_reader(
        self,
        *,
        auto_break_enabled_supplier,
        break_ms_supplier,
        error_callback,
    ) -> None:
        self.reader_thread = threading.Thread(
            target=self._reader_loop,
            kwargs={
                "auto_break_enabled_supplier": auto_break_enabled_supplier,
                "break_ms_supplier": break_ms_supplier,
                "error_callback": error_callback,
            },
            daemon=True,
        )
        self.reader_thread.start()

    def _reader_loop(self, *, auto_break_enabled_supplier, break_ms_supplier, error_callback) -> None:
        last_chunk_time = 0.0
        serial_port = self.serial_port

        while not self.reader_stop.is_set() and serial_port:
            try:
                chunk = serial_port.read(serial_port.in_waiting or 1)
            except (serial.SerialException, OSError) as exc:
                if self.reader_stop.is_set():
                    break
                error_callback(str(exc))
                break

            if not chunk:
                continue

            now = time.time()
            if auto_break_enabled_supplier():
                gap_ms = break_ms_supplier()
                if last_chunk_time and (now - last_chunk_time) * 1000.0 >= gap_ms:
                    self.rx_queue.put(SerialChunk(timestamp=now, data=b"\n", synthetic=True))

            self.rx_queue.put(SerialChunk(timestamp=now, data=chunk))
            last_chunk_time = now

    def close(self) -> None:
        self.reader_stop.set()
        serial_port = self.serial_port
        self.serial_port = None
        if serial_port:
            try:
                if serial_port.is_open:
                    serial_port.close()
            except serial.SerialException:
                pass
        reader_thread = self.reader_thread
        self.reader_thread = None
        if reader_thread is not None and reader_thread.is_alive() and reader_thread is not threading.current_thread():
            reader_thread.join(timeout=0.5)
        self.demo_connected = False

    def is_open(self) -> bool:
        return self.demo_connected or bool(self.serial_port and self.serial_port.is_open)

    def write(self, payload: bytes) -> int:
        if self.demo_connected:
            return len(payload)
        if not self.serial_port or not self.serial_port.is_open:
            raise serial.SerialException("Serial port is not open.")
        return self.serial_port.write(payload)

    def enable_demo_connection(self) -> None:
        self.reader_stop.clear()
        self.demo_connected = True

    def disable_demo_connection(self) -> None:
        self.demo_connected = False
