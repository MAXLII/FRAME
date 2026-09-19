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
#include <future>
#include <memory>

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
std::promise<std::uint32_t> listening;
std::uint64_t received_frames = 0;
std::uint64_t e9_frames = 0;
std::uint64_t codec_select_requests = 0;
std::uint64_t param_requests = 0;
bool device_failed = false;
std::string device_error;

void fail_device(const std::string &message) {
  device_failed = true;
  device_error = message;
  try { listening.set_exception(std::make_exception_ptr(std::runtime_error(message))); }
  catch (const std::future_error &) { /* Readiness was already published. */ }
}

struct socket_owner {
  SOCKET value;
  ~socket_owner() { if (value != INVALID_SOCKET) closesocket(value); }
};

void device_loop() {
#ifdef _WIN32
  WSADATA wsa{};
  if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
    fail_device("WSAStartup failed");
    return;
  }
#endif
  SOCKET listener = socket(AF_INET, SOCK_STREAM, 0);
  socket_owner listener_owner{listener};
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
  if (listen(listener, 1) != 0) {
    fail_device("listen failed");
    return;
  }
  listening.set_value(ntohs(address.sin_port));
  fd_set readable;
  FD_ZERO(&readable);
  FD_SET(listener, &readable);
  timeval accept_timeout{5, 0};
  if (select(static_cast<int>(listener + 1), &readable, nullptr, nullptr, &accept_timeout) <= 0) {
    fail_device("accept timeout");
    return;
  }
  SOCKET peer = accept(listener, nullptr, nullptr);
  socket_owner peer_owner{peer};
  if (peer == INVALID_SOCKET) {
    fail_device("accept failed");
    return;
  }
#ifdef _WIN32
  DWORD receive_timeout = 5000;
#else
  timeval receive_timeout{5, 0};
#endif
  if (setsockopt(peer, SOL_SOCKET, SO_RCVTIMEO,
                 reinterpret_cast<const char *>(&receive_timeout), sizeof(receive_timeout)) != 0) {
    fail_device("receive timeout setup failed");
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
      if (packet.sop == 0xE9)
        ++e9_frames;
      if (packet.group == 0 && packet.word == 0 && packet.ack == 0) {
        ++codec_select_requests;
        frame::packet response;
        response.src = 2;
        response.dst = 1;
        response.group = 0;
        response.word = 0;
        response.ack = 1;
        response.seq = packet.seq;
        response.payload = {0, 1, 0, 1, 0x9D, 0x00, 0xDD, 0xB6};
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
        // A previous transaction's ACK must not satisfy this request.
        response.seq = static_cast<std::uint8_t>((packet.seq + 7) & 7);
        response.payload = {1, 0, 0, 0};
        auto stale = frame::encode_v1(response, false);
        send(peer, reinterpret_cast<const char *>(stale.data()), static_cast<int>(stale.size()), 0);
        response.seq = packet.seq;
        response.payload = {0, 0, 0, 0}; // zero parameters
        auto wire = frame::encode_v1(response, true);
        send(peer, reinterpret_cast<const char *>(wire.data()),
             static_cast<int>(wire.size()), 0);
      }
    }
  }
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
    auto ready = listening.get_future();
    std::jthread device(device_loop);
    require(ready.wait_for(5s) == std::future_status::ready, "device readiness timeout");
    const auto socket_port = ready.get();

    std::unique_ptr<void, decltype(&frame_destroy)> backend(frame_create(), frame_destroy);
    void *h = backend.get();
    require(h != nullptr, "create");

    auto connected =
        call(h, {{"group", "connect"},
                 {"transport", "tcp"},
                 {"host", "127.0.0.1"},
                 {"tcp_port", socket_port},
                 {"wire", "e9"}});
    require(connected["ok"] == true, "connect with wire=e9");
    auto deadline = std::chrono::steady_clock::now() + 2s;
    while (!call(h, {{"group", "status"}})["data"]["v1_negotiated"].get<bool>()) {
      require(std::chrono::steady_clock::now() < deadline, "CODEC_SELECT negotiation not completed");
      std::this_thread::sleep_for(5ms);
    }

    auto listed = call(h, {{"group", "param"}, {"action", "list"}});
    require(listed["ok"] == true, "parameter list over E9");
    require(listed["data"].is_array() && listed["data"].empty(),
            "parameter list empty result");

    backend.reset();
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
