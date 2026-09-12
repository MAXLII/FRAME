// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include "stream_link.hpp"
#include <functional>
#include <utility>

namespace frame {
// Adapter for the existing FRAME wire protocol; other protocols define their own
// decoder and output types rather than manufacturing FRAME packets.
class FrameStreamDecoder final : public StreamDecoder {
  parser &parser_;
  std::function<void(packet)> onPacket_;

public:
  FrameStreamDecoder(parser &decoder, std::function<void(packet)> onPacket)
      : parser_(decoder), onPacket_(std::move(onPacket)) {}
  std::string_view Name() const noexcept override { return "frame-v1"; }
  void Feed(std::span<const std::uint8_t> data) override {
    for (auto &item : parser_.feed(data)) onPacket_(std::move(item));
  }
  void Reset() noexcept override { parser_.reset(); }
};
} // namespace frame
