from __future__ import annotations

import sys
import threading
import time
import types

import pytest

from serial_debug_assistant.services.can_service import CANService, CAN_SEND_TIMEOUT_SECONDS


class FakeMessage:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)
        self.data = kwargs.get("data", b"")


class FailingReceiveBus:
    def __init__(self) -> None:
        self.receive_calls = 0

    def recv(self, *, timeout: float):
        self.receive_calls += 1
        raise RuntimeError("CAN receive failed")


class RecordingSendBus:
    def __init__(self) -> None:
        self.calls = []

    def send(self, message, *, timeout: float) -> None:
        self.calls.append((message, timeout))


class FailingSendBus:
    def send(self, message, *, timeout: float) -> None:
        raise OSError("adapter offline")


def test_reader_keeps_running_after_receive_error() -> None:
    service = CANService()
    bus = FailingReceiveBus()
    service.bus = bus
    errors = []
    reader = threading.Thread(target=service._reader_loop, kwargs={"error_callback": errors.append})

    reader.start()
    deadline = time.monotonic() + 0.5
    while bus.receive_calls < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    service.reader_stop.set()
    reader.join(timeout=0.5)

    assert bus.receive_calls >= 2
    assert errors == ["CAN receive failed"]
    assert service.bus is bus


@pytest.mark.parametrize("send_method,payload", [("send_bytes", b"12345678"), ("send_text_frames", "123#0102")])
def test_send_uses_bounded_timeout(monkeypatch, send_method: str, payload) -> None:
    fake_can = types.SimpleNamespace(Message=FakeMessage)
    monkeypatch.setitem(sys.modules, "can", fake_can)
    service = CANService()
    bus = RecordingSendBus()
    service.bus = bus

    getattr(service, send_method)(payload)

    assert len(bus.calls) == 1
    assert bus.calls[0][1] == CAN_SEND_TIMEOUT_SECONDS


def test_send_error_is_normalized_without_closing_bus(monkeypatch) -> None:
    fake_can = types.SimpleNamespace(Message=FakeMessage)
    monkeypatch.setitem(sys.modules, "can", fake_can)
    service = CANService()
    bus = FailingSendBus()
    service.bus = bus

    with pytest.raises(RuntimeError, match="CAN send failed: adapter offline"):
        service.send_bytes(b"12345678")

    assert service.bus is bus
