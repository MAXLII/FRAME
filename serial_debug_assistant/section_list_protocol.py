from __future__ import annotations

from dataclasses import dataclass
import struct


CMD_SET_SECTION_LIST = 0x01
CMD_WORD_SECTION_LIST_DIRECTORY = 0x38
CMD_WORD_SECTION_LIST_NODE = 0x39
SECTION_LIST_PROTOCOL_VERSION = 1
SECTION_LIST_STATUS_OK = 0


@dataclass(frozen=True, slots=True)
class SectionListDirectoryEntry:
    protocol_version: int
    status: int
    directory_index: int
    list_count: int
    list_id: int = 0
    node_count: int = 0
    name: str = ""


@dataclass(frozen=True, slots=True)
class SectionListNode:
    protocol_version: int
    status: int
    list_id: int
    node_index: int
    node_count: int
    address: int | None = None


def build_section_list_directory_query(index: int) -> bytes:
    if not 0 <= index <= 0xFFFF:
        raise ValueError("directory index must fit uint16")
    return struct.pack("<H", index)


def build_section_list_node_query(list_id: int, node_index: int) -> bytes:
    if not 0 <= list_id <= 0xFFFF:
        raise ValueError("list id must fit uint16")
    if not 0 <= node_index <= 0xFFFFFFFF:
        raise ValueError("node index must fit uint32")
    return struct.pack("<HI", list_id, node_index)


def parse_section_list_directory_ack(payload: bytes) -> SectionListDirectoryEntry:
    if len(payload) < 6:
        raise ValueError("section-list directory response is shorter than 6 bytes")
    protocol_version, status, directory_index, list_count = struct.unpack_from("<BBHH", payload)
    if status != SECTION_LIST_STATUS_OK:
        return SectionListDirectoryEntry(protocol_version, status, directory_index, list_count)
    if len(payload) < 13:
        raise ValueError("successful section-list directory response is shorter than 13 bytes")
    list_id, node_count, name_len = struct.unpack_from("<HIB", payload, 6)
    if len(payload) < 13 + name_len:
        raise ValueError("section-list directory name is truncated")
    name = payload[13 : 13 + name_len].decode("utf-8", errors="replace")
    return SectionListDirectoryEntry(
        protocol_version,
        status,
        directory_index,
        list_count,
        list_id,
        node_count,
        name,
    )


def parse_section_list_node_ack(payload: bytes) -> SectionListNode:
    if len(payload) < 12:
        raise ValueError("section-list node response is shorter than 12 bytes")
    protocol_version, status, list_id, node_index, node_count = struct.unpack_from("<BBHII", payload)
    address = None
    if status == SECTION_LIST_STATUS_OK:
        if len(payload) < 16:
            raise ValueError("successful section-list node response is shorter than 16 bytes")
        address = struct.unpack_from("<I", payload, 12)[0]
    return SectionListNode(protocol_version, status, list_id, node_index, node_count, address)


def describe_section_list_status(status: int) -> str:
    return {
        0: "OK",
        1: "Invalid request",
        2: "Directory index invalid",
        3: "List ID invalid",
        4: "Node index invalid",
        5: "List registration invalid",
        6: "Address unavailable",
    }.get(status, f"Unknown status {status}")
