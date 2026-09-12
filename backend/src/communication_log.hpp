// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include <Windows.h>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <mutex>

namespace frame {
// Entity: optional per-runtime communication evidence, never protocol state.
// Prior: diagnostic failures must not fail communication; retain at most two 8 MiB files.
// Time: UTC milliseconds correlate processes; steady milliseconds measure stalls.
class communication_log final {
  std::mutex mutex_;
  std::ofstream output_;
  std::filesystem::path path_;
  std::size_t size_ = 0;
  const std::chrono::steady_clock::time_point origin_ = std::chrono::steady_clock::now();
public:
  communication_log() noexcept {
    try {
      const auto directory = _wgetenv(L"FRAME_COMM_LOG_DIR");
      if (!directory || !*directory) return;
      std::filesystem::create_directories(directory);
      const auto stamp = std::chrono::duration_cast<std::chrono::microseconds>(
          std::chrono::system_clock::now().time_since_epoch()).count();
      path_ = std::filesystem::path(directory) / ("comm-" + std::to_string(GetCurrentProcessId()) + "-" + std::to_string(stamp) + ".jsonl");
      output_.open(path_, std::ios::binary);
    } catch (...) { }
  }
  bool enabled() const noexcept { return !path_.empty(); }
  void write(const char *event, json data = json::object()) noexcept {
    if (!enabled()) return;
    try {
      std::lock_guard lock(mutex_);
      if (!output_) return;
      data["event"] = event;
      data["utc_ms"] = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
      data["elapsed_ms"] = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - origin_).count();
      data["thread"] = GetCurrentThreadId();
      auto line = data.dump(-1, ' ', false, json::error_handler_t::replace) + "\n";
      if (size_ + line.size() > 8 * 1024 * 1024) {
        output_.close();
        auto previous = path_; previous += ".previous";
        std::error_code error;
        std::filesystem::remove(previous, error);
        std::filesystem::rename(path_, previous, error);
        output_.open(path_, std::ios::binary | std::ios::trunc);
        size_ = 0;
      }
      output_ << line; output_.flush(); size_ += line.size();
    } catch (...) { }
  }
};
} // namespace frame
