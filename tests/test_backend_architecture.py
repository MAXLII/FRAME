import queue
import unittest
from dataclasses import FrozenInstanceError

from serial_debug_assistant.comm import CommunicationManager
from serial_debug_assistant.controllers import ProtocolControllerHub, ProtocolControllerPorts
from serial_debug_assistant.data_pool import RuntimeStatePool
from serial_debug_assistant.models import ProtocolFrame, SerialChunk
from serial_debug_assistant.protocol import build_frame


class FakeByteService:
    def __init__(self) -> None:
        self.rx_queue: queue.Queue[SerialChunk] = queue.Queue()
        self.opened = False
        self.closed = 0
        self.writes: list[bytes] = []

    def close(self) -> None:
        self.opened = False
        self.closed += 1

    def is_open(self) -> bool:
        return self.opened

    def write(self, payload: bytes) -> int:
        self.writes.append(payload)
        return len(payload)


class FakeSerialService(FakeByteService):
    def open(self, **_kwargs) -> None:
        self.opened = True

    def start_reader(self, **_kwargs) -> None:
        pass

    def configure(self, **_kwargs) -> None:
        pass

    def enable_demo_connection(self) -> None:
        self.opened = True

    def disable_demo_connection(self) -> None:
        self.opened = False


class FakeCanService(FakeByteService):
    def open(self, **_kwargs) -> None:
        self.opened = True

    def configure_tx_arbitration(self, *_args, **_kwargs) -> None:
        pass

    def configure_rx_filter(self, *_args, **_kwargs) -> None:
        pass

    def start_reader(self, **_kwargs) -> None:
        pass

    def send_bytes(self, payload: bytes) -> int:
        return self.write(payload)


class FakeEthernetService(FakeByteService):
    def open(self, **_kwargs) -> None:
        self.opened = True

    def start_reader(self, **_kwargs) -> None:
        pass


class FakeLogger:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def log(self, category: str, message: str) -> None:
        self.entries.append((category, message))


def make_manager() -> tuple[CommunicationManager, FakeSerialService, FakeCanService, FakeEthernetService]:
    serial = FakeSerialService()
    can = FakeCanService()
    ethernet = FakeEthernetService()
    manager = CommunicationManager(
        serial_service=serial,
        can_service=can,
        ethernet_service=ethernet,
        logger=FakeLogger(),
    )
    return manager, serial, can, ethernet


class RuntimeStatePoolTest(unittest.TestCase):
    def test_business_and_exchange_interfaces_share_one_private_snapshot(self) -> None:
        pool = RuntimeStatePool()
        initial = pool.business.connection()
        published = pool.exchange.publish_connection(transport="ethernet", endpoint="192.0.2.10:5000")

        self.assertFalse(initial.connected)
        self.assertEqual(pool.business.connection(), published)
        self.assertTrue(published.connected)
        with self.assertRaises(FrozenInstanceError):
            published.transport = "serial"  # type: ignore[misc]

        cleared = pool.exchange.clear_connection()
        self.assertFalse(cleared.connected)
        self.assertEqual(cleared.revision, published.revision + 1)


class CommunicationManagerArchitectureTest(unittest.TestCase):
    def test_registry_selects_platform_writer_and_publishes_connection_state(self) -> None:
        manager, _serial, can, _ethernet = make_manager()

        manager.open_can(interface="virtual", channel="0", bitrate=500_000, error_callback=lambda _error: None)
        sent = manager.write_bytes(b"abc")

        self.assertEqual(sent, 3)
        self.assertEqual(can.writes, [b"abc"])
        self.assertEqual(manager.connected_transport, "can")
        self.assertEqual(manager.endpoint, "0")

    def test_protocol_framework_parses_and_routes_active_transport_bytes(self) -> None:
        manager, serial, _can, _ethernet = make_manager()
        received: list[ProtocolFrame] = []
        manager.router.register(lambda frame: received.append(frame) or True, cmd_set=0x02, cmd_word=0x01)
        manager.enable_demo()
        _sent, _outbound = manager.send_protocol(dst=0x02, d_dst=0, cmd_set=0x02, cmd_word=0x01)
        encoded = build_frame(dst=0x01, d_dst=0, src=0x02, cmd_set=0x02, cmd_word=0x01, is_ack=1)
        serial.rx_queue.put(SerialChunk(timestamp=1.0, data=encoded))

        result = manager.process_rx(max_chunks=4, max_bytes=4096)

        self.assertEqual(result.processed_chunks, 1)
        self.assertEqual([(frame.cmd_set, frame.cmd_word) for frame in received], [(0x02, 0x01)])

    def test_close_closes_shared_demo_service_only_once(self) -> None:
        manager, serial, can, ethernet = make_manager()
        manager.enable_demo()
        closed_before = (serial.closed, can.closed, ethernet.closed)

        manager.close()

        self.assertEqual(serial.closed, closed_before[0] + 1)
        self.assertEqual(can.closed, closed_before[1] + 1)
        self.assertEqual(ethernet.closed, closed_before[2] + 1)
        self.assertIsNone(manager.connected_transport)


class ProtocolControllerPortsTest(unittest.TestCase):
    def test_hub_accepts_narrow_business_ports_without_ui_object(self) -> None:
        calls: list[str] = []
        logger = FakeLogger()
        ports = ProtocolControllerPorts(
            home_handler=lambda _frame: calls.append("home") or False,
            feature_handlers=(("feature", lambda _frame: calls.append("feature") or True),),
            transport_supplier=lambda: "serial",
            logger=logger,
        )
        frame = ProtocolFrame(0xE8, 1, 2, 0, 1, 0, 0x01, 0x01, 1, b"", 0)

        handled = ProtocolControllerHub(ports=ports).handle_frame(frame)

        self.assertTrue(handled)
        self.assertEqual(calls, ["home", "feature"])


if __name__ == "__main__":
    unittest.main()
