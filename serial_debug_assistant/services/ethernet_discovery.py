from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
import select
import socket
import time
from typing import Any, Callable, Mapping, Sequence


DISCOVERY_PORT = 5000
DISCOVERY_TIMEOUT_SECONDS = 0.4
DISCOVERY_REQUEST = b"FRAME_DISCOVER_V1"
DISCOVERY_RESPONSE_PREFIX = "FRAME_DEVICE_V1"
DISCOVERY_MAX_DATAGRAM_SIZE = 1024
DISCOVERY_REQUIRED_FIELDS = (
    "name",
    "ip",
    "tcp_port",
    "mac",
    "fw_version",
    "protocol_version",
)
_MAC_PATTERN = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


@dataclass(frozen=True)
class IPv4NetworkInterface:
    name: str
    address: str
    netmask: str
    broadcast: str


@dataclass(frozen=True)
class EthernetDiscoveryDevice:
    name: str
    ip_address: str
    advertised_ip_address: str
    tcp_port: int
    mac_address: str
    firmware_version: str
    frame_protocol_version: str
    interface: IPv4NetworkInterface

    @property
    def identity(self) -> str:
        return self.mac_address


@dataclass(frozen=True)
class EthernetDiscoveryScan:
    devices: tuple[EthernetDiscoveryDevice, ...]
    interfaces: tuple[IPv4NetworkInterface, ...]
    duration_seconds: float
    send_errors: tuple[str, ...]


def enumerate_ipv4_interfaces(
    *,
    addresses_by_name: Mapping[str, Sequence[Any]] | None = None,
    stats_by_name: Mapping[str, Any] | None = None,
) -> tuple[IPv4NetworkInterface, ...]:
    if addresses_by_name is None or stats_by_name is None:
        import psutil

        addresses_by_name = psutil.net_if_addrs()
        stats_by_name = psutil.net_if_stats()

    interfaces: list[IPv4NetworkInterface] = []
    seen: set[tuple[str, str]] = set()
    for name, addresses in addresses_by_name.items():
        stats = stats_by_name.get(name)
        if stats is None or not bool(getattr(stats, "isup", False)):
            continue
        for address in addresses:
            if getattr(address, "family", None) != socket.AF_INET:
                continue
            address_text = str(getattr(address, "address", ""))
            netmask_text = str(getattr(address, "netmask", ""))
            try:
                ipv4 = ipaddress.IPv4Address(address_text)
                network = ipaddress.IPv4Network(f"{ipv4}/{netmask_text}", strict=False)
            except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
                continue
            if ipv4.is_loopback or ipv4.is_multicast or ipv4.is_unspecified:
                continue
            if network.prefixlen >= 32:
                continue
            key = (name, str(ipv4))
            if key in seen:
                continue
            seen.add(key)
            interfaces.append(
                IPv4NetworkInterface(
                    name=name,
                    address=str(ipv4),
                    netmask=str(network.netmask),
                    broadcast=str(network.broadcast_address),
                )
            )
    interfaces.sort(key=lambda item: (item.name.casefold(), ipaddress.IPv4Address(item.address)))
    return tuple(interfaces)


def build_discovery_request() -> bytes:
    return DISCOVERY_REQUEST


def parse_discovery_response(
    payload: bytes,
    *,
    source_ip: str,
    interface: IPv4NetworkInterface,
) -> EthernetDiscoveryDevice:
    try:
        message = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("discovery response is not ASCII") from exc
    if not message or any(ord(character) < 0x20 or ord(character) > 0x7E for character in message):
        raise ValueError("discovery response contains non-printable ASCII")

    parts = message.split(";")
    if not parts or parts[0] != DISCOVERY_RESPONSE_PREFIX:
        raise ValueError("discovery response prefix is invalid")

    fields: dict[str, str] = {}
    for item in parts[1:]:
        if "=" not in item:
            raise ValueError("discovery response field is malformed")
        key, value = item.split("=", 1)
        if not key or key in fields:
            raise ValueError("discovery response contains an empty or duplicate field")
        fields[key] = value
    missing = [field for field in DISCOVERY_REQUIRED_FIELDS if not fields.get(field)]
    if missing:
        raise ValueError(f"discovery response is missing required field(s): {', '.join(missing)}")

    name = fields["name"].strip()
    firmware_version = fields["fw_version"].strip()
    protocol_version = fields["protocol_version"].strip()
    if not name or not firmware_version or not protocol_version:
        raise ValueError("discovery response contains an empty required value")
    try:
        advertised_ip = str(ipaddress.IPv4Address(fields["ip"]))
        actual_ip = str(ipaddress.IPv4Address(source_ip))
    except ipaddress.AddressValueError as exc:
        raise ValueError("discovery response contains an invalid IPv4 address") from exc
    for address in (advertised_ip, actual_ip):
        ipv4 = ipaddress.IPv4Address(address)
        if ipv4.is_unspecified or ipv4.is_multicast or address == "255.255.255.255":
            raise ValueError("discovery response contains an unusable IPv4 address")
    try:
        tcp_port = int(fields["tcp_port"], 10)
    except ValueError as exc:
        raise ValueError("discovery TCP port is not a decimal integer") from exc
    if not 1 <= tcp_port <= 65535:
        raise ValueError("discovery TCP port is outside 1..65535")

    mac_address = _normalize_mac_address(fields["mac"])
    return EthernetDiscoveryDevice(
        name=name,
        ip_address=actual_ip,
        advertised_ip_address=advertised_ip,
        tcp_port=tcp_port,
        mac_address=mac_address,
        firmware_version=firmware_version,
        frame_protocol_version=protocol_version,
        interface=interface,
    )


class EthernetDiscoveryService:
    def __init__(
        self,
        *,
        interface_provider: Callable[[], tuple[IPv4NetworkInterface, ...]] = enumerate_ipv4_interfaces,
        discovery_port: int = DISCOVERY_PORT,
    ) -> None:
        self.interface_provider = interface_provider
        self.discovery_port = discovery_port

    def discover(self, *, timeout_seconds: float = DISCOVERY_TIMEOUT_SECONDS) -> EthernetDiscoveryScan:
        if timeout_seconds <= 0:
            raise ValueError("discovery timeout must be positive")
        if not 1 <= self.discovery_port <= 65535:
            raise ValueError("discovery UDP port must be between 1 and 65535")

        started = time.monotonic()
        deadline = started + timeout_seconds
        interfaces = self.interface_provider()
        sockets: list[socket.socket] = []
        interface_by_socket: dict[socket.socket, IPv4NetworkInterface] = {}
        send_errors: list[str] = []
        devices_by_identity: dict[str, EthernetDiscoveryDevice] = {}

        try:
            for interface in interfaces:
                udp_socket: socket.socket | None = None
                try:
                    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    udp_socket.bind((interface.address, 0))
                    udp_socket.setblocking(False)
                    udp_socket.sendto(DISCOVERY_REQUEST, (interface.broadcast, self.discovery_port))
                except OSError as exc:
                    send_errors.append(f"{interface.name} ({interface.address}): {exc}")
                    if udp_socket is not None:
                        udp_socket.close()
                    continue
                sockets.append(udp_socket)
                interface_by_socket[udp_socket] = interface

            retry_at = started + min(0.15, timeout_seconds / 2)
            retried = False
            while sockets:
                now = time.monotonic()
                if now >= deadline:
                    break
                if not retried and now >= retry_at:
                    for udp_socket in sockets:
                        interface = interface_by_socket[udp_socket]
                        try:
                            udp_socket.sendto(DISCOVERY_REQUEST, (interface.broadcast, self.discovery_port))
                        except OSError as exc:
                            send_errors.append(f"{interface.name} retry ({interface.address}): {exc}")
                    retried = True
                    continue
                wait_until = deadline if retried else min(deadline, retry_at)
                readable, _, _ = select.select(sockets, (), (), max(0.0, wait_until - now))
                for udp_socket in readable:
                    interface = interface_by_socket[udp_socket]
                    while True:
                        try:
                            payload, source = udp_socket.recvfrom(DISCOVERY_MAX_DATAGRAM_SIZE)
                        except BlockingIOError:
                            break
                        except OSError:
                            break
                        try:
                            device = parse_discovery_response(
                                payload,
                                source_ip=str(source[0]),
                                interface=interface,
                            )
                        except ValueError:
                            continue
                        devices_by_identity[device.identity] = device
        finally:
            for udp_socket in sockets:
                udp_socket.close()

        devices = tuple(
            sorted(
                devices_by_identity.values(),
                key=lambda item: (item.name.casefold(), ipaddress.IPv4Address(item.ip_address), item.tcp_port),
            )
        )
        return EthernetDiscoveryScan(
            devices=devices,
            interfaces=interfaces,
            duration_seconds=time.monotonic() - started,
            send_errors=tuple(send_errors),
        )


def _normalize_mac_address(mac_address: str) -> str:
    if _MAC_PATTERN.fullmatch(mac_address) is None:
        raise ValueError("discovery MAC address is invalid")
    values = bytes.fromhex(mac_address.replace("-", ":").replace(":", ""))
    if values == b"\x00" * 6 or values == b"\xFF" * 6 or values[0] & 0x01:
        raise ValueError("discovery MAC address is not a usable unicast address")
    return ":".join(f"{value:02X}" for value in values)
