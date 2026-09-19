// SPDX-License-Identifier: MIT
#include "protocol.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <string_view>
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
/* =============================================================================
 * COMM v1 (0xE9) codecs
 * =============================================================================
 */
namespace {
// Preset codebook shared with the device firmware. Entry layout must stay in
// sync with code/lib/codec_dict.c.
constexpr std::string_view kCodebookEntries[] = {
    "counter", "led_mask", "temperature", "voltage", "current",
    "power",    "frequency", "status",      "error",   "scope",
    "sfra",     "perf",      "trace",       "ok",      "fail",
    "version",
};
constexpr unsigned kCodebookCount = 16;
constexpr unsigned kLiteralMax = 128, kRepeatMax = 130, kWindow = 256;
bool fail(unsigned &len) {
  len = 0;
  return false;
}
bool encode_literals(bytes &out, unsigned capacity, unsigned limit,
                     std::span<const std::uint8_t> run, unsigned &out_len) {
  // One literal token covers at most kLiteralMax bytes.
  for (std::size_t base = 0; base < run.size(); base += kLiteralMax) {
    const unsigned chunk = static_cast<unsigned>(
        std::min<std::size_t>(kLiteralMax, run.size() - base));
    if (out_len + 1u + chunk > capacity || out_len + 1u + chunk >= limit)
      return false;
    out[out_len++] = static_cast<std::uint8_t>(chunk - 1);
    std::copy_n(run.data() + base, chunk, out.begin() + out_len);
    out_len += chunk;
  }
  return true;
}
bool rle_encode(std::span<const std::uint8_t> input, unsigned limit,
                bytes &output) {
  unsigned out_len = 0;
  std::size_t index = 0;
  while (index < input.size()) {
    std::size_t run = 1;
    while (index + run < input.size() && input[index + run] == input[index] &&
           run < kRepeatMax)
      ++run;
    if (run >= 3) {
      if (out_len + 2 > output.size() || out_len + 2 >= limit)
        return fail(out_len);
      output[out_len++] = static_cast<std::uint8_t>(0x80u | (run - 3));
      output[out_len++] = input[index];
      index += run;
    } else {
      std::size_t literal = 0, start = index;
      while (index < input.size() && literal < kLiteralMax) {
        std::size_t ahead = 1;
        while (index + ahead < input.size() &&
               input[index + ahead] == input[index] && ahead < kRepeatMax)
          ++ahead;
        if (ahead >= 3 || literal + ahead > kLiteralMax)
          break;
        literal += ahead;
        index += ahead;
      }
      if (out_len + 1 + literal > output.size() ||
          out_len + 1 + literal >= limit)
        return fail(out_len);
      output[out_len++] = static_cast<std::uint8_t>(literal - 1);
      std::copy_n(input.data() + start, literal, output.begin() + out_len);
      out_len += static_cast<unsigned>(literal);
    }
  }
  if (out_len == 0 || out_len >= limit)
    return fail(out_len);
  output.resize(out_len);
  return true;
}
bool rle_decode(std::span<const std::uint8_t> input, unsigned limit,
                bytes &output) {
  unsigned out_len = 0;
  std::size_t index = 0;
  while (index < input.size()) {
    const auto token = input[index++];
    if (token <= 0x7F) {
      const unsigned literal = token + 1u;
      if (literal > input.size() - index || out_len + literal > output.size() ||
          out_len + literal >= limit)
        return fail(out_len);
      std::copy_n(input.data() + index, literal, output.begin() + out_len);
      out_len += literal;
      index += literal;
    } else {
      const unsigned repeat = (token & 0x7F) + 3u;
      if (index >= input.size() || out_len + repeat > output.size() ||
          out_len + repeat >= limit)
        return fail(out_len);
      std::fill_n(output.begin() + out_len, repeat, input[index++]);
      out_len += repeat;
    }
  }
  if (out_len == 0 || out_len >= limit)
    return fail(out_len);
  output.resize(out_len);
  return true;
}
bool dict_encode(std::span<const std::uint8_t> input, unsigned limit,
                 bytes &output) {
  unsigned out_len = 0;
  std::size_t index = 0, literal_start = 0;
  unsigned literal_len = 0;
  while (index < input.size()) {
    unsigned best_len = 0, best_index = 0;
    for (unsigned entry = 0; entry < kCodebookCount; ++entry) {
      const auto &text = kCodebookEntries[entry];
      if (text.size() > input.size() - index)
        continue;
      if (std::string_view(reinterpret_cast<const char *>(input.data() + index),
                           text.size()) != text)
        continue;
      if (text.size() > best_len ||
          (text.size() == best_len && entry < best_index)) {
        best_len = static_cast<unsigned>(text.size());
        best_index = entry;
      }
    }
    if (best_len == 0) {
      ++literal_len;
      ++index;
      if (literal_len == kLiteralMax) {
        if (!encode_literals(output, static_cast<unsigned>(output.size()), limit,
                             input.subspan(literal_start, literal_len), out_len))
          return fail(out_len);
        literal_start = index;
        literal_len = 0;
      }
    } else {
      if (literal_len != 0) {
        if (!encode_literals(output, static_cast<unsigned>(output.size()), limit,
                             input.subspan(literal_start, literal_len), out_len))
          return fail(out_len);
        literal_len = 0;
      }
      if (out_len + 1 >= limit || out_len + 1 > output.size())
        return fail(out_len);
      output[out_len++] = static_cast<std::uint8_t>(0x80u | best_index);
      index += best_len;
      literal_start = index;
    }
  }
  if (literal_len != 0 &&
      !encode_literals(output, static_cast<unsigned>(output.size()), limit,
                       input.subspan(literal_start, literal_len), out_len))
    return fail(out_len);
  if (out_len == 0 || out_len >= limit)
    return fail(out_len);
  output.resize(out_len);
  return true;
}
bool dict_decode(std::span<const std::uint8_t> input, unsigned limit,
                 bytes &output) {
  unsigned out_len = 0;
  std::size_t index = 0;
  while (index < input.size()) {
    const auto token = input[index++];
    if (token <= 0x7F) {
      const unsigned literal = token + 1u;
      if (literal > input.size() - index || out_len + literal > output.size() ||
          out_len + literal >= limit)
        return fail(out_len);
      std::copy_n(input.data() + index, literal, output.begin() + out_len);
      out_len += literal;
      index += literal;
    } else if (token <= 0xBF) {
      const unsigned entry = token & 0x3F;
      if (entry >= kCodebookCount)
        return fail(out_len);
      const auto &text = kCodebookEntries[entry];
      if (out_len + text.size() > output.size() ||
          out_len + text.size() >= limit)
        return fail(out_len);
      std::copy(text.begin(), text.end(), output.begin() + out_len);
      out_len += static_cast<unsigned>(text.size());
    } else
      return fail(out_len);
  }
  if (out_len == 0 || out_len >= limit)
    return fail(out_len);
  output.resize(out_len);
  return true;
}
bool lzss_encode(std::span<const std::uint8_t> input, unsigned limit,
                 bytes &output) {
  unsigned out_len = 0;
  std::size_t index = 0, literal_start = 0;
  unsigned literal_len = 0;
  while (index < input.size()) {
    unsigned best_len = 0, best_offset = 0;
    const unsigned max_offset = static_cast<unsigned>(
        std::min<std::size_t>(kWindow, index));
    for (unsigned offset = 1; offset <= max_offset; ++offset) {
      unsigned match = 0;
      while (match < kRepeatMax && index + match < input.size() &&
             input[index + match] == input[index - offset + match])
        ++match;
      if (match > best_len) {
        best_len = match;
        best_offset = offset;
        if (match == kRepeatMax)
          break;
      }
    }
    if (best_len >= 3) {
      if (literal_len != 0) {
        if (!encode_literals(output, static_cast<unsigned>(output.size()), limit,
                             input.subspan(literal_start, literal_len), out_len))
          return fail(out_len);
        literal_len = 0;
      }
      if (out_len + 2 >= limit || out_len + 2 > output.size())
        return fail(out_len);
      output[out_len++] = static_cast<std::uint8_t>(0x80u | (best_len - 3));
      output[out_len++] = static_cast<std::uint8_t>(best_offset - 1);
      index += best_len;
      literal_start = index;
    } else {
      ++literal_len;
      ++index;
      if (literal_len == kLiteralMax) {
        if (!encode_literals(output, static_cast<unsigned>(output.size()), limit,
                             input.subspan(literal_start, literal_len), out_len))
          return fail(out_len);
        literal_start = index;
        literal_len = 0;
      }
    }
  }
  if (literal_len != 0 &&
      !encode_literals(output, static_cast<unsigned>(output.size()), limit,
                       input.subspan(literal_start, literal_len), out_len))
    return fail(out_len);
  if (out_len == 0 || out_len >= limit)
    return fail(out_len);
  output.resize(out_len);
  return true;
}
bool lzss_decode(std::span<const std::uint8_t> input, unsigned limit,
                 bytes &output) {
  unsigned out_len = 0;
  std::size_t index = 0;
  while (index < input.size()) {
    const auto token = input[index++];
    if (token <= 0x7F) {
      const unsigned literal = token + 1u;
      if (literal > input.size() - index || out_len + literal > output.size() ||
          out_len + literal >= limit)
        return fail(out_len);
      std::copy_n(input.data() + index, literal, output.begin() + out_len);
      out_len += literal;
      index += literal;
    } else {
      const unsigned ref_len = (token & 0x7F) + 3u;
      if (index >= input.size())
        return fail(out_len);
      const unsigned offset = input[index++] + 1u;
      if (offset > out_len || out_len + ref_len > output.size() ||
          out_len + ref_len >= limit)
        return fail(out_len);
      for (unsigned i = 0; i < ref_len; ++i)
        output[out_len + i] = output[out_len + i - offset];
      out_len += ref_len;
    }
  }
  if (out_len == 0 || out_len >= limit)
    return fail(out_len);
  output.resize(out_len);
  return true;
}
// CODEC=100: nibble zero-count variable-length code. Each nibble n encodes
// as 1^k + 0^(m+1) + 1 with k = n >> 2 and m = n & 3; bits fill bytes
// MSB-first and the trailing bits of the last byte are padded with ones.
bool zero_encode(std::span<const std::uint8_t> input, unsigned limit,
                 bytes &output) {
  std::uint64_t bit_count = 0;
  unsigned out_len = 0;
  auto put_bit = [&](unsigned bit) {
    if (bit)
      output[bit_count >> 3] |= static_cast<std::uint8_t>(1u << (7u - (bit_count & 7u)));
    ++bit_count;
  };
  for (auto value : input) {
    for (int nibble_index = 0; nibble_index < 2; ++nibble_index) {
      const unsigned nibble =
          nibble_index == 0 ? value >> 4 : value & 0x0F;
      const unsigned segment = nibble >> 2;
      const unsigned offset = nibble & 3u;
      const auto required = (bit_count + segment + offset + 2u + 7u) / 8u;
      if (required > output.size() || required >= limit)
        return fail(out_len);
      for (unsigned i = 0; i < segment; ++i)
        put_bit(1);
      for (unsigned i = 0; i <= offset; ++i)
        put_bit(0);
      put_bit(1);
      if ((bit_count + 7u) / 8u >= limit)
        return fail(out_len);
    }
  }
  while ((bit_count & 7u) != 0u)
    put_bit(1);
  out_len = static_cast<unsigned>(bit_count / 8u);
  if (out_len == 0 || out_len >= limit || out_len > output.size())
    return fail(out_len);
  output.resize(out_len);
  return true;
}
bool zero_decode(std::span<const std::uint8_t> input, unsigned limit,
                 bytes &output) {
  const auto bit_total = input.size() * 8u;
  std::size_t bit_index = 0;
  unsigned out_len = 0;
  unsigned pending_high = 0;
  bool has_pending = false;
  auto get_bit = [&](std::size_t index) {
    return (input[index >> 3] >> (7u - (index & 7u))) & 1u;
  };
  while (bit_index < bit_total) {
    unsigned segment = 0;
    while (bit_index < bit_total && get_bit(bit_index) == 1u) {
      ++segment;
      ++bit_index;
    }
    if (bit_index >= bit_total)
      break; // trailing ones are byte padding
    if (segment > 3)
      return fail(out_len);
    unsigned offset_count = 0;
    while (bit_index < bit_total && get_bit(bit_index) == 0u) {
      ++offset_count;
      ++bit_index;
    }
    if (bit_index >= bit_total)
      return fail(out_len);
    ++bit_index; // terminating '1'
    if (offset_count == 0 || offset_count > 4)
      return fail(out_len);
    const unsigned nibble = (segment << 2) | (offset_count - 1u);
    if (!has_pending) {
      pending_high = nibble;
      has_pending = true;
    } else {
      if (out_len >= output.size() || out_len + 1u >= limit)
        return fail(out_len);
      output[out_len++] = static_cast<std::uint8_t>((pending_high << 4) | nibble);
      has_pending = false;
    }
  }
  if (has_pending || out_len == 0 || out_len >= limit)
    return fail(out_len);
  output.resize(out_len);
  return true;
}
} // namespace
std::uint8_t sum(std::span<const std::uint8_t> b) {
  std::uint8_t value = 0;
  for (auto v : b)
    value = static_cast<std::uint8_t>(value + v);
  if (value == 0x00)
    return 0x55;
  if (value == 0xFF)
    return 0xAA;
  return value;
}
std::uint32_t codebook_crc32() {
  std::uint32_t crc = 0xFFFFFFFFu;
  for (const auto &entry : kCodebookEntries) {
    for (unsigned char c : entry) {
      crc ^= c;
      for (int i = 0; i < 8; ++i)
        crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
  }
  return crc ^ 0xFFFFFFFFu;
}
bool codec_encode(codec kind, std::span<const std::uint8_t> input,
                  unsigned limit, bytes &output) {
  if (input.empty() || limit == 0 || output.empty())
    return false;
  output.assign(output.size(), 0);
  switch (kind) {
  case codec::dict:
    return dict_encode(input, limit, output);
  case codec::rle:
    return rle_encode(input, limit, output);
  case codec::lzss:
    return lzss_encode(input, limit, output);
  case codec::zero:
    return zero_encode(input, limit, output);
  default:
    return false;
  }
}
bool codec_decode(codec kind, std::span<const std::uint8_t> input,
                  unsigned limit, bytes &output) {
  if (input.empty() || limit == 0 || output.empty())
    return false;
  output.assign(output.size(), 0);
  switch (kind) {
  case codec::dict:
    return dict_decode(input, limit, output);
  case codec::rle:
    return rle_decode(input, limit, output);
  case codec::lzss:
    return lzss_decode(input, limit, output);
  case codec::zero:
    return zero_decode(input, limit, output);
  default:
    return false;
  }
}
bytes codec_select_request() {
  bytes payload = {1, 0, 1, 0, 0, 0, 0}; // codec=DICT, codebook_id=0, version=1
  const auto crc32 = codebook_crc32();
  payload[3] = static_cast<std::uint8_t>(crc32 & 0xFFu);
  payload[4] = static_cast<std::uint8_t>((crc32 >> 8) & 0xFFu);
  payload[5] = static_cast<std::uint8_t>((crc32 >> 16) & 0xFFu);
  payload[6] = static_cast<std::uint8_t>((crc32 >> 24) & 0xFFu);
  return payload;
}
bool is_codec_select_response(const packet &p) {
  if (p.group != 0 || p.word != 0 || p.ack == 0 || p.payload.size() != 8 ||
      p.payload[0] != 0)
    return false;
  const auto crc32 = codebook_crc32();
  return p.sop == 0xE9 && p.payload[1] == 1 && p.payload[2] == 0 &&
         p.payload[3] == 1 && reader(p.payload).u32(4) == crc32;
}
bytes encode_v1(const packet &p, bool allow_compression) {
  if (p.src > 15 || p.dst > 15 || p.dynamic_src > 7 || p.dynamic_dst > 7 ||
      p.group > 15 || p.word > 63 || p.seq > 7)
    throw failure(2, "COMM v1 field outside range");
  if (p.payload.size() > 256)
    throw failure(2, "COMM v1 payload exceeds 256 bytes");
  const bool pure = p.payload.empty();
  const bool select = p.group == 0 && p.word == 0;
  bytes frame;
  frame.reserve(263);
  frame.push_back(0xE9);
  std::uint32_t msg = static_cast<std::uint32_t>(p.seq) |
                      (static_cast<std::uint32_t>(p.dst) << 3) |
                      (static_cast<std::uint32_t>(p.dynamic_dst) << 7) |
                      (static_cast<std::uint32_t>(p.src) << 10) |
                      (static_cast<std::uint32_t>(p.dynamic_src) << 14) |
                      (static_cast<std::uint32_t>(p.group) << 17) |
                      (static_cast<std::uint32_t>(p.word) << 21);
  unsigned best_codec = 0, best_len = static_cast<unsigned>(p.payload.size());
  bytes data;
  if (!pure) {
    data = p.payload;
    const unsigned raw = static_cast<unsigned>(p.payload.size());
    const unsigned min_saved =
        raw <= 16 ? 2u : std::max(2u, (raw + 15u) / 16u);
    if (allow_compression && !select && raw > min_saved) {
      const auto consider = [&](codec kind) {
        unsigned limit = std::min(best_len, raw - min_saved + 1u);
        bytes candidate(256, 0);
        if (!codec_encode(kind, p.payload, limit, candidate))
          return;
        if (candidate.size() < best_len) {
          data = std::move(candidate);
          best_len = static_cast<unsigned>(data.size());
          best_codec = static_cast<unsigned>(kind);
        }
      };
      consider(codec::dict);
      if (raw > 16)
        consider(codec::rle);
      if (raw >= 64)
        consider(codec::lzss);
      consider(codec::zero);
    }
  }
  msg |= static_cast<std::uint32_t>(best_codec) << 27;
  if (pure)
    msg |= 1u << 30;
  if (p.ack)
    msg |= 1u << 31;
  put(frame, msg, 4);
  if (!pure) {
    frame.push_back(static_cast<std::uint8_t>(best_len == 256 ? 0 : best_len));
    frame.insert(frame.end(), data.begin(), data.end());
  }
  frame.push_back(sum(frame));
  return frame;
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
    // Skip to the next frame candidate of either protocol.
    const auto pos_e8 = std::find(buffer_.begin(), buffer_.end(), 0xe8);
    const auto pos_e9 = std::find(buffer_.begin(), buffer_.end(), 0xe9);
    const auto pos = std::min(pos_e8, pos_e9);
    buffer_.erase(buffer_.begin(), pos);
    if (buffer_.empty())
      break;
    if (buffer_.front() == 0xe9) {
      // COMM v1 frame: | SOP | MSG(4) | [LEN | DATA...] | SUM |
      if (buffer_.size() < 5)
        break;
      const auto msg = static_cast<std::uint32_t>(buffer_[1]) |
                       (static_cast<std::uint32_t>(buffer_[2]) << 8) |
                       (static_cast<std::uint32_t>(buffer_[3]) << 16) |
                       (static_cast<std::uint32_t>(buffer_[4]) << 24);
      const unsigned cmd = (msg >> 30) & 1u;
      const unsigned msg_codec = (msg >> 27) & 7u;
      if (msg_codec > 4 || (cmd == 1u && msg_codec != 0)) {
        buffer_.erase(buffer_.begin());
        ++rejected;
        continue;
      }
      if (cmd == 1u) {
        if (msg_codec != 0 || buffer_.size() < 6) {
          if (buffer_.size() < 6)
            break;
          buffer_.erase(buffer_.begin());
          ++rejected;
          continue;
        }
        if (sum(std::span(buffer_).first(5)) != buffer_[5]) {
          buffer_.erase(buffer_.begin());
          ++rejected;
          continue;
        }
        packet p;
        p.sop = 0xE9;
        p.seq = static_cast<std::uint8_t>(msg & 7u);
        p.dst = static_cast<std::uint8_t>((msg >> 3) & 0xFu);
        p.dynamic_dst = static_cast<std::uint8_t>(((msg >> 7) & 1u) |
                                                  (((msg >> 8) & 3u) << 1));
        p.src = static_cast<std::uint8_t>((msg >> 10) & 0xFu);
        p.dynamic_src = static_cast<std::uint8_t>(((msg >> 14) & 3u) |
                                                  (((msg >> 16) & 1u) << 2));
        p.group = static_cast<std::uint8_t>((msg >> 17) & 0xFu);
        p.word = static_cast<std::uint8_t>(((msg >> 21) & 7u) |
                                           (((msg >> 24) & 7u) << 3));
        p.ack = static_cast<std::uint8_t>((msg >> 31) & 1u);
        out.push_back(std::move(p));
        buffer_.erase(buffer_.begin(), buffer_.begin() + 6);
        continue;
      }
      if (buffer_.size() < 6)
        break;
      const std::size_t length = buffer_[5] == 0 ? 256 : buffer_[5];
      const std::size_t total = 7 + length;
      if (buffer_.size() < total)
        break;
      if (sum(std::span(buffer_).first(total - 1)) != buffer_[total - 1]) {
        buffer_.erase(buffer_.begin());
        ++rejected;
        continue;
      }
      packet p;
      p.sop = 0xE9;
      p.seq = static_cast<std::uint8_t>(msg & 7u);
      p.dst = static_cast<std::uint8_t>((msg >> 3) & 0xFu);
      p.dynamic_dst = static_cast<std::uint8_t>(((msg >> 7) & 1u) |
                                                (((msg >> 8) & 3u) << 1));
      p.src = static_cast<std::uint8_t>((msg >> 10) & 0xFu);
      p.dynamic_src = static_cast<std::uint8_t>(((msg >> 14) & 3u) |
                                                (((msg >> 16) & 1u) << 2));
      p.group = static_cast<std::uint8_t>((msg >> 17) & 0xFu);
      p.word = static_cast<std::uint8_t>(((msg >> 21) & 7u) |
                                         (((msg >> 24) & 7u) << 3));
      p.ack = static_cast<std::uint8_t>((msg >> 31) & 1u);
      const auto wire = std::span(buffer_).subspan(6, length);
      if (msg_codec == 0) {
        p.payload.assign(wire.begin(), wire.end());
      } else {
        bytes decoded(256, 0);
        if (!codec_decode(static_cast<codec>(msg_codec), wire, 257, decoded)) {
          buffer_.erase(buffer_.begin());
          ++rejected;
          continue;
        }
        p.payload = std::move(decoded);
      }
      out.push_back(std::move(p));
      buffer_.erase(buffer_.begin(), buffer_.begin() + total);
      continue;
    }
    // Legacy 0xE8 frame path.
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
