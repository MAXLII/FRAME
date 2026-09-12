// SPDX-License-Identifier: MIT
#pragma once
#include "runtime.hpp"
#include "symbols.hpp"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <set>
namespace frame {
inline bytes name_payload(const std::string &name) {
  if (name.empty() || name.size() > 64)
    throw failure(2, "Parameter name must contain 1..64 UTF-8 bytes");
  bytes b{static_cast<std::uint8_t>(name.size())};
  b.insert(b.end(), name.begin(), name.end());
  return b;
}
inline bytes object_payload(const json &q) {
  auto id = q.value("id", 0);
  if (id < 0 || id > 255)
    throw failure(2, "Object id outside uint8");
  return {static_cast<std::uint8_t>(id), 0, 0, 0};
}
inline json checked(json j) {
  if (j.contains("status") && j["status"] != 0)
    throw failure(7, "Device status: " + j.dump());
  return j;
}
}
