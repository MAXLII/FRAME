// SPDX-License-Identifier: MIT
#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <string_view>
#include <vector>

namespace frame {
// A decoder owns its partial-frame state. Feed boundaries are not frame boundaries.
class StreamDecoder {
public:
  virtual ~StreamDecoder() = default;
  virtual std::string_view Name() const noexcept = 0;
  virtual void Feed(std::span<const std::uint8_t> data) = 0;
  virtual void Reset() noexcept = 0;
};

// One link, one executor. Registered consumers see the same bytes in wire order.
class StreamLink final {
  std::vector<std::unique_ptr<StreamDecoder>> decoders_;
  std::vector<std::uint8_t> pending_;
  std::size_t offset_ = 0;
  std::size_t capacity_;
  bool started_ = false, dispatching_ = false;

public:
  explicit StreamLink(std::size_t capacity = 256 * 1024);
  void AddDecoder(std::unique_ptr<StreamDecoder> decoder);
  void Push(std::span<const std::uint8_t> data);
  std::size_t Process(std::size_t byteBudget = 16 * 1024);
  void Reset();
  std::size_t PendingBytes() const noexcept { return pending_.size() - offset_; }
  std::size_t DecoderCount() const noexcept { return decoders_.size(); }
};
} // namespace frame
