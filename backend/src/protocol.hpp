// SPDX-License-Identifier: MIT
#pragma once
#include <bit>
#include <cstdint>
#include <nlohmann/json.hpp>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>
namespace frame {
using json = nlohmann::json;
using bytes = std::vector<std::uint8_t>;
struct failure : std::runtime_error {
  int code;
  failure(int value, const std::string &message)
      : std::runtime_error(message), code(value) {}
};
class reader final {
  std::span<const std::uint8_t> data_;

public:
  explicit reader(std::span<const std::uint8_t> data) : data_(data) {}
  void need(std::size_t p, std::size_t n) const {
    if (p > data_.size() || n > data_.size() - p)
      throw failure(5, "Truncated payload");
  }
  std::uint8_t u8(std::size_t p) const {
    need(p, 1);
    return data_[p];
  }
  std::uint16_t u16(std::size_t p) const {
    need(p, 2);
    return data_[p] | (std::uint16_t(data_[p + 1]) << 8);
  }
  std::uint32_t u32(std::size_t p) const {
    need(p, 4);
    return u16(p) | (std::uint32_t(u16(p + 2)) << 16);
  }
  float f32(std::size_t p) const { return std::bit_cast<float>(u32(p)); }
  std::string text(std::size_t p, std::size_t n) const {
    need(p, n);
    return {reinterpret_cast<const char *>(data_.data() + p), n};
  }
};
inline void put(bytes &b, std::uint32_t v, unsigned n) {
  for (unsigned i = 0; i < n; ++i)
    b.push_back(static_cast<std::uint8_t>(v >> (8 * i)));
}
inline void putf(bytes &b, float v) {
  put(b, std::bit_cast<std::uint32_t>(v), 4);
}
struct packet {
  std::uint8_t src = 2, dynamic_src = 0, dst = 1, dynamic_dst = 0, group = 1,
               word = 0, ack = 1;
  bytes payload;
};
std::uint16_t crc(std::span<const std::uint8_t> b);
bytes encode(const packet &p);
bytes unhex(const std::string &s);
std::string hex(std::span<const std::uint8_t> b);
class parser final {
  bytes buffer_;

public:
  std::uint64_t rejected = 0;
  std::vector<packet> feed(std::span<const std::uint8_t> data);
  void reset() { buffer_.clear(); }
};
json decode(std::uint8_t word, std::span<const std::uint8_t> b);
json parameter(std::span<const std::uint8_t> b, unsigned name_offset);
json value(std::uint32_t raw, unsigned type);
std::uint32_t raw_value(const json &v, unsigned type);
} // namespace frame
