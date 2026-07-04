import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
