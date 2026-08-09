import struct
import tempfile
import unittest
from pathlib import Path

from serial_debug_assistant.section_list_protocol import (
    build_section_list_directory_query,
    build_section_list_node_query,
    parse_section_list_directory_ack,
    parse_section_list_node_ack,
)
from serial_debug_assistant.section_list_controller import SectionListController
from serial_debug_assistant.section_map import SectionMap
from serial_debug_assistant.models import ProtocolFrame
from serial_debug_assistant.protocol import FrameParser, build_frame


class SectionListProtocolTest(unittest.TestCase):
    def test_directory_round_trip_fields(self) -> None:
        self.assertEqual(build_section_list_directory_query(3), b"\x03\x00")
        payload = struct.pack("<BBHHHIB", 1, 0, 3, 4, 9, 2, 4) + b"task"
        item = parse_section_list_directory_ack(payload)
        self.assertEqual((item.directory_index, item.list_count, item.list_id), (3, 4, 9))
        self.assertEqual((item.node_count, item.name), (2, "task"))

    def test_node_round_trip_fields(self) -> None:
        self.assertEqual(build_section_list_node_query(2, 7), struct.pack("<HI", 2, 7))
        node = parse_section_list_node_ack(struct.pack("<BBHIII", 1, 0, 2, 7, 8, 0x08001235))
        self.assertEqual(node.address, 0x08001235)

    def test_map_resolves_exact_and_thumb_address(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "firmware.map"
            path.write_text(
                "    task_run                  0x08001234   Thumb Code  20  task.o(.text)\n"
                "    0x08003456   0x08003456   0x00000010   Code   RO   12   .text.control_run control.o\n"
                "    0x1fffe52c   COMPRESSED   0x00000008   Data   RW   458   .data.reg_init_demo demo.o\n"
                "0x08005678 T irq_run\n",
                encoding="utf-8",
            )
            symbols = SectionMap.load(path)
            self.assertEqual(symbols.resolve(0x08001234).name, "task_run")
            self.assertEqual(symbols.resolve(0x08001235).name, "task_run")
            self.assertEqual(symbols.resolve(0x08003457).name, "control_run")
            self.assertEqual(symbols.resolve(0x08005678).name, "irq_run")
            self.assertEqual(symbols.resolve(0x1FFFE52C).name, "reg_init_demo")

    def test_controller_reads_directory_then_selected_list(self) -> None:
        sent: list[dict[str, object]] = []
        directory_updates: list[list[object]] = []
        node_updates: list[tuple[object, list[object]]] = []
        statuses: list[tuple[str, bool]] = []
        controller = SectionListController(
            send=lambda **kwargs: sent.append(kwargs),
            schedule=lambda _delay, _callback: None,
            on_directory=lambda directory: directory_updates.append(directory),
            on_nodes=lambda entry, nodes, complete: node_updates.append((entry, nodes, complete)),
            on_status=lambda message, error: statuses.append((message, error)),
        )
        controller.refresh_directory(2, 0)
        self.assertEqual(sent[-1]["cmd_word"], 0x38)

        directory_payload = struct.pack("<BBHHHIB", 1, 0, 0, 1, 5, 1, 4) + b"task"
        controller.handle(self._frame(0x38, directory_payload))
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(directory_updates), 1)
        self.assertEqual(directory_updates[0][0].name, "task")
        self.assertEqual(statuses[-1], ("已读取 1 条链表，请选择后获取节点", False))

        controller.fetch_list(5, 2, 0)
        self.assertEqual(sent[-1]["cmd_word"], 0x39)
        self.assertEqual(sent[-1]["payload"], struct.pack("<HI", 5, 0))

        node_payload = struct.pack("<BBHIII", 1, 0, 5, 0, 1, 0x08001235)
        controller.handle(self._frame(0x39, node_payload))
        self.assertEqual(node_updates[-1][0].list_id, 5)
        self.assertEqual(node_updates[-1][1][0].address, 0x08001235)
        self.assertTrue(node_updates[-1][2])
        self.assertEqual(statuses[-1], ("已读取 task，共 1 个节点", False))

        controller.fetch_list(5, 2, 0)
        refreshed_payload = struct.pack("<BBHIII", 1, 0, 5, 0, 2, 0x08005679)
        controller.handle(self._frame(0x39, refreshed_payload))
        self.assertEqual(sent[-1]["payload"], struct.pack("<HI", 5, 1))
        self.assertFalse(node_updates[-1][2])
        refreshed_tail = struct.pack("<BBHIII", 1, 0, 5, 1, 2, 0x0800789B)
        controller.handle(self._frame(0x39, refreshed_tail))
        self.assertEqual(len(node_updates), 3)
        self.assertEqual(node_updates[-1][0].node_count, 2)
        self.assertEqual(node_updates[-1][1][0].address, 0x08005679)

    def test_controller_publishes_directory_only_after_complete(self) -> None:
        sent: list[dict[str, object]] = []
        directory_updates: list[list[object]] = []
        controller = SectionListController(
            send=lambda **kwargs: sent.append(kwargs),
            schedule=lambda _delay, _callback: None,
            on_directory=lambda directory: directory_updates.append(directory),
            on_nodes=lambda _entry, _nodes, _complete: None,
            on_status=lambda _message, _error: None,
        )
        controller.refresh_directory(2, 0)

        first = struct.pack("<BBHHHIB", 1, 0, 0, 2, 3, 17, 4) + b"init"
        controller.handle(self._frame(0x38, first))
        self.assertEqual(directory_updates, [])
        self.assertEqual(sent[-1]["payload"], b"\x01\x00")

        second = struct.pack("<BBHHHIB", 1, 0, 1, 2, 5, 24, 4) + b"task"
        controller.handle(self._frame(0x38, second))
        self.assertEqual(len(directory_updates), 1)
        self.assertEqual([item.name for item in directory_updates[0]], ["init", "task"])
        self.assertTrue(all(item["cmd_word"] == 0x38 for item in sent))

    def test_controller_timeout_tracks_directory_progress(self) -> None:
        scheduled: list[tuple[int, object]] = []
        statuses: list[tuple[str, bool]] = []
        directory_updates: list[list[object]] = []
        controller = SectionListController(
            send=lambda **_kwargs: None,
            schedule=lambda delay, callback: scheduled.append((delay, callback)),
            on_directory=lambda directory: directory_updates.append(directory),
            on_nodes=lambda _entry, _nodes, _complete: None,
            on_status=lambda message, error: statuses.append((message, error)),
        )
        controller.refresh_directory(2, 0)
        first_timeout = scheduled[-1]

        first = struct.pack("<BBHHHIB", 1, 0, 0, 2, 3, 17, 4) + b"init"
        controller.handle(self._frame(0x38, first))
        second_timeout = scheduled[-1]
        self.assertEqual(first_timeout[0], 1500)
        self.assertEqual(second_timeout[0], 1500)

        first_timeout[1]()
        self.assertNotEqual(statuses[-1], ("读取链表超时", True))

        second = struct.pack("<BBHHHIB", 1, 0, 1, 2, 5, 24, 4) + b"task"
        controller.handle(self._frame(0x38, second))
        second_timeout[1]()
        self.assertEqual([item.name for item in directory_updates[0]], ["init", "task"])
        self.assertEqual(statuses[-1], ("已读取 2 条链表，请选择后获取节点", False))

    def test_controller_latest_progress_timeout_still_fails(self) -> None:
        scheduled: list[tuple[int, object]] = []
        statuses: list[tuple[str, bool]] = []
        controller = SectionListController(
            send=lambda **_kwargs: None,
            schedule=lambda delay, callback: scheduled.append((delay, callback)),
            on_directory=lambda _directory: None,
            on_nodes=lambda _entry, _nodes, _complete: None,
            on_status=lambda message, error: statuses.append((message, error)),
        )
        controller.refresh_directory(2, 0)

        for _attempt in range(3):
            scheduled[-1][1]()

        self.assertEqual(statuses[-1], ("读取链表超时，已重试 2 次", True))

    def test_controller_ignores_stale_and_duplicate_node_responses(self) -> None:
        sent: list[dict[str, object]] = []
        statuses: list[tuple[str, bool]] = []
        node_updates: list[tuple[list[object], bool]] = []
        controller = SectionListController(
            send=lambda **kwargs: sent.append(kwargs),
            schedule=lambda _delay, _callback: None,
            on_directory=lambda _directory: None,
            on_nodes=lambda _entry, nodes, complete: node_updates.append((nodes, complete)),
            on_status=lambda message, error: statuses.append((message, error)),
        )
        controller.refresh_directory(2, 0)
        directory_payload = struct.pack("<BBHHHIB", 1, 0, 0, 1, 5, 3, 4) + b"task"
        controller.handle(self._frame(0x38, directory_payload))
        controller.fetch_list(5, 2, 0)

        stale_tail = struct.pack("<BBHIII", 1, 0, 5, 2, 3, 0x08000009)
        controller.handle(self._frame(0x39, stale_tail))
        self.assertEqual(sent[-1]["payload"], struct.pack("<HI", 5, 0))

        first = struct.pack("<BBHIII", 1, 0, 5, 0, 3, 0x08000001)
        controller.handle(self._frame(0x39, first))
        controller.handle(self._frame(0x39, first))
        self.assertEqual(sent[-1]["payload"], struct.pack("<HI", 5, 1))

        second = struct.pack("<BBHIII", 1, 0, 5, 1, 3, 0x08000005)
        third = struct.pack("<BBHIII", 1, 0, 5, 2, 3, 0x08000009)
        controller.handle(self._frame(0x39, second))
        controller.handle(self._frame(0x39, third))

        self.assertEqual(len(node_updates[-1][0]), 3)
        self.assertTrue(node_updates[-1][1])
        self.assertEqual(statuses[-1], ("已读取 task，共 3 个节点", False))
        self.assertFalse(any(error for _message, error in statuses))

    def test_controller_retries_a_lost_node_request(self) -> None:
        sent: list[dict[str, object]] = []
        scheduled: list[tuple[int, object]] = []
        statuses: list[tuple[str, bool]] = []
        controller = SectionListController(
            send=lambda **kwargs: sent.append(kwargs),
            schedule=lambda delay, callback: scheduled.append((delay, callback)),
            on_directory=lambda _directory: None,
            on_nodes=lambda _entry, _nodes, _complete: None,
            on_status=lambda message, error: statuses.append((message, error)),
        )
        controller.refresh_directory(2, 0)
        directory_payload = struct.pack("<BBHHHIB", 1, 0, 0, 1, 5, 1, 4) + b"task"
        controller.handle(self._frame(0x38, directory_payload))
        controller.fetch_list(5, 2, 0)

        scheduled[-1][1]()
        self.assertEqual(sent[-2]["payload"], struct.pack("<HI", 5, 0))
        self.assertEqual(sent[-1]["payload"], struct.pack("<HI", 5, 0))

        node_payload = struct.pack("<BBHIII", 1, 0, 5, 0, 1, 0x08001235)
        controller.handle(self._frame(0x39, node_payload))
        self.assertEqual(statuses[-1], ("已读取 task，共 1 个节点", False))

    def test_controller_stress_refreshes_with_loss_and_duplicates(self) -> None:
        sent: list[dict[str, object]] = []
        scheduled: list[tuple[int, object]] = []
        statuses: list[tuple[str, bool]] = []
        completions: list[int] = []
        controller = SectionListController(
            send=lambda **kwargs: sent.append(kwargs),
            schedule=lambda delay, callback: scheduled.append((delay, callback)),
            on_directory=lambda _directory: None,
            on_nodes=lambda _entry, nodes, complete: (
                completions.append(len(nodes)) if complete else None
            ),
            on_status=lambda message, error: statuses.append((message, error)),
        )
        list_count = 115
        node_count = 128
        cycles = 100

        for cycle in range(cycles):
            controller.refresh_directory(2, 0)
            for directory_index in range(list_count):
                if (cycle + directory_index) % 31 == 0:
                    scheduled[-1][1]()
                payload = struct.pack(
                    "<BBHHHIB",
                    1,
                    0,
                    directory_index,
                    list_count,
                    directory_index,
                    node_count if directory_index == 0 else 0,
                    4,
                ) + b"list"
                controller.handle(self._frame(0x38, payload))
                if directory_index > 0 and directory_index % 17 == 0:
                    duplicate = struct.pack(
                        "<BBHHHIB",
                        1,
                        0,
                        directory_index - 1,
                        list_count,
                        directory_index - 1,
                        0,
                        4,
                    ) + b"list"
                    controller.handle(self._frame(0x38, duplicate))

            controller.fetch_list(0, 2, 0)
            for node_index in range(node_count):
                if (cycle + node_index) % 23 == 0:
                    scheduled[-1][1]()
                if node_index > 0 and node_index % 11 == 0:
                    duplicate = struct.pack(
                        "<BBHIII", 1, 0, 0, node_index - 1, node_count, node_index * 4 - 3
                    )
                    controller.handle(self._frame(0x39, duplicate))
                payload = struct.pack(
                    "<BBHIII", 1, 0, 0, node_index, node_count, node_index * 4 + 1
                )
                controller.handle(self._frame(0x39, payload))

        self.assertEqual(completions, [node_count] * cycles)
        self.assertFalse(any(error for _message, error in statuses))
        self.assertGreater(len(sent), cycles * (list_count + node_count))

    def test_frame_parser_accepts_section_list_commands(self) -> None:
        for command_word in (0x38, 0x39):
            raw = build_frame(
                src=2,
                d_src=0,
                dst=1,
                d_dst=0,
                cmd_set=1,
                cmd_word=command_word,
                is_ack=1,
                payload=b"\x01\x00",
            )
            frames = FrameParser().feed(raw)
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].cmd_word, command_word)

    @staticmethod
    def _frame(cmd_word: int, payload: bytes) -> ProtocolFrame:
        return ProtocolFrame(
            sop=0xE8,
            version=1,
            src=2,
            d_src=0,
            dst=1,
            d_dst=0,
            cmd_set=1,
            cmd_word=cmd_word,
            is_ack=1,
            payload=payload,
            crc=0,
        )


if __name__ == "__main__":
    unittest.main()
