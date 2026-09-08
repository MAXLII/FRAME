// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include "tcp_transport.hpp"
#include <Windows.h>
#include <chrono>
#include <deque>
#include <fstream>
namespace frame {
std::wstring wide(const std::string &s);
class transport final {
  tcp_transport tcp_;
  HANDLE handle_ = INVALID_HANDLE_VALUE;
  json replay_;
  std::size_t replay_index_ = 0;
  std::deque<bytes> replay_rx_;
  std::ofstream recording_;
  bytes repeat_frame_;
  std::chrono::steady_clock::time_point repeat_due_;
  unsigned repeat_period_ = 10;
  bool advance_tick_ = false;

public:
  std::string endpoint;
  unsigned baud_rate = 0;
  ~transport() { close(); }
  void open(const json &settings, const std::function<void()> &guard = {});
  void close();
  unsigned set_baud(unsigned baud);
  bool opened() const {
    return handle_ != INVALID_HANDLE_VALUE || tcp_.opened() || !replay_.is_null();
  }
  void write(const bytes &b);
  bytes read(unsigned timeout_ms = 10);
  static json ports();
};
} // namespace frame
