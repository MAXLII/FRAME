import tempfile
import unittest
from pathlib import Path

from serial_debug_assistant.jlink_debug import infer_jlink_device, infer_jlink_device_from_text
from serial_debug_assistant.ui.jlink_debug_tab import _expression_parts


class JLinkDeviceInferenceTest(unittest.TestCase):
    def test_infers_device_from_file_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "gd32g553rct6_app.map"
            map_path.write_text("", encoding="utf-8")

            self.assertEqual(infer_jlink_device(elf_path=None, map_path=map_path), "GD32G553RCT6")

    def test_infers_device_from_map_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "app.map"
            map_path.write_text("LOAD startup_hc32f334k8ta.o\n.text 0x08000000\n", encoding="utf-8")

            self.assertEqual(infer_jlink_device(elf_path=None, map_path=map_path), "HC32F334K8TA")

    def test_infers_device_from_elf_strings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            elf_path = Path(temp_dir) / "app.elf"
            elf_path.write_bytes(b"\x7fELF\x00linker STM32F407VE_FLASH.ld\x00")

            self.assertEqual(infer_jlink_device(elf_path=elf_path, map_path=None), "STM32F407VE")

    def test_infers_device_from_jlink_output(self) -> None:
        output = 'Device "GD32G553RCT6" selected.\nConnecting to target via SWD\n'

        self.assertEqual(infer_jlink_device_from_text(output), "GD32G553RCT6")

    def test_expression_parts_keep_array_dimensions_nested(self) -> None:
        self.assertEqual(
            _expression_parts("scope.matrix[0][1].value"),
            ["scope", "matrix", "[0]", "[1]", "value"],
        )


if __name__ == "__main__":
    unittest.main()
