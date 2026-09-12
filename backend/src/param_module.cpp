// SPDX-License-Identifier: MIT
#include "service_support.hpp"
namespace frame {
static json Handle(runtime &r, operation &op) {
  auto &q = op.command;
  auto group = q.value("group", std::string()), action = q.value("action", std::string());
    if (action == "list") {
      r.send(1, {});
      auto head = r.wait_packet(op, 1);
      unsigned count = reader(head.payload).u32(0);
      if (count > 100000)
        throw failure(6, "Parameter directory exceeds quota");
      std::map<unsigned, json> indexed;
      std::set<std::string> names;
      unsigned published = 0;
      r.progress(op, {{"received", 0}, {"total", count}, {"items", json::array()}});
      auto end = clock::now() + std::chrono::milliseconds(r.timeout_ms);
      unsigned legacy = 0;
      while (indexed.size() < count) {
        r.guard(op);
        bool made_progress = false;
        for (auto it = r.incoming.begin(); it != r.incoming.end();) {
          if (!it->ack && (it->word == 4 || it->word == 0x3f)) {
            if (it->word == 4) {
              if (legacy >= count || indexed.contains(legacy))
                throw failure(6, "Duplicate or out-of-range parameter index");
              indexed[legacy++] = decode(4, it->payload);
            } else {
              auto batch = decode(0x3f, it->payload);
              if (batch["total"] != count)
                throw failure(6, "Parameter directory changed");
              unsigned index = batch["first"];
              for (auto &item : batch["items"]) {
                if (index >= count || indexed.contains(index))
                  throw failure(6, "Duplicate or out-of-range parameter index");
                indexed[index++] = item;
              }
            }
            it = r.incoming.erase(it);
            made_progress = true;
          } else
            ++it;
        }
        if (made_progress) {
          end = clock::now() + std::chrono::milliseconds(r.timeout_ms);
          // Emit only a contiguous prefix, so out-of-order batches cannot
          // reorder rows already shown in the client.
          while (indexed.contains(published)) {
            json chunk = json::array();
            while (indexed.contains(published) && chunk.size() < 64) {
              const auto &item = indexed.at(published);
              if (!names.insert(item.at("name").get<std::string>()).second)
                throw failure(6, "Duplicate parameter name in directory");
              chunk.push_back(item);
              ++published;
            }
            r.progress(op, {{"received", published}, {"total", count}, {"items", std::move(chunk)}});
          }
        }
        if (clock::now() > end)
          throw failure(6, "Incomplete parameter directory");
        if (indexed.size() < count)
          r.pump();
      }
      r.parameters.clear();
      if (indexed.size() != count)
        throw failure(6, "Parameter directory count mismatch");
      json rows = json::array();
      for (auto &[index, item] : indexed) {
        if (r.parameters.contains(item["name"]))
          throw failure(6, "Duplicate parameter name in directory");
        r.parameters[item["name"]] = item;
        rows.push_back(item);
      }
      return rows;
    }
    if (action == "batch-read" || action == "batch-write") {
      std::ifstream file(wide(q.at("input")));
      if (!file)
        throw failure(2, "Cannot read batch input");
      json items;
      file >> items;
      if (!items.is_array() || items.size() > 1024)
        throw failure(2, "Batch must be an array of at most 1024 items");
      for (auto &item : items) {
        if (item.is_string() && action == "batch-read")
          continue;
        if (!item.is_object() || !item.contains("name") ||
            !item["name"].is_string() ||
            (action == "batch-write" && !item.contains("value")))
          throw failure(
              2, "Batch items require a name and writes require a value");
      }
      json rows = json::array();
      for (auto &item : items) {
        r.guard(op);
        operation child;
        child.parent = &op;
        child.deadline = op.deadline;
        child.command = q;
        child.command["action"] = action == "batch-read" ? "read" : "write";
        if (item.is_string())
          child.command["name"] = item;
        else {
          child.command["name"] = item["name"];
          if (item.contains("value"))
            child.command["value"] = item["value"];
        }
        try {
          rows.push_back({{"ok", true}, {"data", r.execute(child)}});
        } catch (const failure &e) {
          rows.push_back(
              {{"ok", false}, {"error", e.what()}, {"code", e.code}});
          if (e.code == 4 || e.code == 130)
            break;
        }
      }
      bool partial = rows.size() != items.size();
      for (auto &row : rows)
        if (!row["ok"].get<bool>())
          partial = true;
      return {{"items", rows}, {"partial", partial}};
    }
    auto name = q.value("name", std::string());
    auto payload = name_payload(name);
    auto matcher = [name](const packet &p) {
      try {
        return parameter(p.payload, p.word == 3 ? 14 : 6)["name"] == name;
      } catch (...) {
        return false;
      }
    };
    if (action == "read") {
      auto row = r.query(op, 2, payload, matcher);
      r.parameters[name].update(row);
      return row;
    }
    if (action == "write") {
      if (!r.parameters.contains(name) || !r.parameters[name].contains("min_raw")) {
        auto saved = q;
        op.command["action"] = "list";
        r.execute(op);
        op.command = saved;
      }
      if (!r.parameters.contains(name))
        throw failure(7, "Parameter not in device directory");
      auto entry = r.parameters[name];
      auto type = entry.at("type").get<unsigned>();
      if (type != 7 && entry.at("min_raw") == entry.at("max_raw"))
        throw failure(7, "Parameter is read-only");
      auto raw = type == 7 ? 0u : raw_value(q.at("value"), type);
      auto min_raw = type == 7 ? 0u : q.contains("min") ? raw_value(q.at("min"), type) : entry.at("min_raw").get<std::uint32_t>();
      auto max_raw = type == 7 ? 0u : q.contains("max") ? raw_value(q.at("max"), type) : entry.at("max_raw").get<std::uint32_t>();
      auto numeric = value(raw, type);
      auto minimum = value(min_raw, type), maximum = value(max_raw, type);
      if (type != 7 && (minimum.is_null() || maximum.is_null() || minimum.get<double>() > maximum.get<double>()))
        throw failure(2, "Invalid parameter limits");
      if (type != 7 && minimum != maximum &&
          (numeric.get<double>() < minimum.get<double>() ||
           numeric.get<double>() > maximum.get<double>()))
        throw failure(2, "Value outside device parameter bounds");
      bytes b{static_cast<std::uint8_t>(name.size())};
      put(b, raw, 4);
      put(b, max_raw, 4);
      put(b, min_raw, 4);
      b.insert(b.end(), name.begin(), name.end());
      // A write ACK already contains the device's actual value and limits.
      // Do not fail an acknowledged update because a redundant read times out
      // or the application's callback subsequently changes a live variable.
      std::erase_if(r.incoming, [&](const packet &p) { return p.word == 3 && matcher(p); });
      json ack;
      bool ack_received = true;
      try {
        ack = r.query(op, 3, b, matcher);
      } catch (const failure &error) {
        if (error.code != 4 || type == 7) throw;
        r.guard(op); // Cancellation and the operation deadline still take precedence.
        ack_received = false;
        // The directory supplies value AND limits. A scalar read cannot confirm
        // edited limits. Never retry the write, including command-type entries.
        auto saved = q;
        op.command["action"] = "list";
        json directory;
        try { directory = r.execute(op); }
        catch (...) { op.command = saved; throw; }
        op.command = saved;
        auto found = std::find_if(directory.begin(), directory.end(), [&](const json &row) { return row["name"] == name; });
        if (found == directory.end()) throw failure(7, "Written parameter missing from fresh directory");
        ack = *found;
      }
      if (type != 7) {
        if (ack["type"] != type)
          throw failure(7, "Parameter type changed during write confirmation");
        // Narrow integer fields may carry padding in the upper raw bytes.
        // Compare their declared typed values; FP32 still compares exactly.
        if (ack["max"] != maximum || ack["min"] != minimum)
          throw failure(7, "Parameter limit readback mismatch");
        if (ack["value"] != numeric)
          throw failure(7, "Write readback mismatch: " + ack.dump());
        ack["verified"] = true;
        ack["verification"] = ack_received ? "write_ack" : "directory_readback";
      }
      ack["ack_received"] = ack_received;
      r.parameters[name].update(ack);
      return ack;
    }
    if (action == "report") {
      payload.insert(payload.begin() + 1, q.value("enable", true) ? 1 : 0);
      return r.query(op, 5, payload);
    }
    throw failure(2, "Unknown parameter action");
  throw failure(2, "Unsupported param command" );
}
static void Disconnected(runtime &r) { r.parameters.clear(); }
static void Install(BackendRegistry &registry) {
  registry.Service({"param", {"frame-protocol"}, nullptr, nullptr, Disconnected}); registry.Commands("param", "param", {"list","read","write","batch-read","batch-write","report"}, Handle, CommandPolicy{ExecutionLane::Core, true, false, false, "frame-v1"});
}
FRAME_REGISTER_MODULE(frame_module_param, Install)
} // namespace frame
