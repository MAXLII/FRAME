// SPDX-License-Identifier: MIT
#pragma once
#include "transport.hpp"
#include <filesystem>
#include <functional>
namespace frame {
// One Commander process per logical J-Link session, owned by its executor.
class commander final {
  HANDLE process_ = nullptr, input_ = nullptr, output_ = nullptr;
  std::filesystem::path directory_;
  std::uint64_t sequence_ = 0;
  std::string drain();

public:
  std::string identity;
  ~commander() { close(); }
  void close() noexcept;
  void open(const std::string &executable, const std::string &device,
            unsigned probe, const std::function<void()> &guard,
            const std::string &interface_name = "SWD", unsigned speed = 1000);
  std::string exchange(const std::string &command,
                       const std::function<void()> &guard);
  bool alive() const {
    return process_ && WaitForSingleObject(process_, 0) == WAIT_TIMEOUT;
  }
};
} // namespace frame
