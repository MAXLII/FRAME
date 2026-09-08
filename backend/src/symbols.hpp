// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include <memory>
namespace frame {
class symbols final {
  struct impl;
  std::unique_ptr<impl> state_;

public:
  symbols();
  ~symbols();
  json load(const std::string &path);
  void merge_map(const std::string &path);
  json at_address(std::uint64_t address);
  json describe_pointer(const std::string &name, std::uint64_t address);
  json dereference(const std::string &name, std::uint64_t address);
  json list(const std::string &filter, unsigned offset, unsigned limit, bool variables_only = false);
  json find(const std::string &name);
  json expand(const std::string &name, unsigned offset, unsigned limit);
};
} // namespace frame
