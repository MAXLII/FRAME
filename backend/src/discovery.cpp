// SPDX-License-Identifier: MIT
#include <WinSock2.h>
#include <WS2tcpip.h>
#include <iphlpapi.h>
#include "discovery.hpp"
#include <algorithm>
#include <charconv>
#include <chrono>
#include <map>
#include <memory>
#include <set>
namespace frame {
namespace {
bool address(const std::string &text, in_addr &value) {
  if (InetPtonA(AF_INET, text.c_str(), &value) != 1) return false;
  auto host = ntohl(value.s_addr);
  return host != 0 && host != 0xffffffff && (host >> 28) != 14;
}
std::string text_address(in_addr value) {
  char text[INET_ADDRSTRLEN]{};
  InetNtopA(AF_INET, &value, text, sizeof(text));
  return text;
}
std::string utf8(const wchar_t *text) {
  int size = WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
  std::string value(size, '\0');
  WideCharToMultiByte(CP_UTF8, 0, text, -1, value.data(), size, nullptr, nullptr);
  if (!value.empty()) value.pop_back();
  return value;
}
struct udp_socket {
  SOCKET value = INVALID_SOCKET;
  json interface;
  sockaddr_in destination{};
  ~udp_socket() { if (value != INVALID_SOCKET) closesocket(value); }
};
}
json ethernet_discovery::parse(const std::string &payload, const std::string &source) {
  auto invalid = [] { throw failure(2, "Invalid FRAME discovery response"); };
  if (payload.size() > 1024 || !payload.starts_with("FRAME_DEVICE_V1;")) invalid();
  for (unsigned char c : payload) if (c < 32 || c > 126) invalid();
  std::map<std::string, std::string> fields;
  std::size_t pos = 16;
  while (pos < payload.size()) {
    auto end = payload.find(';', pos);
    auto field = payload.substr(pos, end == std::string::npos ? end : end - pos);
    auto equals = field.find('=');
    if (equals == 0 || equals == std::string::npos || !fields.emplace(field.substr(0, equals), field.substr(equals + 1)).second) invalid();
    if (end == std::string::npos) break;
    pos = end + 1;
    if (pos == payload.size()) invalid();
  }
  for (auto key : {"name", "ip", "tcp_port", "mac", "fw_version", "protocol_version"})
    if (!fields.contains(key) || fields[key].find_first_not_of(' ') == std::string::npos) invalid();
  in_addr ip{};
  if (!address(fields["ip"], ip) || !address(source, ip)) invalid();
  unsigned port = 0;
  auto &port_text = fields["tcp_port"];
  auto converted = std::from_chars(port_text.data(), port_text.data() + port_text.size(), port);
  if (converted.ec != std::errc() || converted.ptr != port_text.data() + port_text.size() || port == 0 || port > 65535) invalid();
  auto mac = fields["mac"];
  if (mac.size() != 17) invalid();
  unsigned first = 0, nonzero = 0;
  for (unsigned i = 0; i < 6; ++i) {
    unsigned byte = 0;
    auto parsed = std::from_chars(mac.data() + i * 3, mac.data() + i * 3 + 2, byte, 16);
    if (parsed.ec != std::errc() || parsed.ptr != mac.data() + i * 3 + 2) invalid();
    if (i < 5 && mac[i * 3 + 2] != ':' && mac[i * 3 + 2] != '-') invalid();
    if (i == 0) first = byte;
    nonzero |= byte;
    constexpr char hex[] = "0123456789ABCDEF";
    mac[i * 3] = hex[byte >> 4]; mac[i * 3 + 1] = hex[byte & 15];
    if (i < 5) mac[i * 3 + 2] = ':';
  }
  if (!nonzero || (first & 1)) invalid();
  return {{"name", fields["name"]}, {"ip", source}, {"advertised_ip", fields["ip"]},
          {"tcp_port", port}, {"mac", mac}, {"fw_version", fields["fw_version"]},
          {"protocol_version", fields["protocol_version"]}};
}
json ethernet_discovery::scan(const json &settings, const std::function<void()> &guard) {
  unsigned milliseconds = settings.value("scan_ms", 400u), port = settings.value("discovery_port", 5000u);
  if (milliseconds < 50 || milliseconds > 10000 || port == 0 || port > 65535)
    throw failure(2, "Invalid discovery scan_ms (50..10000) or UDP port");
  WSADATA data{};
  if (WSAStartup(MAKEWORD(2, 2), &data)) throw failure(3, "Winsock initialization failed");
  struct cleanup { ~cleanup() { WSACleanup(); } } cleanup;
  json interfaces = json::array(), errors = json::array();
  if (settings.contains("host")) {
    in_addr target{};
    if (!address(settings["host"], target)) throw failure(2, "Invalid discovery target IPv4");
    interfaces.push_back({{"name", "direct"}, {"address", "0.0.0.0"}, {"broadcast", settings["host"]}});
  } else {
    ULONG size = 16384, result = ERROR_BUFFER_OVERFLOW;
    std::vector<unsigned char> buffer;
    for (int retry = 0; retry < 3 && result == ERROR_BUFFER_OVERFLOW; ++retry) {
      buffer.resize(size);
      result = GetAdaptersAddresses(AF_INET, GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER,
                                   nullptr, reinterpret_cast<IP_ADAPTER_ADDRESSES *>(buffer.data()), &size);
    }
    if (result != NO_ERROR && result != ERROR_NO_DATA) throw failure(3, "Cannot enumerate IPv4 adapters");
    std::set<std::string> seen;
    if (result == NO_ERROR) for (auto *adapter = reinterpret_cast<IP_ADAPTER_ADDRESSES *>(buffer.data()); adapter; adapter = adapter->Next) {
      if (adapter->OperStatus != IfOperStatusUp || adapter->IfType == IF_TYPE_SOFTWARE_LOOPBACK) continue;
      for (auto *unicast = adapter->FirstUnicastAddress; unicast; unicast = unicast->Next) {
        if (unicast->Address.lpSockaddr->sa_family != AF_INET || unicast->OnLinkPrefixLength >= 32) continue;
        auto ip = reinterpret_cast<sockaddr_in *>(unicast->Address.lpSockaddr)->sin_addr;
        auto text = text_address(ip);
        if (!address(text, ip) || !seen.insert(text).second) continue;
        auto prefix = unicast->OnLinkPrefixLength;
        in_addr broadcast{}; broadcast.s_addr = htonl(ntohl(ip.s_addr) | (prefix == 0 ? 0xffffffffu : 0xffffffffu >> prefix));
        interfaces.push_back({{"name", utf8(adapter->FriendlyName)}, {"address", text}, {"broadcast", text_address(broadcast)}});
      }
    }
  }
  std::vector<std::unique_ptr<udp_socket>> sockets;
  auto send = [&](udp_socket &socket) {
    constexpr char request[] = "FRAME_DISCOVER_V1";
    if (sendto(socket.value, request, sizeof(request) - 1, 0, reinterpret_cast<sockaddr *>(&socket.destination), sizeof(socket.destination)) == SOCKET_ERROR)
      errors.push_back(socket.interface["address"].get<std::string>() + ": send " + std::to_string(WSAGetLastError()));
  };
  for (const auto &interface : interfaces) {
    guard();
    if (sockets.size() >= FD_SETSIZE) { errors.push_back("Discovery adapter limit reached"); break; }
    auto socket = std::make_unique<udp_socket>(); socket->interface = interface;
    socket->value = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    BOOL broadcast = TRUE; u_long nonblocking = 1;
    sockaddr_in local{}; local.sin_family = AF_INET;
    InetPtonA(AF_INET, interface["address"].get<std::string>().c_str(), &local.sin_addr);
    if (socket->value == INVALID_SOCKET || setsockopt(socket->value, SOL_SOCKET, SO_BROADCAST, reinterpret_cast<char *>(&broadcast), sizeof(broadcast)) == SOCKET_ERROR ||
        bind(socket->value, reinterpret_cast<sockaddr *>(&local), sizeof(local)) == SOCKET_ERROR || ioctlsocket(socket->value, FIONBIO, &nonblocking) == SOCKET_ERROR) {
      errors.push_back(interface["address"].get<std::string>() + ": socket " + std::to_string(WSAGetLastError())); continue;
    }
    socket->destination.sin_family = AF_INET; socket->destination.sin_port = htons(static_cast<u_short>(port));
    InetPtonA(AF_INET, interface["broadcast"].get<std::string>().c_str(), &socket->destination.sin_addr);
    send(*socket); sockets.push_back(std::move(socket));
  }
  auto start = std::chrono::steady_clock::now(), deadline = start + std::chrono::milliseconds(milliseconds);
  bool retried = false;
  std::map<std::string, json> devices;
  while (!sockets.empty() && std::chrono::steady_clock::now() < deadline) {
    guard();
    if (!retried && std::chrono::steady_clock::now() - start >= std::chrono::milliseconds(std::min(150u, milliseconds / 2))) {
      for (auto &socket : sockets) send(*socket);
      retried = true;
    }
    fd_set ready; FD_ZERO(&ready); for (auto &socket : sockets) FD_SET(socket->value, &ready);
    timeval wait{0, 10000};
    if (select(0, &ready, nullptr, nullptr, &wait) == SOCKET_ERROR) throw failure(3, "Discovery receive failed");
    for (auto &socket : sockets) if (FD_ISSET(socket->value, &ready)) {
      for (unsigned n = 0; n < 64; ++n) {
        guard(); char buffer[1025]; sockaddr_in source{}; int length = sizeof(source);
        int count = recvfrom(socket->value, buffer, sizeof(buffer), 0, reinterpret_cast<sockaddr *>(&source), &length);
        if (count == SOCKET_ERROR) break;
        try {
          auto device = parse(std::string(buffer, count), text_address(source.sin_addr));
          device["interface"] = socket->interface;
          if (devices.size() < 256 || devices.contains(device["mac"])) devices[device["mac"]] = device;
        } catch (const failure &) { /* Ignore unrelated or malformed UDP traffic. */ }
      }
    }
  }
  json found = json::array(); for (auto &[mac, device] : devices) found.push_back(device);
  return {{"devices", found}, {"interfaces", interfaces}, {"send_errors", errors}};
}
}
