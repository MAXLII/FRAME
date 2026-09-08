// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include <functional>
namespace frame {
class tcp_transport final {
  std::uintptr_t socket_ = ~std::uintptr_t(0);
  bool started_ = false;
public:
  ~tcp_transport() { close(); }
  bool opened() const { return socket_ != ~std::uintptr_t(0); }
  void open(const std::string &address, unsigned port, const std::function<void()> &guard);
  void close();
  void write(const bytes &data);
  bytes read(unsigned timeout_ms);
};
}
