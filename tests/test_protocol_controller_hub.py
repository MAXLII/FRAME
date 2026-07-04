import unittest

from serial_debug_assistant.controllers import ProtocolControllerHub
from serial_debug_assistant.models import ProtocolFrame


def make_frame(*, cmd_set: int, cmd_word: int = 0x01, is_ack: int = 1) -> ProtocolFrame:
    return ProtocolFrame(
        sop=0xE8,
        version=0x01,
        src=0x02,
        d_src=0x00,
        dst=0x01,
        d_dst=0x00,
        cmd_set=cmd_set,
        cmd_word=cmd_word,
        is_ack=is_ack,
        payload=b"",
        crc=0,
    )


class FakeLogger:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def log(self, category: str, message: str) -> None:
        self.entries.append((category, message))


class FakeApp:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.connected_transport = "serial"
        self.logger = FakeLogger()

    def _handle_home_protocol_frame(self, frame: ProtocolFrame) -> bool:
        self.calls.append("home")
        return frame.cmd_set == 0x02

    def _handle_upgrade_protocol_frame(self, frame: ProtocolFrame) -> bool:
        self.calls.append("upgrade")
        return False

    def _handle_factory_mode_protocol_frame(self, frame: ProtocolFrame) -> bool:
        self.calls.append("factory")
        return False

    def _handle_black_box_protocol_frame(self, frame: ProtocolFrame) -> bool:
        self.calls.append("black_box")
        return False

    def _handle_scope_protocol_frame(self, frame: ProtocolFrame) -> bool:
        self.calls.append("scope")
        return False

    def _handle_sfra_protocol_frame(self, frame: ProtocolFrame) -> bool:
        self.calls.append("sfra")
        return False

    def _handle_perf_protocol_frame(self, frame: ProtocolFrame) -> bool:
        self.calls.append("perf")
        return False

    def _handle_trace_protocol_frame(self, frame: ProtocolFrame) -> bool:
        self.calls.append("trace")
        return False

    def _handle_parameter_wave_protocol_frame(self, frame: ProtocolFrame) -> bool:
        self.calls.append("parameter_wave")
        return True


class ProtocolControllerHubTest(unittest.TestCase):
    def test_home_frame_is_handled_before_common_cmd_set(self) -> None:
        app = FakeApp()
        handled = ProtocolControllerHub(app).handle_frame(make_frame(cmd_set=0x02))

        self.assertTrue(handled)
        self.assertEqual(app.calls, ["home"])

    def test_non_common_cmd_set_does_not_enter_feature_controllers(self) -> None:
        app = FakeApp()
        handled = ProtocolControllerHub(app).handle_frame(make_frame(cmd_set=0x03))

        self.assertFalse(handled)
        self.assertEqual(app.calls, ["home"])

    def test_common_cmd_set_runs_feature_controllers_in_order(self) -> None:
        app = FakeApp()
        handled = ProtocolControllerHub(app).handle_frame(make_frame(cmd_set=0x01))

        self.assertTrue(handled)
        self.assertEqual(
            app.calls,
            ["home", "upgrade", "factory", "black_box", "scope", "sfra", "perf", "trace", "parameter_wave"],
        )


if __name__ == "__main__":
    unittest.main()
