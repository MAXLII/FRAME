// SPDX-License-Identifier: MIT
#include "service_support.hpp"
namespace frame {
static json Handle(runtime &r, operation &op) {
  auto &q = op.command;
  auto group = q.value("group", std::string()), action = q.value("action", std::string());
    if (action == "info")
      return r.query(op, 0x20, {});
    if (action == "summary")
      return r.query(op, 0x21, {});
    if (action == "reset")
      return r.query(op, 0x25, {});
    if (action == "start" || action == "stop")
      return r.query(op, 0x2e, {static_cast<std::uint8_t>(action == "start")});
    if (action == "dictionary" || action == "samples") {
      if (action == "samples" && r.perf_dictionary.empty()) {
        auto saved = q;
        op.command["action"] = "dictionary";
        op.command["filter"] = 0;
        try { r.execute(op); } catch (...) { op.command = saved; throw; }
        op.command = saved;
      }
      bytes b{static_cast<std::uint8_t>(q.value("filter", 0)), 0, 0, 0};
      auto filter = q.value("filter", 0);
      if (filter < 0 || filter > 255)
        throw failure(2, "Perf filter outside uint8");
      put(b, action == "dictionary" ? 0 : r.perf_version, 4);
      auto query_word = action == "dictionary" ? 0x26 : 0x29;
      r.send(query_word, b);
      auto ack = decode(static_cast<std::uint8_t>(query_word), r.wait_packet(op, query_word).payload);
      if (!ack["accepted"].get<bool>()) {
        if (action == "samples" && ack["reason"] == 5 && !q.value("resync_attempted", false)) {
          auto saved = q; q["resync_attempted"] = true; r.perf_dictionary.clear();
          try { auto result = r.execute(op); q = saved; return result; } catch (...) { q = saved; throw; }
        }
        throw failure(7, "Perf request rejected, reason " + ack["reason"].dump());
      }
      std::map<unsigned, json> next_dictionary;
      auto seq = ack["sequence"].get<unsigned>();
      unsigned expected = ack["count"];
      std::set<unsigned> seen;
      json rows = json::array();
      bool ended = false;
      auto end = clock::now() + std::chrono::milliseconds(r.timeout_ms);
      while (!ended) {
        r.guard(op);
        for (auto it = r.incoming.begin(); it != r.incoming.end();) {
          auto word = it->word;
          if (!it->ack &&
              (word == 0x27 || word == 0x28 || word == 0x2a || word == 0x2b) &&
              reader(it->payload).u32(0) == seq) {
            reader payload_reader(it->payload);
            if (word == 0x27 && action == "dictionary") {
              auto item = decode(word, it->payload);
              if (item["index"].get<unsigned>() >= expected ||
                  !seen.insert(item["record_id"].get<unsigned>()).second)
                throw failure(6, "Duplicate or invalid Perf dictionary index");
              next_dictionary[item["record_id"]] = item;
              rows.push_back(item);
            } else if (word == 0x2a && action == "samples") {
              unsigned offset = 8;
              for (unsigned i = 0; i < payload_reader.u16(6); ++i) {
                auto id = payload_reader.u16(offset);
                if (!seen.insert(id).second)
                  throw failure(6, "Duplicate Perf sample record");
                if (!r.perf_dictionary.contains(id))
                  throw failure(6,
                                "Perf sample references unknown dictionary id");
                auto item = r.perf_dictionary[id];
                item["time_us"] = payload_reader.u32(offset + 2);
                item["max_us"] = payload_reader.u32(offset + 6);
                unsigned type = item["type"];
                if (type == 1) {
                  item["period_us"] = payload_reader.u32(offset + 10);
                  item["load"] = payload_reader.f32(offset + 14);
                  item["peak"] = payload_reader.f32(offset + 18);
                  offset += 22;
                } else if (type == 2) {
                  item["load"] = payload_reader.f32(offset + 10);
                  item["peak"] = payload_reader.f32(offset + 14);
                  offset += 18;
                } else if (type == 3)
                  offset += 10;
                else
                  throw failure(5, "Unknown Perf record type");
                rows.push_back(item);
                r.progress(op, {{"received", rows.size()}, {"total", expected}, {"items", json::array({item})}});
              }
            } else if (word == (action == "dictionary" ? 0x28 : 0x2b)) {
              auto final = checked(decode(word, it->payload));
              if (final["count"] != expected ||
                  (action == "dictionary" && final["version"] != ack["version"]))
                throw failure(6, "Perf end count/version mismatch");
              ended = true;
            }
            it = r.incoming.erase(it);
            end = clock::now() + std::chrono::milliseconds(r.timeout_ms);
          } else
            ++it;
        }
        if (clock::now() > end)
          throw failure(6, "Incomplete Perf transaction");
        if (!ended)
          r.pump();
      }
      if (rows.size() != expected)
        throw failure(6, "Perf record count mismatch: expected " +
                             std::to_string(expected) + ", got " +
                             std::to_string(rows.size()) + ", ack " +
                             ack.dump());
      if (action == "dictionary") { r.perf_dictionary = std::move(next_dictionary); r.perf_version = ack["version"]; }
      return rows;
    }
    throw failure(2, "Unknown Perf action");
  throw failure(2, "Unsupported perf command" );
}
static void Disconnected(runtime &r) { r.perf_dictionary.clear(); r.perf_version = 0; }
static void Install(BackendRegistry &registry) {
  registry.Service({"perf", {"frame-protocol"}, nullptr, nullptr, Disconnected}); registry.Commands("perf", "perf", {"info","summary","reset","start","stop","dictionary","samples"}, Handle, CommandPolicy{ExecutionLane::Core, true, false, false, "frame-v1", "perf_samples"});
}
FRAME_REGISTER_MODULE(frame_module_perf, Install)
} // namespace frame
