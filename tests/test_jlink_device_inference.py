import tempfile
import unittest
from pathlib import Path

from serial_debug_assistant.jlink_debug import (
    DebugVariable,
    JLinkDebugError,
    _encode_write_value,
    _normalize_mcu_type_name,
    _symbol_names_from_variables,
    _validate_ram_write,
    infer_jlink_device,
    infer_jlink_device_from_text,
)
from serial_debug_assistant.ui.jlink_debug_tab import _expression_parts, _variable_matches_search


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

    def test_search_ignores_struct_member_names(self) -> None:
        variable = DebugVariable(
            "task.period",
            0x20000000,
            4,
            ".bss",
            "demo.elf",
            type_name="uint32_t",
            parent_types=(("task", "reg_task_t"),),
        )

        self.assertTrue(_variable_matches_search(variable, "task"))
        self.assertTrue(_variable_matches_search(variable, "reg_task"))
        self.assertFalse(_variable_matches_search(variable, "period"))

    def test_rejects_flash_write_range(self) -> None:
        with self.assertRaises(JLinkDebugError):
            _validate_ram_write(0x08000000, 4)

    def test_allows_ram_write_range(self) -> None:
        _validate_ram_write(0x20000000, 4)

    def test_encodes_integer_write_value(self) -> None:
        variable = DebugVariable("counter", 0x20000000, 4, ".bss", "demo.elf", type_name="uint32_t")

        self.assertEqual(_encode_write_value(variable, "0x12345678"), bytes.fromhex("78 56 34 12"))

    def test_encodes_float_write_value(self) -> None:
        variable = DebugVariable("gain", 0x20000000, 4, ".bss", "demo.elf", type_name="float")

        self.assertEqual(_encode_write_value(variable, "1.0"), bytes.fromhex("00 00 80 3F"))

    def test_prefixed_hex_write_takes_priority_over_float_type(self) -> None:
        variable = DebugVariable("gain", 0x20000000, 4, ".bss", "demo.elf", type_name="float")

        self.assertEqual(_encode_write_value(variable, "0x3F800000"), bytes.fromhex("00 00 80 3F"))

    def test_normalizes_32_bit_mcu_integer_type_names(self) -> None:
        cases = {
            "signed char": "int8_t",
            "unsigned char": "uint8_t",
            "signed short": "int16_t",
            "unsigned short": "uint16_t",
            "signed int": "int32_t",
            "unsigned int": "uint32_t",
            "long int": "int32_t",
            "long unsigned int": "uint32_t",
            "signed long long": "int64_t",
            "unsigned long long": "uint64_t",
            "long unsigned int *": "uint32_t *",
            "char *": "char *",
        }

        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(_normalize_mcu_type_name(source), expected)

    def test_encodes_raw_hex_write_value(self) -> None:
        variable = DebugVariable("buffer", 0x20000000, 4, ".bss", "demo.elf", type_name="uint8_t[]")

        self.assertEqual(_encode_write_value(variable, "hex: 01 02 03 04"), bytes.fromhex("01 02 03 04"))

    def test_symbol_names_prefer_struct_parent_name(self) -> None:
        symbols = _symbol_names_from_variables(
            [
                DebugVariable(
                    "task.t_period",
                    0x20001000,
                    4,
                    ".bss",
                    "demo.elf",
                    type_name="uint32_t",
                    parent_types=(("task", "reg_task_t"),),
                ),
                DebugVariable(
                    "task.p_next",
                    0x20001018,
                    4,
                    ".bss",
                    "demo.elf",
                    type_name="reg_task_t *",
                    parent_types=(("task", "reg_task_t"),),
                ),
            ]
        )

        self.assertEqual(symbols[0x20001000], "task")


if __name__ == "__main__":
    unittest.main()
