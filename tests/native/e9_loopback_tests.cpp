// SPDX-License-Identifier: MIT
// COMM v1 end-to-end loopback: a mock device answers E9 requests over TCP and
// the FRAME backend connects with wire=e9 to run a parameter list operation.
#include "frame/api.hpp"
#include "protocol.hpp"
#include <chrono>
#include <cstdint>
#include <iostream>
#include <string>
#include <thread>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#define SOCKET int
#define INVALID_SOCKET (-1)
#define closesocket close
#endif

using json = nlohmann::json;
using namespace std::chrono_literals;

namespace {
std::uint32_t socket_port = 0;
std::uint64_t received_frames = 0;
std::uint64_t e9_frames = 0;
std::uint64_t codec_select_requests = 0;
std::uint64_t param_requests = 0;
bool device_failed = false;
std::string device_error;

void fail_device(const std::string &message) {
  device_failed = true;
  device_error = message;
}

void device_loop() {
#ifdef _WIN32
  WSADATA wsa{};
  if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
    fail_device("WSAStartup failed");
    return;
  }
#endif
  SOCKET listener = socket(AF_INET, SOCK_STREAM, 0);
  if (listener == INVALID_SOCKET) {
    fail_device("socket failed");
    return;
  }
  sockaddr_in address{};
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  address.sin_port = 0;
  if (bind(listener, reinterpret_cast<sockaddr *>(&address), sizeof(address)) !=
      0) {
    fail_device("bind failed");
    return;
  }
  socklen_t length = sizeof(address);
  if (getsockname(listener, reinterpret_cast<sockaddr *>(&address), &length) !=
      0) {
    fail_device("getsockname failed");
    return;
  }
  socket_port = ntohs(address.sin_port);
  if (listen(listener, 1) != 0) {
    fail_device("listen failed");
    return;
  }
  SOCKET peer = accept(listener, nullptr, nullptr);
  if (peer == INVALID_SOCKET) {
    fail_device("accept failed");
    return;
  }
  frame::parser parser;
  std::uint8_t buffer[4096];
  for (;;) {
    int count = recv(peer, reinterpret_cast<char *>(buffer), sizeof(buffer), 0);
    if (count <= 0)
      break;
    std::vector<frame::packet> packets;
    try {
      packets = parser.feed(std::span<const std::uint8_t>(buffer, count));
    } catch (const std::exception &e) {
      fail_device(std::string("parser: ") + e.what());
      break;
    }
    for (auto &packet : packets) {
      ++received_frames;
      if (packet.seq <= 7 && packet.src == 1)
        ++e9_frames;
      if (packet.group == 0 && packet.word == 0 && packet.ack == 0) {
        ++codec_select_requests;
        const auto crc32 = frame::codebook_crc32();
        frame::packet response;
        response.src = 2;
        response.dst = 1;
        response.group = 0;
        response.word = 0;
        response.ack = 1;
        response.seq = packet.seq;
        response.payload = {0, 1, 0, 1, 0, 0, 0, 0};
        response.payload[4] = static_cast<std::uint8_t>((crc32 >> 24) & 0xFFu);
        response.payload[5] = static_cast<std::uint8_t>(crc32 & 0xFFu);
        response.payload[6] = static_cast<std::uint8_t>((crc32 >> 8) & 0xFFu);
        response.payload[7] = static_cast<std::uint8_t>((crc32 >> 16) & 0xFFu);
        auto wire = frame::encode_v1(response);
        send(peer, reinterpret_cast<const char *>(wire.data()),
             static_cast<int>(wire.size()), 0);
      } else if (packet.group == 1 && packet.word == 1 && packet.ack == 0) {
        ++param_requests;
        frame::packet response;
        response.src = 2;
        response.dst = 1;
        response.group = 1;
        response.word = 1;
        response.ack = 1;
        response.seq = packet.seq;
        response.payload = {0, 0, 0, 0}; // zero parameters
        auto wire = frame::encode_v1(response, true);
        send(peer, reinterpret_cast<const char *>(wire.data()),
             static_cast<int>(wire.size()), 0);
      }
    }
  }
  closesocket(peer);
  closesocket(listener);
}

void require(bool ok, const char *text) {
  if (!ok)
    throw std::runtime_error(text);
}
std::uint64_t submit(void *h, json command) {
  auto s = command.dump();
  std::uint64_t id = 0;
  require(frame_submit(h, s.data(), static_cast<std::uint32_t>(s.size()), &id) ==
              0,
          "submit");
  return id;
}
json wait(void *h, std::uint64_t id) {
  auto end = std::chrono::steady_clock::now() + 5s;
  std::uint32_t n = 0;
  while (frame_result(h, id, nullptr, 0, &n) == 1) {
    require(std::chrono::steady_clock::now() < end, "wait deadline");
    std::this_thread::sleep_for(5ms);
  }
  std::string s(n, '\0');
  require(frame_result(h, id, s.data(), n, &n) == 0, "copy result");
  auto result = json::parse(s);
  require(frame_release(h, id) == 0, "release");
  return result;
}
json call(void *h, json q) { return wait(h, submit(h, q)); }
} // namespace

int main() {
  try {
    std::thread device(device_loop);
    auto deadline = std::chrono::steady_clock::now() + 5s;
    while (socket_port == 0 && !device_failed) {
      require(std::chrono::steady_clock::now() < deadline, "device port");
      std::this_thread::sleep_for(10ms);
    }
    require(!device_failed, device_error.c_str());

    void *h = frame_create();
    require(h != nullptr, "create");

    auto connected =
        call(h, {{"group", "connect"},
                 {"transport", "tcp"},
                 {"host", "127.0.0.1"},
                 {"tcp_port", socket_port},
                 {"wire", "e9"}});
    require(connected["ok"] == true, "connect with wire=e9");

    auto listed = call(h, {{"group", "param"}, {"action", "list"}});
    require(listed["ok"] == true, "parameter list over E9");
    require(listed["data"].is_array() && listed["data"].empty(),
            "parameter list empty result");

    frame_destroy(h);
    device.join();

    require(!device_failed, device_error.c_str());
    require(received_frames > 0 && e9_frames == received_frames,
            "all transmitted frames are 0xE9");
    require(codec_select_requests == 1, "one CODEC_SELECT negotiation");
    require(param_requests == 1, "one parameter list request");
    std::cout << "PASS: E9 loopback (negotiation + parameter list)\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
}
