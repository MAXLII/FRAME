// SPDX-License-Identifier: MIT
#include "service_support.hpp"
namespace frame {
static json Handle(runtime &r, operation &op) {
  auto &q = op.command;
  auto group = q.value("group", std::string()), action = q.value("action", std::string());
  if (group == "section" && action == "resolve") {
    symbols index; index.load(q.at("map"));
    auto rows = q.at("records");
    for (auto &row : rows) { auto names = index.at_address(row.at("address")); row["name"] = names.empty() ? "" : names.front(); row["symbols"] = names; }
    return rows;
  }
    symbols map_index;
    if (q.contains("map")) map_index.load(q.at("map"));
    auto resolve = [&](json rows) {
      if (q.contains("map")) for (auto &row : rows) {
        auto names = map_index.at_address(row.at("address"));
        row["name"] = names.empty() ? "" : names.front();
        row["symbols"] = names;
      }
      return rows;
    };
    if (action == "resolve") return resolve(q.at("records"));
    json rows = json::array();
    if (action == "list") {
      for (unsigned i = 0; i < 1024; ++i) {
        bytes b;
        put(b, i, 2);
        auto item = r.query(op, 0x38, b);
        if (item["index"] != i)
          throw failure(5, "Directory index mismatch");
        rows.push_back(item);
        if (i + 1 >= item["count"].get<unsigned>())
          return rows;
      }
      throw failure(6, "Directory quota exceeded");
    }
    if (action == "nodes") {
      unsigned id = q.value("id", 0u);
      if (id > 65535)
        throw failure(2, "List id outside uint16");
      for (unsigned i = 0; i < 100000; ++i) {
        bytes b;
        put(b, id, 2);
        put(b, i, 4);
        r.send(0x39, b);
        auto response = r.wait_packet(op, 0x39, true, [id, i](const packet &p) {
          reader r(p.payload);
          return r.u16(2) == id && r.u32(4) == i;
        });
        auto item = decode(0x39, response.payload);
        if (i == 0 && item["status"] == 4 && item["count"] == 0)
          return rows;
        checked(item);
        item = resolve(json::array({item})).front();
        rows.push_back(item);
        r.progress(op, {{"received", rows.size()}, {"total", item["count"]}, {"items", json::array({item})}});
        if (i + 1 >= item["count"].get<unsigned>())
          return rows;
      }
      throw failure(6, "Node quota exceeded");
    }
    throw failure(2, "Unknown section action");
  throw failure(2, "Unsupported section command" );
}
static void Install(BackendRegistry &registry) {
  registry.Service({"section", {"frame-protocol"}}); registry.Commands("section", "section", {"resolve"}, Handle); registry.Commands("section", "section", {"list","nodes"}, Handle, CommandPolicy{ExecutionLane::Core, true, false, false, "frame-v1", "section_nodes"});
}
FRAME_REGISTER_MODULE(frame_module_section, Install)
} // namespace frame
