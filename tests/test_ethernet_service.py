from __future__ import annotations

import queue
import socket
import threading

from serial_debug_assistant.services.ethernet_service import EthernetService


def test_ethernet_service_exchanges_unmodified_bytes() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    received = queue.Queue[bytes]()
    release_server = threading.Event()

    def server() -> None:
        connection, _address = listener.accept()
        with connection:
            received.put(connection.recv(64))
            connection.sendall(b"\xE8\x01\x23\x45")
            release_server.wait(timeout=1.0)

    server_thread = threading.Thread(target=server, daemon=True)
    server_thread.start()

    errors: list[str] = []
    service = EthernetService()
    try:
        service.open(host="127.0.0.1", port=port)
        service.start_reader(error_callback=errors.append)
        assert service.write(b"\xE8\xAA\x55") == 3
        assert received.get(timeout=1.0) == b"\xE8\xAA\x55"
        assert service.rx_queue.get(timeout=1.0).data == b"\xE8\x01\x23\x45"
    finally:
        service.close()
        release_server.set()
        listener.close()
        server_thread.join(timeout=1.0)

    assert not errors
