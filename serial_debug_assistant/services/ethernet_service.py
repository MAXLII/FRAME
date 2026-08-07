from __future__ import annotations

import queue
import socket
import threading
import time

from serial_debug_assistant.models import SerialChunk


class EthernetService:
    """TCP byte-stream transport used by FRAME protocol services."""

    def __init__(self) -> None:
        self.socket: socket.socket | None = None
        self.reader_thread: threading.Thread | None = None
        self.reader_stop = threading.Event()
        self.rx_queue: queue.Queue[SerialChunk] = queue.Queue()
        self._write_lock = threading.Lock()

    def open(self, *, host: str, port: int, connect_timeout: float = 3.0) -> None:
        endpoint_host = host.strip()
        if not endpoint_host:
            raise ValueError("Ethernet host is required.")
        if not 1 <= port <= 65535:
            raise ValueError("Ethernet port must be between 1 and 65535.")

        self.close()
        tcp_socket = socket.create_connection((endpoint_host, port), timeout=connect_timeout)
        tcp_socket.settimeout(0.2)
        tcp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket = tcp_socket
        self.reader_stop.clear()

    def start_reader(self, *, error_callback) -> None:
        if self.socket is None:
            raise RuntimeError("Ethernet transport is not open.")
        self.reader_thread = threading.Thread(
            target=self._reader_loop,
            kwargs={"error_callback": error_callback},
            daemon=True,
        )
        self.reader_thread.start()

    def _reader_loop(self, *, error_callback) -> None:
        tcp_socket = self.socket
        while not self.reader_stop.is_set() and tcp_socket is not None:
            try:
                chunk = tcp_socket.recv(65536)
            except socket.timeout:
                continue
            except OSError as exc:
                if not self.reader_stop.is_set():
                    self.reader_stop.set()
                    error_callback(str(exc))
                break
            if not chunk:
                if not self.reader_stop.is_set():
                    self.reader_stop.set()
                    error_callback("The remote Ethernet endpoint closed the connection.")
                break
            self.rx_queue.put(SerialChunk(timestamp=time.time(), data=chunk))

    def close(self) -> None:
        self.reader_stop.set()
        tcp_socket = self.socket
        self.socket = None
        if tcp_socket is not None:
            try:
                tcp_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                tcp_socket.close()
            except OSError:
                pass
        reader_thread = self.reader_thread
        self.reader_thread = None
        if reader_thread is not None and reader_thread.is_alive() and reader_thread is not threading.current_thread():
            reader_thread.join(timeout=0.5)

    def is_open(self) -> bool:
        return self.socket is not None and not self.reader_stop.is_set()

    def write(self, payload: bytes) -> int:
        tcp_socket = self.socket
        if tcp_socket is None or self.reader_stop.is_set():
            raise RuntimeError("Ethernet transport is not open.")
        with self._write_lock:
            try:
                tcp_socket.sendall(payload)
            except OSError as exc:
                raise RuntimeError(f"Ethernet send failed: {exc}") from exc
        return len(payload)
