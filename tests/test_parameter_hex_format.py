import unittest

from serial_debug_assistant.ui.parameter_tab import format_hex_value


class ParameterHexFormatTest(unittest.TestCase):
    def test_signed_integer_uses_twos_complement_width(self) -> None:
        self.assertEqual(format_hex_value(0xFFFFFFFF, 0), "0xFF")
        self.assertEqual(format_hex_value(0xFFFFFFFF, 2), "0xFFFF")
        self.assertEqual(format_hex_value(0xFFFFFFFF, 4), "0xFFFFFFFF")

    def test_unsigned_integer_uses_type_width(self) -> None:
        self.assertEqual(format_hex_value(0x1234, 1), "0x34")
        self.assertEqual(format_hex_value(0x1234, 3), "0x1234")
        self.assertEqual(format_hex_value(0x1234, 5), "0x00001234")

    def test_non_integer_type_has_no_hex_display(self) -> None:
        self.assertEqual(format_hex_value(0, 6), "/")
        self.assertEqual(format_hex_value(0, 7), "/")


if __name__ == "__main__":
    unittest.main()
