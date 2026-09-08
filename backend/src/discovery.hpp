// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include <functional>
namespace frame {
class ethernet_discovery final {
public:
  static json parse(const std::string &payload, const std::string &source);
  static json scan(const json &settings, const std::function<void()> &guard);
};
}
