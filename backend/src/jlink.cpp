// SPDX-License-Identifier: MIT
#include "commander.hpp"
#include "runtime.hpp"
#include "symbols.hpp"
#include <filesystem>
#include <fstream>
#include <regex>
#include <sstream>
#include <bit>
#include <cmath>
namespace frame {
static std::string quote_arg(const std::string &s) {
  if (s.find('"') != std::string::npos || s.find('\n') != std::string::npos ||
      s.find('\r') != std::string::npos)
    throw failure(2, "Invalid process argument");
  return "\"" + s + "\"";
}
json runtime::jlink(operation &op) {
  auto &q = op.command;
  auto action = q.value("action", std::string("connect"));
  if (action == "disconnect") {
    if (probe_session)
      probe_session->close();
    return {{"connected", false}};
  }
  if (action == "detect") {
    auto directory = std::filesystem::path(wide(q.at("path"))).parent_path();
    for (int level = 0; level < 4 && !directory.empty(); ++level, directory = directory.parent_path()) {
      unsigned visited = 0;
      for (const auto &entry : std::filesystem::directory_iterator(directory)) {
        if (++visited > 512) break;
        auto extension = entry.path().extension().wstring();
        if (extension != L".uvprojx" && extension != L".uvproj" && extension != L".jlink") continue;
        if (!entry.is_regular_file() || entry.file_size() > 4 * 1024 * 1024) continue;
        std::ifstream file(entry.path());
        std::string text((std::istreambuf_iterator<char>(file)), {});
        std::smatch match;
        if (std::regex_search(text, match, std::regex(R"(<Device>\s*([A-Za-z0-9_+.-]+)\s*</Device>|Device\s*=\s*([A-Za-z0-9_+.-]+))"))) {
          std::string device = match[1].matched ? match[1].str() : match[2].str();
          if (device.starts_with("HC32")) device = "Cortex-M4";
          return {{"device", device}, {"source", entry.path().string()}};
        }
      }
    }
    return {{"detected", false}};
  }
  if (!symbol_index)
    symbol_index = std::make_unique<symbols>();
  if (q.contains("elf") && jlink_settings.value("loaded_elf", std::string()) !=
                               q["elf"].get<std::string>()) {
    symbol_index->load(q["elf"]);
    jlink_settings["loaded_elf"] = q["elf"];
  }
  if (action == "load") {
    auto result = symbol_index->load(q.at("path"));
    if (q.contains("map")) symbol_index->merge_map(q.at("map"));
    jlink_settings["loaded_elf"] = q.at("path");
    return result;
  }
  if (action == "symbols")
    return symbol_index->list(q.value("filter", std::string()),
                              q.value("offset", 0u), q.value("limit", 100u), q.value("variables_only", false));
  if (action == "expand") {
    auto variable = symbol_index->find(q.at("name"));
    if (variable.value("kind", std::string()) == "pointer") {
      if (q.value("offset", 0u) != 0) return json::array();
      auto saved = q;
      q["action"] = "read";
      json pointer;
      try { pointer = jlink(op); } catch (...) { q = saved; throw; }
      q = saved;
      return symbol_index->dereference(q.at("name"), pointer.at("raw"));
    }
    return symbol_index->expand(q.at("name"), q.value("offset", 0u), q.value("limit", 100u));
  }
  jlink_settings.update(q);
  auto device = jlink_settings.value("device", std::string("GD32E507ZE"));
  if (!std::regex_match(device, std::regex("[A-Za-z0-9_+.-]+")))
    throw failure(2, "Invalid J-Link target");
  auto exe = jlink_settings.value(
      "jlink_exe",
      std::string("C:\\Program Files\\SEGGER\\JLink_V936\\JLink.exe"));
  if (!std::filesystem::exists(wide(exe)))
    throw failure(3, "J-Link executable not found; use --jlink-exe");
  auto dir = std::filesystem::temp_directory_path() /
             (L"frame-jlink-" + std::to_wstring(GetCurrentProcessId()) + L"-" +
              std::to_wstring(op.id));
  if (!std::filesystem::create_directory(dir))
    throw failure(8, "J-Link temporary operation directory already exists");
  struct cleanup final {
    std::filesystem::path path;
    ~cleanup() {
      std::error_code ec;
      std::filesystem::remove_all(path, ec);
    }
  } cleanup_files{dir};
  auto memory = dir / L"memory.bin";
  std::ostringstream commands;
  json variable;
  std::uint32_t address = 0;
  unsigned size = 0;
  if (action == "read" || action == "write") {
    variable = symbol_index->find(q.at("name"));
    if (variable.value("unsupported_location", false))
      throw failure(7, "Variable location/bit-field layout is not supported");
    auto addr = variable.at("address").get<std::uint64_t>();
    size = variable.at("size");
    if (addr > 0xffffffff || size == 0 || size > 4096 ||
        addr + size > 0x100000000ull)
      throw failure(7, "Unsupported variable location or size");
    address = static_cast<std::uint32_t>(addr);
    if (action == "write") {
      unsigned write_encoding = variable.value("encoding", 0u);
      if (variable.value("kind", std::string()) != "scalar" ||
          (write_encoding != 2 && write_encoding != 4 && write_encoding != 5 &&
           write_encoding != 6 && write_encoding != 7 && write_encoding != 8))
        throw failure(7, "Write requires a supported DWARF scalar type");
      if (stream_count_ != 0)
        throw failure(9, "Stop acquisition before J-Link writes");
      if (address < 0x20000000 || std::uint64_t(address) + size > 0x20020000)
        throw failure(7,
                      "Writes restricted to E507 SRAM 0x20000000..0x20020000");
      if (size != 1 && size != 2 && size != 4 && size != 8)
        throw failure(7, "Write requires a scalar of 1, 2, 4 or 8 bytes");
      unsigned encoding = variable.value("encoding", 0u),
               type = encoding == 4                    ? 6
                      : encoding == 5 || encoding == 6 ? (size == 1   ? 0
                                                          : size == 2 ? 2
                                                                      : 4)
                                                       : (size == 1   ? 1
                                                          : size == 2 ? 3
                                                                      : 5);
      std::uint64_t raw = 0;
      if (size == 8) {
        auto text = q["value"].is_string() ? q["value"].get<std::string>() : q["value"].dump();
        std::size_t used = 0;
        try {
          if (encoding == 4) { auto number = std::stod(text, &used); if (!std::isfinite(number)) throw failure(2, "Nonfinite double"); raw = std::bit_cast<std::uint64_t>(number); }
          else if (encoding == 5 || encoding == 6) raw = static_cast<std::uint64_t>(std::stoll(text, &used, text.starts_with("0x") ? 16 : 10));
          else { if (text.starts_with("-")) throw failure(2, "Negative unsigned value"); raw = std::stoull(text, &used, text.starts_with("0x") ? 16 : 10); }
          if (used != text.size()) throw failure(2, "Invalid scalar value");
        } catch (const std::invalid_argument &) { throw failure(2, "Invalid scalar value"); }
        catch (const std::out_of_range &) { throw failure(2, "Scalar value out of range"); }
      } else raw = raw_value(q.at("value"), type);
      if (write_encoding == 2 && raw > 1)
        throw failure(2, "Boolean RAM value must be 0 or 1");
      if (size == 8) {
        commands << "w4 0x" << std::hex << address << " 0x" << static_cast<std::uint32_t>(raw) << "\n";
        commands << "w4 0x" << address + 4 << " 0x" << static_cast<std::uint32_t>(raw >> 32) << std::dec << "\n";
      } else commands << "w" << size << " 0x" << std::hex << address << " 0x" << raw << std::dec << "\n";
      variable["expected_raw"] = raw;
      variable["value_type"] = type;
    }
    if (address >= 0x40000000 && address < 0x60000000)
      throw failure(7, "MMIO requires a separate explicit access workflow");
    commands << "savebin " << quote_arg(memory.string()) << ", 0x" << std::hex
             << address << ", 0x" << size << std::dec << "\n";
  } else if (action != "connect")
    throw failure(2, "Unknown J-Link action");
  if (!probe_session)
    probe_session = std::make_unique<commander>();
  auto check = [this, &op] { guard(op); };
  auto probe = jlink_settings.value("probe", 0u);
  auto interface_name = jlink_settings.value("interface", std::string("SWD"));
  auto speed = jlink_settings.value("speed", 1000u);
  if ((interface_name != "SWD" && interface_name != "JTAG") || speed < 1 || speed > 50000)
    throw failure(2, "J-Link interface must be SWD/JTAG; speed must be 1..50000 kHz");
  bool reused = probe_session->alive() &&
                probe_session->identity ==
                    exe + "|" + device + "|" + std::to_string(probe) + "|" + interface_name + "|" + std::to_string(speed);
  if (!reused)
    probe_session->open(exe, device, probe, check, interface_name, speed);
  std::string output;
  std::istringstream script(commands.str());
  std::string command;
  while (std::getline(script, command))
    if (!command.empty())
      output += probe_session->exchange(command, check);
  if (action == "connect")
    return {{"device", device},
            {"connected", true},
            {"session_reused", reused},
            {"selected_probe", probe},
            {"interface", interface_name}, {"speed", speed},
            {"output", output}};
  std::ifstream input(memory, std::ios::binary);
  bytes data((std::istreambuf_iterator<char>(input)), {});
  if (data.size() != size)
    throw failure(6, "J-Link returned incomplete memory data: " + output);
  variable["hex"] = hex(data);
  if (size == 8) {
    std::uint64_t raw = 0;
    for (unsigned i = 0; i < 8; ++i) raw |= std::uint64_t(data[i]) << (i * 8);
    variable["raw"] = raw;
    auto encoding = variable.value("encoding", 0u);
    if (encoding == 4) variable["value"] = std::bit_cast<double>(raw);
    else if (encoding == 5 || encoding == 6) variable["value"] = std::bit_cast<std::int64_t>(raw);
    else variable["value"] = raw;
    if (action == "write" && variable["expected_raw"] != raw) throw failure(7, "RAM readback mismatch");
  } else if (size <= 4) {
    std::uint32_t raw = 0;
    for (unsigned i = 0; i < size; ++i)
      raw |= std::uint32_t(data[i]) << (i * 8);
    variable["raw"] = raw;
    unsigned encoding = variable.value("encoding", 0u),
             type = encoding == 4                    ? 6
                    : encoding == 5 || encoding == 6 ? (size == 1   ? 0
                                                        : size == 2 ? 2
                                                                    : 4)
                                                     : (size == 1   ? 1
                                                        : size == 2 ? 3
                                                                    : 5);
    variable["value"] = value(raw, type);
    if (action == "write" && variable["expected_raw"] != raw)
      throw failure(7, "RAM readback mismatch");
  }
  if (variable.value("kind", std::string()) == "pointer" && variable.contains("raw")) {
    try { variable.update(symbol_index->describe_pointer(q.at("name"), variable.at("raw"))); }
    catch (const failure &) { /* Reading a pointer succeeds even if its target has no usable layout. */ }
  }
  return variable;
}
} // namespace frame
