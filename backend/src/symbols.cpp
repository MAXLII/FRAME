// SPDX-License-Identifier: MIT
#include "symbols.hpp"
#include "transport.hpp"
#include <fstream>
#include <llvm/DebugInfo/DWARF/DWARFContext.h>
#include <llvm/DebugInfo/DWARF/DWARFDie.h>
#include <llvm/Object/Binary.h>
#include <llvm/Object/ObjectFile.h>
#include <llvm/Object/SymbolSize.h>
#include <llvm/Support/Error.h>
#include <map>
#include <regex>
#include <utility>
namespace frame {
struct symbols::impl {
  std::unique_ptr<llvm::object::OwningBinary<llvm::object::Binary>> binary;
  std::unique_ptr<llvm::DWARFContext> context;
  std::map<std::string, json> values;
  std::map<std::string, llvm::DWARFDie> types;
  std::pair<llvm::DWARFDie, json> resolve_pointer(const std::string &name, std::uint64_t address);
};
static std::uint64_t attr(llvm::DWARFDie die, llvm::dwarf::Attribute a,
                          std::uint64_t fallback = 0) {
  auto v = die.find(a);
  return v ? llvm::dwarf::toUnsigned(v, fallback) : fallback;
}
static llvm::DWARFDie real_type(llvm::DWARFDie d) {
  for (int i = 0; d && i < 16; ++i) {
    auto tag = d.getTag();
    if (tag != llvm::dwarf::DW_TAG_typedef &&
        tag != llvm::dwarf::DW_TAG_const_type &&
        tag != llvm::dwarf::DW_TAG_volatile_type)
      break;
    d = d.getAttributeValueAsReferencedDie(llvm::dwarf::DW_AT_type);
  }
  return d;
}
static std::uint64_t type_size(llvm::DWARFDie d, int depth = 0) {
  if (!d || depth > 16)
    return 0;
  d = real_type(d);
  auto size = attr(d, llvm::dwarf::DW_AT_byte_size);
  if (size)
    return size;
  if (d.getTag() == llvm::dwarf::DW_TAG_array_type) {
    std::uint64_t count = 1;
    for (auto c : d.children())
      if (c.getTag() == llvm::dwarf::DW_TAG_subrange_type)
        count *= attr(c, llvm::dwarf::DW_AT_count,
                      attr(c, llvm::dwarf::DW_AT_upper_bound) + 1);
    return count * type_size(d.getAttributeValueAsReferencedDie(
                                 llvm::dwarf::DW_AT_type),
                             depth + 1);
  }
  return 0;
}
static json type_info(llvm::DWARFDie d) {
  d = real_type(d);
  if (!d)
    return {{"size", 0}, {"kind", "unknown"}};
  auto name = d.getName(llvm::DINameKind::ShortName);
  std::string kind = "scalar";
  switch (d.getTag()) {
  case llvm::dwarf::DW_TAG_structure_type:
    kind = "struct";
    break;
  case llvm::dwarf::DW_TAG_union_type:
    kind = "union";
    break;
  case llvm::dwarf::DW_TAG_array_type:
    kind = "array";
    break;
  case llvm::dwarf::DW_TAG_pointer_type:
    kind = "pointer";
    break;
  default:
    break;
  }
  return {{"size", type_size(d)},
          {"kind", kind},
          {"type_name", name ? name : ""},
          {"encoding", attr(d, llvm::dwarf::DW_AT_encoding)}};
}
std::pair<llvm::DWARFDie, json> symbols::impl::resolve_pointer(const std::string &name, std::uint64_t address) {
  if (!types.contains(name)) throw failure(7, "Pointer has no DWARF type");
  auto pointer = real_type(types.at(name));
  if (pointer.getTag() != llvm::dwarf::DW_TAG_pointer_type) throw failure(2, "Not a pointer");
  if (!address) throw failure(7, "Null pointer");
  auto type = pointer.getAttributeValueAsReferencedDie(llvm::dwarf::DW_AT_type);
  auto item = type_info(type);
  const bool infer_type = item["size"] == 0 || item["kind"] == "scalar";
  llvm::DWARFDie matched_type;
  std::string resolved_symbol;
  for (const auto &[candidate_name, candidate] : values) {
    if (!candidate.value("is_variable", false) || candidate.value("ambiguous", false) ||
        candidate.value("address", UINT64_MAX) != address || !types.contains(candidate_name))
      continue;
    auto candidate_type = real_type(types.at(candidate_name));
    auto info = type_info(candidate_type);
    if (info["size"] == 0) continue;
    // A declared aggregate layout remains authoritative for dynamic nodes.
    // Match its named symbol too, without attaching an incompatible object's name.
    if (!infer_type && (info["kind"] != item["kind"] || info["size"] != item["size"] ||
        info["type_name"] != item["type_name"])) continue;
    if (matched_type && matched_type != candidate_type)
      throw failure(7, "Multiple DWARF object types at pointer address");
    matched_type = candidate_type;
    resolved_symbol = candidate_name;
  }
  if (matched_type) {
    if (infer_type) { type = matched_type; item = type_info(type); }
    item["resolved_symbol"] = resolved_symbol;
    item["resolution"] = "symbol_address";
  }
  if (!item.value("size", 0u)) throw failure(7, "No DWARF target type or typed object at pointer address; MAP alone has no member layout");
  return {type, item};
}
symbols::symbols() : state_(std::make_unique<impl>()) {}
symbols::~symbols() = default;
json symbols::load(const std::string &path) {
  auto next = std::make_unique<impl>();
  if (path.ends_with(".map")) {
    std::ifstream f(wide(path));
    if (!f)
      throw failure(8, "Cannot open MAP");
    std::regex re(R"(^\s*0x([0-9a-fA-F]+)\s+([A-Za-z_][A-Za-z_0-9.]*)\s*$)");
    std::string line;
    while (std::getline(f, line)) {
      std::smatch m;
      if (std::regex_match(line, m, re))
        next->values[m[2]] = {{"name", m[2].str()},
                              {"address", std::stoull(m[1], nullptr, 16)},
                              {"size", 0},
                              {"kind", "unknown"}};
    }
  } else {
    auto binary = llvm::object::createBinary(path);
    if (!binary)
      throw failure(8, llvm::toString(binary.takeError()));
    next->binary =
        std::make_unique<llvm::object::OwningBinary<llvm::object::Binary>>(
            std::move(*binary));
    auto obj =
        llvm::dyn_cast<llvm::object::ObjectFile>(next->binary->getBinary());
    if (!obj)
      throw failure(8, "Not an object file");
    next->context = llvm::DWARFContext::create(*obj);
    for (auto &[sym, symbol_size] : llvm::object::computeSymbolSizes(*obj)) {
      auto name = sym.getName();
      auto address = sym.getAddress();
      if (!name) {
        llvm::consumeError(name.takeError());
        continue;
      }
      if (!address) {
        llvm::consumeError(address.takeError());
        continue;
      }
      auto symbol_type = sym.getType();
      if (!symbol_type) llvm::consumeError(symbol_type.takeError());
      if (!name->empty())
        next->values[name->str()] = {{"name", name->str()},
                                     {"address", *address},
                                     {"size", symbol_size},
                                     {"kind", "unknown"},
                                     {"is_variable", symbol_type && *symbol_type == llvm::object::SymbolRef::ST_Data}};
    }
    std::function<void(llvm::DWARFDie, unsigned)> visit = [&](llvm::DWARFDie d,
                                                              unsigned depth) {
      if (!d || depth > 64)
        return;
      if (d.getTag() == llvm::dwarf::DW_TAG_variable) {
        auto name = d.getName(llvm::DINameKind::ShortName);
        auto location = d.find(llvm::dwarf::DW_AT_location);
        if (name && location) {
          auto block = location->getAsBlock();
          if (block && block->size() >= 5 &&
              (*block)[0] == llvm::dwarf::DW_OP_addr) {
            reader r(std::span(block->data(), block->size()));
            auto address = r.u32(1);
            auto type =
                d.getAttributeValueAsReferencedDie(llvm::dwarf::DW_AT_type);
            if (!type) {
              auto spec = d.getAttributeValueAsReferencedDie(
                  llvm::dwarf::DW_AT_specification);
              if (spec)
                type = spec.getAttributeValueAsReferencedDie(
                    llvm::dwarf::DW_AT_type);
            }
            auto item = type_info(type);
            if (item["size"] == 0 && next->values.contains(name))
              item["size"] = next->values[name]["size"];
            item["name"] = name;
            item["is_variable"] = true;
            item["address"] = address;
            if (next->types.contains(name))
              item["ambiguous"] =
                  next->values[name].value("ambiguous", false) ||
                  next->values[name]["address"] != address;
            next->values[name] = item;
            next->types[name] = type;
          }
        }
      }
      for (auto child : d.children())
        visit(child, depth + 1);
    };
    for (auto &cu : next->context->compile_units())
      visit(cu->getUnitDIE(false), 0);
  }
  auto count = next->values.size();
  state_ = std::move(next);
  return {{"path", path},
          {"count", count},
          {"dwarf_variables", state_->types.size()},
          {"firmware_identity_verified", false}};
}
json symbols::list(const std::string &filter, unsigned offset, unsigned limit, bool variables_only) {
  json rows = json::array();
  unsigned index = 0;
  for (auto &[name, v] : state_->values)
    if (name.find(filter) != std::string::npos && (!variables_only || v.value("is_variable", true))) {
      if (index++ < offset)
        continue;
      if (rows.size() >= std::min(limit, 4096u))
        break;
      rows.push_back(v);
    }
  return rows;
}
void symbols::merge_map(const std::string &path) {
  symbols extra;
  extra.load(path);
  for (const auto &[name, variable] : extra.state_->values)
    if (!state_->values.contains(name)) state_->values[name] = variable;
}
json symbols::at_address(std::uint64_t address) {
  json names = json::array();
  for (const auto &[name, variable] : state_->values)
    if (variable.value("address", UINT64_MAX) == address) names.push_back(name);
  return names;
}
json symbols::dereference(const std::string &name, std::uint64_t address) {
  const auto expression = "(*" + name + ")";
  // Failed resolution must also invalidate the previous target's members.
  for (auto it = state_->values.begin(); it != state_->values.end();) {
    if (it->first == expression || it->first.starts_with(expression + ".") || it->first.starts_with(expression + "[")) {
      state_->types.erase(it->first); it = state_->values.erase(it);
    } else ++it;
  }
  auto [type, item] = state_->resolve_pointer(name, address);
  item["name"] = expression; item["address"] = address;
  state_->values[expression] = item; state_->types[expression] = type;
  return json::array({item});
}
json symbols::describe_pointer(const std::string &name, std::uint64_t address) {
  auto [type, item] = state_->resolve_pointer(name, address);
  std::string type_name = item.value("type_name", std::string());
  json result = {{"resolved_type", type_name.empty() ? item.at("kind") : json(type_name)}};
  if (item.contains("resolved_symbol")) result["resolved_symbol"] = item["resolved_symbol"];
  return result;
}
json symbols::find(const std::string &name) {
  auto it = state_->values.find(name);
  if (it == state_->values.end())
    throw failure(2, "Symbol not found: " + name);
  if (it->second.value("ambiguous", false))
    throw failure(7, "Ambiguous DWARF symbol name: " + name);
  return it->second;
}
json symbols::expand(const std::string &name, unsigned offset, unsigned limit) {
  if (!state_->types.contains(name))
    throw failure(7, "No supported DWARF type for symbol");
  auto d = real_type(state_->types.at(name));
  auto base = find(name).at("address").get<std::uint64_t>();
  json rows = json::array();
  unsigned index = 0;
  limit = std::min(limit, 4096u);
  if (d.getTag() == llvm::dwarf::DW_TAG_array_type) {
    auto element = d.getAttributeValueAsReferencedDie(llvm::dwarf::DW_AT_type);
    auto size = type_size(element);
    if (!size)
      throw failure(7, "Unknown element size");
    auto count = type_size(d) / size;
    for (auto i = offset; i < count && rows.size() < limit; ++i) {
      auto item = type_info(element);
      item["name"] = name + "[" + std::to_string(i) + "]";
      item["address"] = base + i * size;
      state_->values[item["name"]] = item;
      state_->types[item["name"]] = element;
      rows.push_back(item);
    }
  } else
    for (auto child : d.children())
      if (child.getTag() == llvm::dwarf::DW_TAG_member) {
        if (index++ < offset)
          continue;
        if (rows.size() >= limit)
          break;
        auto n = child.getName(llvm::DINameKind::ShortName);
        auto type =
            child.getAttributeValueAsReferencedDie(llvm::dwarf::DW_AT_type);
        auto item = type_info(type);
        item["name"] = name + "." + (n ? n : "unnamed");
        item["address"] =
            base + attr(child, llvm::dwarf::DW_AT_data_member_location);
        auto location = child.find(llvm::dwarf::DW_AT_data_member_location);
        item["unsupported_location"] =
            bool(child.find(llvm::dwarf::DW_AT_bit_size)) ||
            (d.getTag() != llvm::dwarf::DW_TAG_union_type &&
             (!location || !location->getAsUnsignedConstant()));
        state_->values[item["name"]] = item;
        state_->types[item["name"]] = type;
        rows.push_back(item);
      }
  return rows;
}
} // namespace frame
