from __future__ import annotations

import struct
import unittest

from serial_debug_assistant.firmware_update import (
    UPDATE_PACKET_SIZE,
    build_update_info_payload,
    build_update_packet_payload,
    default_upgrade_target,
)
from serial_debug_assistant.models import FirmwareFooter, FirmwareImage
from serial_debug_assistant.protocol import crc16_ccitt


class FirmwareUpdateTest(unittest.TestCase):
    @staticmethod
    def _image(module_id: int, data: bytes = b"firmware") -> FirmwareImage:
        return FirmwareImage(
            path="firmware.bin",
            data=data,
            footer=FirmwareFooter(
                unix_time=0,
                fw_type=1,
                version=0x01020304,
                file_size=len(data),
                commit_id="test",
                module_id=module_id,
                crc32=0,
            ),
            footer_crc_ok=True,
            payload_crc16=crc16_ccitt(data),
            warnings=[],
        )

    def test_default_target_is_firmware_owner(self) -> None:
        self.assertEqual(default_upgrade_target(self._image(0x02)), 0x02)
        self.assertEqual(default_upgrade_target(self._image(0x03)), 0x03)

    def test_update_info_keeps_target_module_id(self) -> None:
        image = self._image(0x03)
        module_id, version, length, update_type = struct.unpack(
            "<BIIB", build_update_info_payload(image, 1)
        )
        self.assertEqual(module_id, 0x03)
        self.assertEqual(version, image.footer.version)
        self.assertEqual(length, len(image.data))
        self.assertEqual(update_type, 1)

    def test_packet_uses_fixed_envelope_and_valid_crc(self) -> None:
        image = self._image(0x03, b"abc")
        packet = build_update_packet_payload(image, 0)
        self.assertEqual(len(packet), 4 + 1 + 2 + UPDATE_PACKET_SIZE + 2)
        self.assertEqual(packet[4], 0x03)
        self.assertEqual(int.from_bytes(packet[5:7], "little"), 3)
        self.assertEqual(packet[7:10], b"abc")
        self.assertEqual(packet[10 : 7 + UPDATE_PACKET_SIZE], b"\xFF" * (UPDATE_PACKET_SIZE - 3))
        self.assertEqual(int.from_bytes(packet[-2:], "little"), crc16_ccitt(packet[:-2]))


if __name__ == "__main__":
    unittest.main()
