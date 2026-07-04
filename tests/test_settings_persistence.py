import tempfile
import unittest
import json
from pathlib import Path

from serial_debug_assistant.app_config import save_config_section
from serial_debug_assistant.ui.settings_persistence import load_ui_settings, save_ui_settings


class SettingsPersistenceTest(unittest.TestCase):
    def test_saves_and_loads_supported_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ui_settings.json"

            save_ui_settings(
                path,
                {
                    "connection.baud": "921600",
                    "connection.recv_hex": True,
                    "scope.index": 3,
                    "scope.scale": 1.5,
                },
            )

            self.assertEqual(
                load_ui_settings(path),
                {
                    "connection.baud": "921600",
                    "connection.recv_hex": True,
                    "scope.index": 3,
                    "scope.scale": 1.5,
                },
            )

    def test_ignores_unsupported_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ui_settings.json"

            save_ui_settings(path, {"ok": "value", "bad": {"nested": "value"}})

            self.assertEqual(load_ui_settings(path), {"ok": "value"})

    def test_bad_json_loads_as_empty_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ui_settings.json"
            path.write_text("{bad json", encoding="utf-8")

            self.assertEqual(load_ui_settings(path), {})

    def test_saves_ui_settings_inside_shared_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "frame_config.json"
            save_config_section(path, "jlink", {"target_history": ["GD32G553RET6"]})

            save_ui_settings(path, {"connection.baud": "921600"})

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["jlink"], {"target_history": ["GD32G553RET6"]})
            self.assertEqual(data["ui_settings"]["values"], {"connection.baud": "921600"})

    def test_loads_legacy_ui_settings_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ui_settings.json"
            path.write_text(
                json.dumps({"version": 1, "values": {"connection.baud": "115200"}}),
                encoding="utf-8",
            )

            self.assertEqual(load_ui_settings(path), {"connection.baud": "115200"})


if __name__ == "__main__":
    unittest.main()
