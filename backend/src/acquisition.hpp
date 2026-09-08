// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include <cstdint>
#include <unordered_set>
namespace frame {
// Extend a device counter without mistaking small out-of-order arrivals for
// wrap.
class tick_clock final {
  bool initialized_ = false;
  std::uint32_t last_ = 0;
  std::uint64_t base_ = 0;

public:
  std::uint64_t wraps = 0, out_of_order = 0;
  std::uint64_t extend(std::uint32_t tick) {
    if (initialized_ && tick < last_) {
      if (last_ - tick > 0x80000000u) {
        base_ += 0x100000000ull;
        ++wraps;
      } else {
        ++out_of_order;
        return base_ + tick;
      }
    }
    initialized_ = true;
    last_ = tick;
    return base_ + tick;
  }
};
class batch_integrity final {
  bool initialized_ = false;
  std::uint32_t tick_ = 0, total_ = 0;
  std::unordered_set<unsigned> indexes_;

public:
  std::uint64_t missing = 0, duplicates = 0, changed = 0;
  void observe(std::uint32_t tick, unsigned total, unsigned first,
               unsigned count) {
    if (total > 100000 || first > total || count > total - first)
      throw failure(6, "Wave batch range exceeds capacity");
    if (!initialized_ || tick != tick_) {
      if (initialized_ && indexes_.size() < total_)
        missing += total_ - indexes_.size();
      indexes_.clear();
      tick_ = tick;
      total_ = total;
      initialized_ = true;
    } else if (total != total_) {
      ++changed;
      throw failure(6, "Wave batch directory changed within sample");
    }
    for (unsigned i = first; i < first + count; ++i)
      if (!indexes_.insert(i).second)
        ++duplicates;
  }
  std::uint64_t pending_missing() const {
    return initialized_ && indexes_.size() < total_ ? total_ - indexes_.size()
                                                    : 0;
  }
};
} // namespace frame
