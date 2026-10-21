// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include <algorithm>
#include <fstream>
#include <iterator>
namespace frame {
// SHUT is the payload container. The existing FRAME 01/08..0B wire schema is unchanged.
class firmware_image final {
  bytes data_;
  static std::uint32_t checksum(std::span<const std::uint8_t> data, unsigned first) {
    std::uint32_t value = UINT32_MAX;
    for (std::size_t i = 0; i < data.size(); ++i) {
      value ^= i >= first && i < 116 ? 0 : data[i];
      for (unsigned n = 0; n < 8; ++n)
        value = (value >> 1) ^ ((value & 1) ? 0xEDB88320u : 0u);
    }
    return value ^ UINT32_MAX;
  }
public:
  explicit firmware_image(bytes data) : data_(std::move(data)) {
    reader r(data_);
    if (data_.size() < 128 || data_.size() > 512 * 1024 || r.u32(0) != 0x54554853 ||
        r.u32(4) != 1 || r.u32(8) != 128 || r.u32(12) != data_.size() ||
        r.u32(16) == 0 || r.u32(16) > 255 || r.u32(24) != 1 || r.u32(28) != 0x507 ||
        r.u32(88) != 1 || r.u32(112) != 0x434F4D54 ||
        r.u32(116) || r.u32(120) || r.u32(124))
      throw failure(2, "Invalid SHUT image header, size, module or ABI");
    if (checksum(data_, 104) != r.u32(104) || checksum(std::span(data_).first(128), 108) != r.u32(108))
      throw failure(2, "SHUT image/header CRC mismatch");
  }
  static firmware_image load(const std::string &path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file || file.tellg() < 128 || file.tellg() > 512 * 1024) throw failure(2, "Unreadable or oversized SHUT image");
    bytes data(static_cast<std::size_t>(file.tellg())); file.seekg(0);
    if (!file.read(reinterpret_cast<char *>(data.data()), static_cast<std::streamsize>(data.size())))
      throw failure(2, "Incomplete image read");
    return firmware_image(std::move(data));
  }
  std::size_t size() const { return data_.size(); }
  std::uint32_t module() const { return reader(data_).u32(16); }
  json describe() const {
    reader r(data_);
    return {{"format","SHUT-v1"},{"module",module()},{"version",r.u32(20)},
      {"bytes",size()},{"entry",r.u32(36)},{"irq_count",r.u32(84)},
      {"image_crc32",r.u32(104)},{"hardware_tested",false}};
  }
  bytes info(bool force) const {
    bytes result{static_cast<std::uint8_t>(module())};
    put(result, reader(data_).u32(20), 4); put(result, static_cast<std::uint32_t>(size()), 4);
    result.push_back(force ? 2 : 1); return result;
  }
  bytes block(std::size_t offset) const {
    if (offset >= size() || offset % 1024) throw failure(2, "Invalid firmware block offset");
    const auto count = std::min<std::size_t>(1024, size() - offset);
    bytes result; put(result, static_cast<std::uint32_t>(offset), 4);
    result.push_back(static_cast<std::uint8_t>(module())); put(result, static_cast<std::uint32_t>(count), 2);
    result.insert(result.end(), data_.begin() + offset, data_.begin() + offset + count);
    result.resize(1031, 0xFF); put(result, crc(result), 2); return result;
  }
  bytes end() const { bytes result; put(result, crc(data_), 2); return result; }
};
} // namespace frame
