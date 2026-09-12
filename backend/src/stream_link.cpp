// SPDX-License-Identifier: MIT
#include "stream_link.hpp"
#include <algorithm>
#include <stdexcept>
#include <utility>

namespace frame {
StreamLink::StreamLink(std::size_t capacity) : capacity_(capacity) {
  if (capacity == 0) throw std::invalid_argument("Stream link capacity must be positive");
}
void StreamLink::AddDecoder(std::unique_ptr<StreamDecoder> decoder) {
  if (started_ || dispatching_) throw std::logic_error("Register decoders before receiving data");
  if (!decoder || decoder->Name().empty()) throw std::invalid_argument("Named stream decoder required");
  if (decoders_.size() >= 8) throw std::length_error("Stream decoder quota exceeded");
  for (const auto &registered : decoders_)
    if (registered->Name() == decoder->Name()) throw std::invalid_argument("Duplicate stream decoder");
  decoders_.push_back(std::move(decoder));
}
void StreamLink::Push(std::span<const std::uint8_t> data) {
  if (dispatching_) throw std::logic_error("Reentrant stream input");
  if (data.empty()) return;
  if (decoders_.empty()) throw std::logic_error("Stream link has no decoder");
  // Reject the whole input instead of silently dropping bytes from a partial frame.
  if (data.size() > capacity_ - PendingBytes()) throw std::length_error("Stream receive queue exhausted");
  if (offset_) { pending_.erase(pending_.begin(), pending_.begin() + offset_); offset_ = 0; }
  pending_.insert(pending_.end(), data.begin(), data.end());
  started_ = true;
}
std::size_t StreamLink::Process(std::size_t byteBudget) {
  if (dispatching_) throw std::logic_error("Reentrant stream processing");
  const auto count = std::min(byteBudget, PendingBytes());
  if (count == 0) return 0;
  dispatching_ = true;
  try {
    const auto data = std::span<const std::uint8_t>(pending_).subspan(offset_, count);
    for (auto &decoder : decoders_) decoder->Feed(data);
    offset_ += count;
    if (offset_ == pending_.size()) { pending_.clear(); offset_ = 0; }
    dispatching_ = false;
    return count;
  } catch (...) {
    // Some consumers may already have emitted frames; never replay this input.
    dispatching_ = false;
    Reset();
    throw;
  }
}
void StreamLink::Reset() {
  if (dispatching_) throw std::logic_error("Cannot reset a link inside its decoder");
  pending_.clear(); offset_ = 0;
  for (auto &decoder : decoders_) decoder->Reset();
}
} // namespace frame
