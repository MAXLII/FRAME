from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from serial_debug_assistant.models import ProtocolFrame
from serial_debug_assistant.section_list_protocol import (
    CMD_SET_SECTION_LIST,
    CMD_WORD_SECTION_LIST_DIRECTORY,
    CMD_WORD_SECTION_LIST_NODE,
    SECTION_LIST_PROTOCOL_VERSION,
    SECTION_LIST_STATUS_OK,
    SectionListDirectoryEntry,
    SectionListNode,
    build_section_list_directory_query,
    build_section_list_node_query,
    describe_section_list_status,
    parse_section_list_directory_ack,
    parse_section_list_node_ack,
)


class SectionListController:
    def __init__(
        self,
        *,
        send: Callable[..., None],
        schedule: Callable[[int, Callable[[], None]], object],
        on_directory: Callable[[list[SectionListDirectoryEntry]], None],
        on_nodes: Callable[[SectionListDirectoryEntry, list[SectionListNode], bool], None],
        on_status: Callable[[str, bool], None],
    ) -> None:
        self._send = send
        self._schedule = schedule
        self._on_directory = on_directory
        self._on_nodes = on_nodes
        self._on_status = on_status
        self._target = 0
        self._dynamic_target = 0
        self._generation = 0
        self._complete = False
        self._mode = "idle"
        self._directory: list[SectionListDirectoryEntry] = []
        self._active_entry: SectionListDirectoryEntry | None = None
        self._active_nodes: list[SectionListNode] = []
        self._active_expected_count: int | None = None

    def refresh_directory(self, target: int, dynamic_target: int) -> None:
        self._target = target
        self._dynamic_target = dynamic_target
        self._generation += 1
        generation = self._generation
        self._directory.clear()
        self._active_entry = None
        self._active_nodes.clear()
        self._active_expected_count = None
        self._complete = False
        self._mode = "directory"
        self._on_status("正在读取链表目录…", False)
        self._query_directory(0)
        self._schedule(1500, lambda: self._timeout(generation))

    def fetch_list(self, list_id: int, target: int, dynamic_target: int) -> None:
        entry = next((item for item in self._directory if item.list_id == list_id), None)
        if entry is None:
            self._on_status("请选择有效的链表", True)
            return
        self._target = target
        self._dynamic_target = dynamic_target
        self._generation += 1
        generation = self._generation
        self._active_entry = entry
        self._active_nodes = []
        self._active_expected_count = None
        self._complete = False
        self._mode = "nodes"
        if entry.node_count == 0:
            self._complete = True
            self._mode = "idle"
            self._on_nodes(entry, [], True)
            self._on_status(f"链表 {entry.name} 没有节点", False)
            return
        self._on_status(f"正在读取 {entry.name}：0 / {entry.node_count}", False)
        self._query_node(entry.list_id, 0)
        timeout_ms = max(1500, int(entry.node_count) * 350)
        self._schedule(timeout_ms, lambda: self._timeout(generation))

    def handle(self, frame: ProtocolFrame) -> bool:
        if frame.cmd_set != CMD_SET_SECTION_LIST or frame.is_ack != 1:
            return False
        if frame.cmd_word == CMD_WORD_SECTION_LIST_DIRECTORY and self._mode == "directory":
            return self._handle_directory(frame.payload)
        if frame.cmd_word == CMD_WORD_SECTION_LIST_NODE and self._mode == "nodes":
            return self._handle_node(frame.payload)
        return False

    def _handle_directory(self, payload: bytes) -> bool:
        try:
            entry = parse_section_list_directory_ack(payload)
        except ValueError as exc:
            self._fail(str(exc))
            return True
        if entry.protocol_version != SECTION_LIST_PROTOCOL_VERSION:
            self._fail(f"不支持的链表协议版本 {entry.protocol_version}")
            return True
        if entry.status != SECTION_LIST_STATUS_OK:
            if entry.list_count == 0:
                self._complete = True
                self._mode = "idle"
                self._on_directory([])
                self._on_status("设备未注册可调试链表", False)
                return True
            self._fail(describe_section_list_status(entry.status))
            return True
        self._directory.append(entry)
        if entry.directory_index + 1 < entry.list_count:
            self._query_directory(entry.directory_index + 1)
        else:
            self._complete = True
            self._mode = "idle"
            self._on_directory(list(self._directory))
            self._on_status(f"已读取 {len(self._directory)} 条链表，请选择后获取节点", False)
        return True

    def _handle_node(self, payload: bytes) -> bool:
        try:
            node = parse_section_list_node_ack(payload)
        except ValueError as exc:
            self._fail(str(exc))
            return True
        if node.status != SECTION_LIST_STATUS_OK:
            self._fail(describe_section_list_status(node.status))
            return True
        entry = self._active_entry
        if (entry is None) or (node.list_id != entry.list_id):
            self._fail("收到的链表节点与当前选择不一致")
            return True
        if node.node_index != len(self._active_nodes):
            self._fail("收到的链表节点顺序不连续，请重新刷新")
            return True
        if self._active_expected_count is None:
            self._active_expected_count = node.node_count
        elif node.node_count != self._active_expected_count:
            self._fail("链表节点数量在读取过程中发生变化，请重新刷新")
            return True
        self._active_nodes.append(node)
        received = len(self._active_nodes)
        expected_count = self._active_expected_count
        updated_entry = replace(entry, node_count=expected_count)
        self._directory = [
            updated_entry if item.list_id == entry.list_id else item for item in self._directory
        ]
        self._active_entry = updated_entry
        complete = received >= expected_count
        self._on_nodes(updated_entry, list(self._active_nodes), complete)
        if received < expected_count:
            self._on_status(f"正在读取 {entry.name}：{received} / {expected_count}", False)
            self._query_node(entry.list_id, received)
        else:
            self._complete = True
            self._mode = "idle"
            self._on_status(f"已读取 {entry.name}，共 {received} 个节点", False)
        return True

    def _query_directory(self, index: int) -> None:
        self._send(
            dst=self._target,
            d_dst=self._dynamic_target,
            cmd_set=CMD_SET_SECTION_LIST,
            cmd_word=CMD_WORD_SECTION_LIST_DIRECTORY,
            payload=build_section_list_directory_query(index),
        )

    def _query_node(self, list_id: int, node_index: int) -> None:
        self._send(
            dst=self._target,
            d_dst=self._dynamic_target,
            cmd_set=CMD_SET_SECTION_LIST,
            cmd_word=CMD_WORD_SECTION_LIST_NODE,
            payload=build_section_list_node_query(list_id, node_index),
        )

    def _timeout(self, generation: int) -> None:
        if generation != self._generation:
            return
        if not self._complete:
            self._fail("读取链表超时")

    def _fail(self, message: str) -> None:
        self._complete = True
        self._mode = "idle"
        self._on_status(message, True)
