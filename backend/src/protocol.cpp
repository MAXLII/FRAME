// SPDX-License-Identifier: MIT
#include "protocol.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
namespace frame {
std::uint16_t crc(std::span<const std::uint8_t> b) {
  std::uint16_t c = 0xffff;
  for (auto v : b) {
    c ^= std::uint16_t(v) << 8;
    for (int i = 0; i < 8; ++i)
      c = static_cast<std::uint16_t>((c & 0x8000) ? (c << 1) ^ 0x1021 : c << 1);
  }
  return c;
}
bytes encode(const packet &p) {
  if (p.payload.size() > 10240)
    throw failure(2, "Payload exceeds 10 KiB");
  bytes b = {0xe8,          1,       p.src,  p.dynamic_src, p.dst,
             p.dynamic_dst, p.group, p.word, p.ack};
  put(b, static_cast<std::uint32_t>(p.payload.size()), 2);
  b.insert(b.end(), p.payload.begin(), p.payload.end());
  put(b, crc(b), 2);
  b.push_back(13);
  b.push_back(10);
  return b;
}
std::string hex(std::span<const std::uint8_t> b) {
  std::string s;
  const char *digits = "0123456789ABCDEF";
  for (auto v : b) {
    s += digits[v >> 4];
    s += digits[v & 15];
  }
  return s;
}
bytes unhex(const std::string &s) {
  bytes b;
  int hi = -1;
  for (unsigned char c : s) {
    if (std::isspace(c))
      continue;
    int v = c >= '0' && c <= '9'   ? c - '0'
            : c >= 'a' && c <= 'f' ? c - 'a' + 10
            : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                   : -1;
    if (v < 0)
      throw failure(2, "Invalid HEX");
    if (hi < 0)
      hi = v;
    else {
      b.push_back(static_cast<std::uint8_t>(hi * 16 + v));
      hi = -1;
    }
  }
  if (hi >= 0)
    throw failure(2, "Odd HEX length");
  return b;
}
std::vector<packet> parser::feed(std::span<const std::uint8_t> data) {
  if (buffer_.size() + data.size() > 4 * 1024 * 1024) {
    reset();
    ++rejected;
    throw failure(6, "RX buffer overflow");
  }
  buffer_.insert(buffer_.end(), data.begin(), data.end());
  std::vector<packet> out;
  while (!buffer_.empty()) {
    auto start = std::find(buffer_.begin(), buffer_.end(), 0xe8);
    buffer_.erase(buffer_.begin(), start);
    if (buffer_.size() < 11)
      break;
    reader r(buffer_);
    auto n = r.u16(9);
    std::size_t total = 14 + n;
    if (r.u8(1) != 1 || n > 10240) {
      buffer_.erase(buffer_.begin());
      ++rejected;
      continue;
    }
    if (buffer_.size() < total)
      break;
    if (r.u8(total - 1) != 13 ||
        r.u16(11 + n) != crc(std::span(buffer_).first(11 + n))) {
      buffer_.erase(buffer_.begin());
      ++rejected;
      continue;
    }
    packet p;
    p.src = r.u8(2);
    p.dynamic_src = r.u8(3);
    p.dst = r.u8(4);
    p.dynamic_dst = r.u8(5);
    p.group = r.u8(6);
    p.word = r.u8(7);
    p.ack = r.u8(8);
    p.payload.assign(buffer_.begin() + 11, buffer_.begin() + 11 + n);
    out.push_back(std::move(p));
    buffer_.erase(buffer_.begin(), buffer_.begin() + total);
  }
  return out;
}
json value(std::uint32_t raw, unsigned type) {
  switch (type) {
  case 0:
    return static_cast<std::int8_t>(raw);
  case 1:
    return static_cast<std::uint8_t>(raw);
  case 2:
    return static_cast<std::int16_t>(raw);
  case 3:
    return static_cast<std::uint16_t>(raw);
  case 4:
    return std::bit_cast<std::int32_t>(raw);
  case 5:
  case 7:
    return raw;
  case 6: {
    auto f = std::bit_cast<float>(raw);
    return std::isfinite(f) ? json(f) : json(nullptr);
  }
  default:
    throw failure(5, "Unknown parameter type");
  }
}
std::uint32_t raw_value(const json &v, unsigned type) {
  double number = 0;
  if (v.is_string()) {
    auto text = v.get<std::string>();
    std::size_t used = 0;
    number = std::stod(text, &used);
    if (used != text.size())
      throw failure(2, "Trailing characters in numeric value");
  } else
    number = v.get<double>();
  if (!std::isfinite(number))
    throw failure(2, "Non-finite value");
  if (type == 6) {
    auto f = static_cast<float>(number);
    if (!std::isfinite(f))
      throw failure(2, "FP32 overflow");
    return std::bit_cast<std::uint32_t>(f);
  }
  const double lows[] = {-128, 0, -32768, 0, -2147483648., 0, 0, 0},
               highs[] = {127,         255,         32767, 65535,
                          2147483647., 4294967295., 0,     4294967295.};
  if (type > 7 || number < lows[type] || number > highs[type] ||
      std::floor(number) != number)
    throw failure(2, "Value outside type range");
  return static_cast<std::uint32_t>(static_cast<std::int64_t>(number));
}
json parameter(std::span<const std::uint8_t> b, unsigned offset) {
  reader r(b);
  r.need(0, offset);
  json j = {{"name", r.text(offset, r.u8(0))},
            {"type", r.u8(1)},
            {"raw", r.u32(2)},
            {"value", value(r.u32(2), r.u8(1))}};
  if (offset >= 14) {
    j["max_raw"] = r.u32(6);
    j["min_raw"] = r.u32(10);
    j["max"] = value(r.u32(6), r.u8(1));
    j["min"] = value(r.u32(10), r.u8(1));
  }
  if (offset == 15)
    j["flags"] = r.u8(14);
  return j;
}
json decode(std::uint8_t w, std::span<const std::uint8_t> b) {
  reader r(b);
  json j;
  if (w == 2)
    return parameter(b, 6);
  if (w == 3)
    return parameter(b, 14);
  if (w == 4)
    return parameter(b, 15);
  if (w == 0x3f || w == 0x40) {
    bool wave = w == 0x40;
    unsigned offset = wave ? 14 : 10, base = wave ? 4 : 0;
    auto total = r.u32(base), first = r.u32(base + 4);
    auto count = r.u16(base + 8);
    if (first > total || count > total - first)
      throw failure(5, "Invalid batch range");
    j = {{"total", total}, {"first", first}, {"items", json::array()}};
    if (wave)
      j["tick_100us"] = r.u32(0);
    for (unsigned i = 0; i < count; ++i) {
      unsigned fixed = wave ? 6 : 15;
      auto size = fixed + r.u8(offset);
      r.need(offset, size);
      j["items"].push_back(parameter(b.subspan(offset, size), fixed));
      offset += size;
    }
    if (offset != b.size())
      throw failure(5, "Trailing batch bytes");
    return j;
  }
  if (w == 0x18 || w == 0x2f)
    return {{"id", r.u8(0)}, {"last", r.u8(1)}, {"name", r.text(4, r.u8(2))}};
  if (w == 0x19) {
    j = {{"id", r.u8(0)},
         {"status", r.u8(1)},
         {"state", r.u8(2)},
         {"ready", r.u8(3)},
         {"channels", r.u8(4)}};
    const char *names[] = {
        "count",      "write_index",           "trigger_index",
        "post_count", "trigger_display_index", "period_us",
        "tag"};
    for (unsigned i = 0; i < 7; ++i)
      j[names[i]] = r.u32(8 + 4 * i);
    return j;
  }
  if (w == 0x1a)
    return {{"id", r.u8(0)},
            {"status", r.u8(1)},
            {"index", r.u8(2)},
            {"last", r.u8(3)},
            {"name", r.text(8, r.u8(4))}};
  if (w >= 0x1b && w <= 0x1e)
    return {{"id", r.u8(0)},
            {"status", r.u8(1)},
            {"state", r.u8(2)},
            {"ready", r.u8(3)},
            {"tag", r.u32(4)}};
  if (w == 0x1f) {
    j = {{"id", r.u8(0)},   {"status", r.u8(1)}, {"index", r.u32(4)},
         {"tag", r.u32(8)}, {"last", r.u8(12)},  {"values", json::array()}};
    r.need(0, 16);
    for (unsigned i = 0; i < r.u8(3); ++i)
      j["values"].push_back(r.f32(16 + i * 4));
    return j;
  }
  if (w >= 0x30 && w <= 0x34 || w == 0x37) {
    j = {{"id", r.u8(0)},     {"status", r.u8(1)},  {"state", r.u8(2)},
         {"busy", r.u8(3)},   {"done", r.u8(4)},    {"ready", r.u8(5)},
         {"index", r.u16(8)}, {"count", r.u16(10)}, {"table_length", r.u16(12)},
         {"tag", r.u32(16)}};
    if (w == 0x30) {
      const char *names[] = {"current_hz",    "isr_hz",    "start_hz",
                             "stop_hz",       "amplitude", "settle_cycles",
                             "collect_cycles"};
      for (unsigned i = 0; i < 7; ++i)
        j[names[i]] = r.f32(20 + i * 4);
    }
    return j;
  }
  if (w == 0x35 || w == 0x36) {
    auto mag = r.f32(16);
    return {{"id", r.u8(0)},
            {"status", r.u8(1)},
            {"last", r.u8(2)},
            {"index", r.u16(4)},
            {"count", r.u16(6)},
            {"tag", r.u32(8)},
            {"frequency", r.f32(12)},
            {"magnitude", mag},
            {"db", mag > 0 && std::isfinite(mag) ? json(20 * std::log10(mag))
                                                 : json(nullptr)},
            {"phase", r.f32(20)}};
  }
  if (w == 0x20)
    return {{"version", r.u16(0)},    {"count", r.u16(2)},
            {"unit_us", r.f32(4)},    {"count_per_tick", r.u32(8)},
            {"window_ms", r.u32(12)}, {"flags", r.u8(16)}};
  if (w == 0x21)
    return {{"task_load", r.f32(0)},
            {"task_peak", r.f32(4)},
            {"interrupt_load", r.f32(8)},
            {"interrupt_peak", r.f32(12)}};
  if (w == 0x26 || w == 0x29)
    return {{"accepted", r.u8(0) != 0}, {"filter", r.u8(1)},
            {"count", r.u16(2)},        {"sequence", r.u32(4)},
            {"version", r.u32(8)},      {"reason", r.u8(12)}};
  if (w == 0x27)
    return {{"sequence", r.u32(0)}, {"index", r.u16(4)},
            {"count", r.u16(6)},    {"record_id", r.u16(8)},
            {"type", r.u8(10)},     {"name", r.text(12, r.u8(11))}};
  if (w == 0x28 || w == 0x2b) {
    j = {{"sequence", r.u32(0)}, {"count", r.u16(4)}, {"status", r.u8(6)}};
    if (w == 0x28)
      j["version"] = r.u32(8);
    return j;
  }
  if (w == 0x0c)
    return {{"success", b.empty() || r.u8(0) != 0}};
  if (w == 5 || w == 0x25 || w == 0x2e)
    return {{"success", r.u8(0) != 0}};
  if (w == 0x2c)
    return {{"success", r.u8(0) != 0},
            {"running", b.size() > 1 ? r.u8(1) : 0},
            {"unit_us", b.size() >= 4 ? r.u16(2) : 100}};
  if (w == 0x2d)
    return {{"tick", r.u32(0)}, {"line", r.u16(4)}};
  if (w == 0x38) {
    j = {{"version", r.u8(0)},
         {"status", r.u8(1)},
         {"index", r.u16(2)},
         {"count", r.u16(4)}};
    if (r.u8(1) == 0) {
      j["list_id"] = r.u16(6);
      j["node_count"] = r.u32(8);
      j["name"] = r.text(13, r.u8(12));
    }
    return j;
  }
  if (w == 0x39) {
    j = {{"version", r.u8(0)},
         {"status", r.u8(1)},
         {"list_id", r.u16(2)},
         {"index", r.u32(4)},
         {"count", r.u32(8)}};
    if (r.u8(1) == 0)
      j["address"] = r.u32(12);
    return j;
  }
  return {{"hex", hex(b)}};
}
} // namespace frame
