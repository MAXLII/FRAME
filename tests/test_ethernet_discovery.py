from __future__ import annotations

from types import SimpleNamespace
import socket
import threading

import pytest

from serial_debug_assistant.services.ethernet_discovery import (
    DISCOVERY_REQUEST,
    EthernetDiscoveryService,
    IPv4NetworkInterface,
    build_discovery_request,
    enumerate_ipv4_interfaces,
    parse_discovery_response,
)


def _response(**overrides: str) -> bytes:
    fields = {
        "name": "GD32E507-PFC",
        "ip": "192.168.10.99",
        "tcp_port": "9000",
        "mac": "02:12:34:56:78:9A",
        "fw_version": "1.4.2",
        "protocol_version": "1.0",
    }
    fields.update(overrides)
    return (
        "FRAME_DEVICE_V1;"
        + ";".join(f"{key}={value}" for key, value in fields.items())
    ).encode("ascii")


def test_discovery_request_and_response_round_trip_uses_source_ip() -> None:
    assert build_discovery_request() == DISCOVERY_REQUEST == b"FRAME_DISCOVER_V1"
    interface = IPv4NetworkInterface("Ethernet 1", "192.168.10.2", "255.255.255.0", "192.168.10.255")

    device = parse_discovery_response(
        _response(),
        source_ip="192.168.10.20",
        interface=interface,
    )

    assert device.name == "GD32E507-PFC"
    assert device.ip_address == "192.168.10.20"
    assert device.advertised_ip_address == "192.168.10.99"
    assert device.tcp_port == 9000
    assert device.mac_address == "02:12:34:56:78:9A"
    assert device.firmware_version == "1.4.2"
    assert device.frame_protocol_version == "1.0"
    assert device.interface == interface


@pytest.mark.parametrize(
    "payload, message",
    [
        (b"FRAME_DISCOVER_V1", "prefix"),
        (b"hello", "prefix"),
        (_response(name=""), "missing required"),
        (_response(mac="not-a-mac"), "MAC address"),
        (_response(tcp_port="0"), "outside"),
        (_response() + b";name=duplicate", "duplicate"),
    ],
)
def test_discovery_response_strictly_rejects_echo_and_invalid_fields(payload: bytes, message: str) -> None:
    interface = IPv4NetworkInterface("Ethernet", "10.0.0.2", "255.255.255.0", "10.0.0.255")

    with pytest.raises(ValueError, match=message):
        parse_discovery_response(payload, source_ip="10.0.0.20", interface=interface)


def test_enumerate_ipv4_interfaces_filters_inactive_and_loopback() -> None:
    addresses = {
        "Ethernet": [SimpleNamespace(family=socket.AF_INET, address="192.168.5.12", netmask="255.255.255.0")],
        "Loopback": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1", netmask="255.0.0.0")],
        "Disabled": [SimpleNamespace(family=socket.AF_INET, address="10.1.2.3", netmask="255.255.0.0")],
    }
    stats = {
        "Ethernet": SimpleNamespace(isup=True),
        "Loopback": SimpleNamespace(isup=True),
        "Disabled": SimpleNamespace(isup=False),
    }

    interfaces = enumerate_ipv4_interfaces(addresses_by_name=addresses, stats_by_name=stats)

    assert interfaces == (
        IPv4NetworkInterface("Ethernet", "192.168.5.12", "255.255.255.0", "192.168.5.255"),
    )


def test_discovery_service_collects_devices_and_merges_duplicate_mac() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    server.bind(("127.0.0.1", 0))
    server.settimeout(0.5)
    discovery_port = int(server.getsockname()[1])
    interface = IPv4NetworkInterface("Test", "127.0.0.1", "255.0.0.0", "127.0.0.1")
    responder_error: list[BaseException] = []

    def respond() -> None:
        try:
            request, source = server.recvfrom(1024)
            assert request == DISCOVERY_REQUEST
            server.sendto(_response(name="GD32E507-A", mac="02:00:00:00:00:01"), source)
            server.sendto(_response(name="GD32E507-A duplicate", mac="02-00-00-00-00-01"), source)
            server.sendto(_response(name="GD32E507-B", mac="02:00:00:00:00:02", tcp_port="9001"), source)
            server.sendto(request, source)  # Ordinary UDP echo must be ignored.
        except BaseException as exc:
            responder_error.append(exc)
        finally:
            server.close()

    responder = threading.Thread(target=respond, daemon=True)
    responder.start()
    service = EthernetDiscoveryService(interface_provider=lambda: (interface,), discovery_port=discovery_port)

    scan = service.discover(timeout_seconds=0.1)
    responder.join(timeout=1.0)

    assert responder_error == []
    assert len(scan.devices) == 2
    assert {device.mac_address for device in scan.devices} == {
        "02:00:00:00:00:01",
        "02:00:00:00:00:02",
    }
    assert all(device.ip_address == "127.0.0.1" for device in scan.devices)
    assert scan.interfaces == (interface,)
    assert scan.send_errors == ()
