// SPDX-License-Identifier: MIT
#include "runtime.hpp"
#include "discovery.hpp"
#include "symbols.hpp"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <set>
namespace frame {
static bytes name_payload(const std::string &name) {
  if (name.empty() || name.size() > 64)
    throw failure(2, "Parameter name must contain 1..64 UTF-8 bytes");
  bytes b{static_cast<std::uint8_t>(name.size())};
  b.insert(b.end(), name.begin(), name.end());
  return b;
}
static bytes object_payload(const json &q) {
  auto id = q.value("id", 0);
  if (id < 0 || id > 255)
    throw failure(2, "Object id outside uint8");
  return {static_cast<std::uint8_t>(id), 0, 0, 0};
}
static json checked(json j) {
  if (j.contains("status") && j["status"] != 0)
    throw failure(7, "Device status: " + j.dump());
  return j;
}
json runtime::execute(operation &op) {
  auto &q = op.command;
  auto group = q.value("group", std::string()),
       action = q.value("action", std::string());
  timeout_ms = q.value("response_timeout", 1500u);
  if (timeout_ms < 10 || timeout_ms > 60000)
    throw failure(2, "response_timeout outside 10..60000 ms");
  if (group == "status")
    return json::parse(snapshot());
  if (group == "ethernet" && action == "discover")
    return ethernet_discovery::scan(q, [&] { guard(op); if (serial.opened()) pump(0); });
  if (group == "section" && action == "resolve") {
    symbols index; index.load(q.at("map"));
    auto rows = q.at("records");
    for (auto &row : rows) { auto names = index.at_address(row.at("address")); row["name"] = names.empty() ? "" : names.front(); row["symbols"] = names; }
    return rows;
  }
  if (group == "serial" && action == "ports")
    return transport::ports();
  if (group == "serial" && action == "baud") {
    auto baud = serial.set_baud(q.at("baud").get<unsigned>());
    return {{"baud", baud}, {"endpoint", serial.endpoint}};
  }
  if (group == "connect" || group == "serial" && action == "connect") {
    if (!streams.empty())
      throw failure(9, "Stop acquisition jobs before reconnecting");
    serial.open(q, [&] { guard(op); });
    ++epoch_;
    incoming.clear();
    decoder.reset();
    parameters.clear();
    perf_dictionary.clear();
    dst = q.value("dst", 2u);
    dynamic_dst = q.value("dynamic_dst", 0u);
    if (dst > 255 || dynamic_dst > 255) {
      serial.close();
      throw failure(2, "Address outside uint8");
    }
    return {{"connected", true}, {"endpoint", serial.endpoint}};
  }
  if (group == "disconnect") {
    if (!streams.empty())
      throw failure(9, "Cancel jobs before disconnecting");
    serial.close();
    for(auto &[id,data]:datasets)if(data.value("group",std::string())=="sfra"&&data.value("state",std::string())=="running"){data["state"]="partial";data["partial"]=true;}
    ++epoch_;
    incoming.clear();
    decoder.reset();
    return {{"connected", false}};
  }
  if (group == "data") {
    if (action == "save") {
      if (!q.contains("records") || !q["records"].is_array() || q["records"].size() > 100000)
        throw failure(2, "Expected at most 100000 records");
      // Reuse the backend's atomic file exporter without retaining a dataset.
      datasets[op.id] = {{"schema_version", 1}, {"group", "perf"}, {"state", "complete"}, {"records", q["records"]}};
      try { export_dataset(op.id, q.at("output")); } catch (...) { datasets.erase(op.id); throw; }
      datasets.erase(op.id);
      return {{"path", q.at("output")}};
    }
    auto id = q.value("dataset", std::uint64_t(0));
    if (!datasets.contains(id))
      throw failure(2, "Unknown dataset");
    if (action == "release") {
      if (streams.contains(id))
        throw failure(9, "Dataset is still acquiring");
      datasets.erase(id);
      return {{"released", id}};
    }
    if (action == "export") {
      export_dataset(id, q.at("output"));
      return {{"path", q.at("output")}};
    }
    auto &d = datasets[id];
    auto &rows = d["records"];
    if (action == "view") {
      if (d.value("group", "") != "wave")
        throw failure(2, "Waveform dataset required");
      double seconds = q.value("seconds", 30.0);
      if (!std::isfinite(seconds) || seconds < 0 || seconds > 86400)
        throw failure(2, "View seconds must be in [0,86400]");
      double last = rows.empty() ? 0.0 : rows.back().value("time", 0.0);
      double first = rows.empty() ? 0.0 : rows.front().value("time", 0.0);
      double right = q.value("right", last);
      double left = q.value("left", seconds == 0 ? first : std::max(first, right - seconds));
      if (!std::isfinite(left) || !std::isfinite(right) || left > right)
        throw failure(2, "Invalid waveform viewport");
      std::map<std::string, std::vector<const json *>> series;
      std::map<std::string, const json *> latest_records;
      for (const auto &row : rows) {
        latest_records[row.value("name", "?")] = &row;
        double time = row.value("time", 0.0);
        if (time >= left && time <= right)
          series[row.value("name", "?")].push_back(&row);
      }
      json visible = json::array();
      // First/min/max/last per bucket preserve peaks; originals remain exportable.
      for (const auto &[name, points] : series) {
        auto stride = std::max<std::size_t>(1, (points.size() + 999) / 1000);
        for (std::size_t i = 0; i < points.size(); i += stride) {
          auto end = std::min(points.size(), i + stride);
          auto lo = i, hi = i;
          for (auto j = i + 1; j < end; ++j) {
            if ((*points[j])["value"] < (*points[lo])["value"]) lo = j;
            if ((*points[j])["value"] > (*points[hi])["value"]) hi = j;
          }
          std::set<std::size_t> selected{i, lo, hi, end - 1};
          for (auto j : selected) visible.push_back(*points[j]);
        }
      }
      std::stable_sort(visible.begin(), visible.end(), [](const json &a, const json &b) {
        return a.value("time", 0.0) < b.value("time", 0.0);
      });
      json latest = json::array();
      for (const auto &[name, record] : latest_records) latest.push_back(*record);
      return {{"records", visible}, {"latest_records", latest}, {"total", rows.size()},
              {"dataset_id", id}, {"left", left}, {"right", right}};
    }
    auto revision = d.value("dropped", 0ull) + rows.size();
    if (q.contains("revision") && q["revision"] != revision)
      throw failure(
          6,
          "Dataset revision changed; restart paging from the current snapshot");
    auto offset = q.value("offset", std::size_t(0)),
         limit = q.value("limit", std::size_t(1000));
    limit = std::min<std::size_t>(limit, 10000);
    json out = json::object();
    for (auto item = d.begin(); item != d.end(); ++item)
      if (item.key() != "records")
        out[item.key()] = item.value();
    out["records"] = json::array();
    for (auto i = std::min(offset, rows.size());
         i < std::min(rows.size(), offset + limit); ++i)
      out["records"].push_back(rows[i]);
    out["total"] = rows.size();
    out["dataset_id"] = id;
    out["revision"] = revision;
    return out;
  }
  if (group == "jlink") {
    if (action == "write") {
      if (stream_count_ != 0)
        throw failure(9, "Stop acquisition before J-Link writes");
      if (jlink_write_active_.exchange(true))
        throw failure(9, "J-Link write already queued");
    }
    std::lock_guard lock(mutex_);
    jlink_pending_.push_back(operations_.at(op.id));
    cv_.notify_all();
    return nullptr;
  }
  if (!serial.opened()) {
    if (q.contains("port") || q.contains("replay") || q.value("transport", std::string()) == "tcp") {
      serial.open(q, [&] { guard(op); });
      ++epoch_;
      decoder.reset();
      incoming.clear();
      parameters.clear();
      perf_dictionary.clear();
      dst = q.value("dst", 2u);
      dynamic_dst = q.value("dynamic_dst", 0u);
    } else
      throw failure(3, "Connect a device first, or provide --port / --transport tcp --host IP");
  }
  if (group == "serial") {
    if (!streams.empty())
      throw failure(9, "Raw serial requires idle protocol jobs");
    auto b = q.contains("hex") ? unhex(q.at("hex")) : bytes();
    if (q.contains("text")) {
      auto text = q.at("text").get<std::string>();
      b.assign(text.begin(), text.end());
    }
    if (action == "send" || action == "raw") {
      double duration = q.value("duration", 0.2),
             interval = q.value("interval", 0.0);
      if (!std::isfinite(duration) || duration < 0 || duration > 86400 ||
          !std::isfinite(interval) || interval < 0 || interval > 86400)
        throw failure(2, "Invalid serial duration/interval");
      if (b.size() > 1024 * 1024 || datasets.size() >= 32)
        throw failure(9, "Serial data capacity exceeded");
      if (!q.contains("timeout"))
        op.deadline = clock::now() +
                      std::chrono::milliseconds(
                          static_cast<std::int64_t>(duration * 1000) + 3000);
      auto &dataset = datasets[op.id];
      dataset = {{"schema_version", 1},
                 {"group", "serial"},
                 {"state", "running"},
                 {"records", json::array()},
                 {"dropped", 0}};
      auto &blocks = dataset["records"];
      std::size_t retained = 0;
      if (!b.empty()) {
        serial.write(b);
        tx_bytes += b.size();
      }
      auto end = clock::now() +
                 std::chrono::milliseconds(static_cast<int>(duration * 1000));
      auto next = clock::now() +
                  std::chrono::milliseconds(static_cast<int>(interval * 1000));
      while (clock::now() < end) {
        guard(op);
        auto data = serial.read(10);
        if (!data.empty()) {
          rx_bytes += data.size();
          while (!blocks.empty() && retained + data.size() > 8 * 1024 * 1024) {
            retained -= blocks[0]["bytes"].get<std::size_t>();
            blocks.erase(blocks.begin());
            dataset["dropped"] = dataset["dropped"].get<unsigned>() + 1;
          }
          blocks.push_back({{"hex", hex(data)}, {"bytes", data.size()}});
          retained += data.size();
        }
        if (interval > 0 && clock::now() >= next) {
          serial.write(b);
          tx_bytes += b.size();
          next = clock::now() +
                 std::chrono::milliseconds(static_cast<int>(interval * 1000));
        }
      }
      dataset["state"] = "complete";
      dataset["partial"] = dataset["dropped"] != 0;
      if (q.contains("output")) {
        export_dataset(op.id, q.at("output"));
      }
      return {{"dataset_id", op.id},
              {"records", blocks},
              {"count", blocks.size()},
              {"partial", dataset["partial"]}};
    }
    throw failure(2, "Unknown serial action");
  }
  if (group == "param") {
    if (action == "list") {
      send(1, {});
      auto head = wait_packet(op, 1);
      unsigned count = reader(head.payload).u32(0);
      if (count > 100000)
        throw failure(6, "Parameter directory exceeds quota");
      std::map<unsigned, json> indexed;
      std::set<std::string> names;
      unsigned published = 0;
      this->progress(op, {{"received", 0}, {"total", count}, {"items", json::array()}});
      auto end = clock::now() + std::chrono::milliseconds(timeout_ms);
      unsigned legacy = 0;
      while (indexed.size() < count) {
        guard(op);
        bool progress = false;
        for (auto it = incoming.begin(); it != incoming.end();) {
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
            it = incoming.erase(it);
            progress = true;
          } else
            ++it;
        }
        if (progress) {
          end = clock::now() + std::chrono::milliseconds(timeout_ms);
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
            this->progress(op, {{"received", published}, {"total", count}, {"items", std::move(chunk)}});
          }
        }
        if (clock::now() > end)
          throw failure(6, "Incomplete parameter directory");
        if (indexed.size() < count)
          pump();
      }
      parameters.clear();
      if (indexed.size() != count)
        throw failure(6, "Parameter directory count mismatch");
      json rows = json::array();
      for (auto &[index, item] : indexed) {
        if (parameters.contains(item["name"]))
          throw failure(6, "Duplicate parameter name in directory");
        parameters[item["name"]] = item;
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
        guard(op);
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
          rows.push_back({{"ok", true}, {"data", execute(child)}});
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
      auto row = query(op, 2, payload, matcher);
      parameters[name].update(row);
      return row;
    }
    if (action == "write") {
      if (!parameters.contains(name) || !parameters[name].contains("min_raw")) {
        auto saved = q;
        op.command["action"] = "list";
        execute(op);
        op.command = saved;
      }
      if (!parameters.contains(name))
        throw failure(7, "Parameter not in device directory");
      auto entry = parameters[name];
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
      auto ack = query(op, 3, b, matcher);
      parameters[name].update(ack);
      if (type != 7) {
        if (ack["max_raw"] != max_raw || ack["min_raw"] != min_raw)
          throw failure(7, "Parameter limit readback mismatch");
        auto read = query(op, 2, payload, matcher);
        if (read["raw"] != raw)
          throw failure(7, "Write readback mismatch: " + read.dump());
        ack["verified"] = true;
      }
      return ack;
    }
    if (action == "report") {
      payload.insert(payload.begin() + 1, q.value("enable", true) ? 1 : 0);
      return query(op, 5, payload);
    }
    throw failure(2, "Unknown parameter action");
  }
  if (group == "wave" || group == "trace") {
    unsigned control = group == "wave" ? 0x0c : 0x2c;
    if (group == "wave" && action == "period") {
      auto period = q.value("period", 0u);
      if (period == 0 || period > 60000) throw failure(2, "Period must be in 1..60000 ms");
      bytes payload; put(payload, period, 4); auto ack = query(op, 6, payload);
      for (auto &[id, stream] : streams) if (stream.group == "wave") datasets[id]["period_ms"] = period;
      return ack;
    }
    if (action == "stop") {
      auto ack = query(op, control, {0});
      for (auto &[id, s] : streams)
        if (s.group == group) {
          s.stop_confirmed = true;
          s.end = clock::now();
        }
      return ack;
    }
    if (action == "status")
      return json::parse(snapshot());
    if (action != "capture" && action != "start")
      throw failure(2, "Expected capture/start/stop/status");
    if (jlink_write_active_)
      throw failure(9, "J-Link write is active");
    for (auto &[id, s] : streams)
      if (s.group == group)
        throw failure(9, "Acquisition already running");
    auto resume = group == "wave" ? q.value("resume_dataset", std::uint64_t(0)) : 0;
    if (resume && (!datasets.contains(resume) || datasets[resume]["group"] != "wave" || datasets[resume]["state"] == "running"))
      throw failure(2, "Resume requires a stopped wave dataset");
    if (streams.size() >= 4 || (datasets.size() >= 32 && !resume))
      throw failure(9, "Dataset/job quota reached");
    double duration = q.value("duration", 10.0);
    if (!std::isfinite(duration) || duration < 0 || duration > 86400)
      throw failure(2, "Duration must be in [0,86400]; 0 means continuous capture");
    if (q.value("period", 10u) == 0 || q.value("period", 10u) > 60000)
      throw failure(2, "Period must be in 1..60000 ms");
    if (group == "wave") {
      wave_clock = {};
      wave_integrity = {};
      bytes b;
      put(b, q.value("period", 10u), 4);
      send(6, b);
      wait_packet(op, 6);
    }
    if (group == "trace")
      trace_clock = {};
    auto ack = query(op, control, {1});
    datasets[op.id] = {{"schema_version", 1}, {"group", group},
                       {"state", "running"},  {"records", json::array()},
                       {"control", ack},      {"dropped", 0}};
    if (group == "wave") {
      datasets[op.id]["period_ms"] = q.value("period", 10u);
      datasets[op.id]["segment"] = resume ? datasets[resume].value("segment", 0u) + 1 : 0;
      if (resume) {
        datasets[op.id]["records"] = std::move(datasets[resume]["records"]);
        datasets[op.id]["dropped"] = datasets[resume].value("dropped", 0);
        datasets.erase(resume);
      }
    }
    std::shared_ptr<operation> ptr;
    {
      std::lock_guard lock(mutex_);
      ptr = operations_.at(op.id);
    }
    streams[op.id] = {ptr, group,
                      duration == 0 ? clock::time_point::max() : clock::now() +
                          std::chrono::milliseconds(
                              static_cast<std::int64_t>(duration * 1000))};
    stream_count_ = static_cast<unsigned>(streams.size());
    return {{"dataset_id", op.id}};
  }
  if (group == "scope" || group == "sfra") {
    bool scope = group == "scope";
    auto b = object_payload(q);
    unsigned id = b[0];
    auto match = [id](const packet &p) {
      return !p.payload.empty() && p.payload[0] == id;
    };
    if (action == "list") {
      unsigned word = scope ? 0x18 : 0x2f;
      send(word, {0});
      json rows = json::array();
      for (unsigned i = 0; i < 256; ++i) {
        auto p = wait_packet(op, word);
        auto item = decode(static_cast<std::uint8_t>(word), p.payload);
        rows.push_back(item);
        if (item["last"] != 0)
          return rows;
      }
      throw failure(6, "Object enumeration exceeded quota");
    }
    if (action == "info")
      return query(op, scope ? 0x19 : 0x30, b, match);
    if (action == "channels" && scope) {
      auto info = query(op, 0x19, b, match);
      json rows = json::array();
      for (unsigned i = 0; i < info["channels"].get<unsigned>(); ++i) {
        b[1] = static_cast<std::uint8_t>(i);
        rows.push_back(query(op, 0x1a, b, match));
      }
      return rows;
    }
    if (action == "configure" && !scope) {
      bytes cfg{static_cast<std::uint8_t>(id), 3, 0, 0};
      auto start = q.at("start_hz").get<float>(),
           stop = q.at("stop_hz").get<float>(),
           amplitude = q.at("amplitude").get<float>();
      if (!(start > 0 && stop >= start && amplitude > 0 &&
            std::isfinite(stop) && std::isfinite(amplitude)))
        throw failure(2, "Invalid sweep configuration");
      putf(cfg, start);
      putf(cfg, stop);
      putf(cfg, amplitude);
      return query(op, 0x31, cfg, match);
    }
    std::map<std::string, unsigned> controls =
        scope ? std::map<std::string, unsigned>{{"start", 0x1b},
                                                {"trigger", 0x1c},
                                                {"stop", 0x1d},
                                                {"reset", 0x1e}}
              : std::map<std::string, unsigned>{
                    {"start", 0x32}, {"stop", 0x33}, {"reset", 0x34}};
    if (controls.contains(action)) {
      if(!scope&&action=="start"&&datasets.size()>=32)throw failure(9,"Dataset quota exceeded");
      if (action == "start") {
        auto other =
            query(op, scope ? 0x30 : 0x19, object_payload(json{{"id", 0}}));
        if (other.value("busy", 0) != 0 || other.value("state", 0) == 1)
          throw failure(9, "Other active capture must be stopped first");
      }
      auto ack = query(op, controls[action], b, match);
      if(!scope){
        if(action=="start"){
          datasets[op.id]={{"schema_version",1},{"group","sfra"},{"state","running"},{"epoch",epoch_},{"metadata",ack},{"records",json::array()},{"partial",false}};
          for(auto it=incoming.begin();it!=incoming.end();){if(receive_sfra_report(*it))it=incoming.erase(it);else ++it;}
          return {{"dataset_id",op.id},{"metadata",ack}};
        }
        for(auto &[datasetId,data]:datasets)if(data.value("group",std::string())=="sfra"&&data.value("state",std::string())=="running"&&data["metadata"]["id"]==id){data["state"]="stopped";data["partial"]=true;}
      }
      if (scope && (action == "start" || action == "trigger")) {
        // Control ACK can precede the sampling task's state transition.
        const auto deadline = clock::now() + std::chrono::milliseconds(500);
        const unsigned expected = action == "start" ? 1u : 2u;
        do {
          guard(op); pump(10);
          auto info = query(op, 0x19, b, match);
          if (info.value("state", 0u) == expected || info.value("ready", 0u) != 0)
            return info;
          ack = std::move(info);
        } while (clock::now() < deadline);
        ack["transition_pending"] = true;
      }
      return ack;
    }
    if (action == "pull" || action == "points") {
      auto info = query(op, scope ? 0x19 : 0x30, b, match);
      if (info["ready"] == 0)
        throw failure(7, "Device data is not ready");
      if (!scope &&
          (info["done"] == 0 || info["table_length"] != info["count"]))
        throw failure(7, "SFRA sweep is not complete; query info until done");
      auto count = info["count"].get<unsigned>(),
           tag = info["tag"].get<unsigned>();
      if (count > 1000000 || datasets.size() >= 32)
        throw failure(9, "Dataset quota exceeded");
      auto &d = datasets[op.id];
      d = {{"schema_version", 1},
           {"group", group},
           {"metadata", info},
           {"state", "partial"},
           {"records", json::array()}};
      for (unsigned index = 0; index < count; ++index) {
        guard(op);
        bytes request = scope ? bytes{static_cast<std::uint8_t>(id), 0, 0, 0}
                              : bytes{static_cast<std::uint8_t>(id), 0};
        put(request, index, scope ? 4 : 2);
        put(request, tag, 4);
        auto item = query(op, scope ? 0x1f : 0x35, request,
                          [id, index, tag, scope](const packet &p) {
                            try {
                              auto r = decode(scope ? 0x1f : 0x35, p.payload);
                              return r["id"] == id && r["index"] == index;
                            } catch (...) {
                              return false;
                            }
                          });
        if (item["tag"] != tag)
          throw failure(6, "Capture changed during pull");
        if (scope)
          item["time"] = double(index) * info["period_us"].get<double>() / 1e6;
        d["records"].push_back(item);
      }
      d["state"] = "complete";
      if (q.contains("output"))
        export_dataset(op.id, q["output"]);
      return {{"dataset_id", op.id}, {"count", count}, {"metadata", info}};
    }
    throw failure(2, "Unknown capture action");
  }
  if (group == "section") {
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
        auto item = query(op, 0x38, b);
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
        send(0x39, b);
        auto response = wait_packet(op, 0x39, true, [id, i](const packet &p) {
          reader r(p.payload);
          return r.u16(2) == id && r.u32(4) == i;
        });
        auto item = decode(0x39, response.payload);
        if (i == 0 && item["status"] == 4 && item["count"] == 0)
          return rows;
        checked(item);
        item = resolve(json::array({item})).front();
        rows.push_back(item);
        progress(op, {{"received", rows.size()}, {"total", item["count"]}, {"items", json::array({item})}});
        if (i + 1 >= item["count"].get<unsigned>())
          return rows;
      }
      throw failure(6, "Node quota exceeded");
    }
    throw failure(2, "Unknown section action");
  }
  if (group == "perf") {
    if (action == "info")
      return query(op, 0x20, {});
    if (action == "summary")
      return query(op, 0x21, {});
    if (action == "reset")
      return query(op, 0x25, {});
    if (action == "start" || action == "stop")
      return query(op, 0x2e, {static_cast<std::uint8_t>(action == "start")});
    if (action == "dictionary" || action == "samples") {
      if (action == "samples" && perf_dictionary.empty()) {
        auto saved = q;
        op.command["action"] = "dictionary";
        op.command["filter"] = 0;
        try { execute(op); } catch (...) { op.command = saved; throw; }
        op.command = saved;
      }
      bytes b{static_cast<std::uint8_t>(q.value("filter", 0)), 0, 0, 0};
      auto filter = q.value("filter", 0);
      if (filter < 0 || filter > 255)
        throw failure(2, "Perf filter outside uint8");
      put(b, action == "dictionary" ? 0 : perf_version, 4);
      auto query_word = action == "dictionary" ? 0x26 : 0x29;
      send(query_word, b);
      auto ack = decode(static_cast<std::uint8_t>(query_word), wait_packet(op, query_word).payload);
      if (!ack["accepted"].get<bool>()) {
        if (action == "samples" && ack["reason"] == 5 && !q.value("resync_attempted", false)) {
          auto saved = q; q["resync_attempted"] = true; perf_dictionary.clear();
          try { auto result = execute(op); q = saved; return result; } catch (...) { q = saved; throw; }
        }
        throw failure(7, "Perf request rejected, reason " + ack["reason"].dump());
      }
      std::map<unsigned, json> next_dictionary;
      auto seq = ack["sequence"].get<unsigned>();
      unsigned expected = ack["count"];
      std::set<unsigned> seen;
      json rows = json::array();
      bool ended = false;
      auto end = clock::now() + std::chrono::milliseconds(timeout_ms);
      while (!ended) {
        guard(op);
        for (auto it = incoming.begin(); it != incoming.end();) {
          auto word = it->word;
          if (!it->ack &&
              (word == 0x27 || word == 0x28 || word == 0x2a || word == 0x2b) &&
              reader(it->payload).u32(0) == seq) {
            reader r(it->payload);
            if (word == 0x27 && action == "dictionary") {
              auto item = decode(word, it->payload);
              if (item["index"].get<unsigned>() >= expected ||
                  !seen.insert(item["record_id"].get<unsigned>()).second)
                throw failure(6, "Duplicate or invalid Perf dictionary index");
              next_dictionary[item["record_id"]] = item;
              rows.push_back(item);
            } else if (word == 0x2a && action == "samples") {
              unsigned offset = 8;
              for (unsigned i = 0; i < r.u16(6); ++i) {
                auto id = r.u16(offset);
                if (!seen.insert(id).second)
                  throw failure(6, "Duplicate Perf sample record");
                if (!perf_dictionary.contains(id))
                  throw failure(6,
                                "Perf sample references unknown dictionary id");
                auto item = perf_dictionary[id];
                item["time_us"] = r.u32(offset + 2);
                item["max_us"] = r.u32(offset + 6);
                unsigned type = item["type"];
                if (type == 1) {
                  item["period_us"] = r.u32(offset + 10);
                  item["load"] = r.f32(offset + 14);
                  item["peak"] = r.f32(offset + 18);
                  offset += 22;
                } else if (type == 2) {
                  item["load"] = r.f32(offset + 10);
                  item["peak"] = r.f32(offset + 14);
                  offset += 18;
                } else if (type == 3)
                  offset += 10;
                else
                  throw failure(5, "Unknown Perf record type");
                rows.push_back(item);
                progress(op, {{"received", rows.size()}, {"total", expected}, {"items", json::array({item})}});
              }
            } else if (word == (action == "dictionary" ? 0x28 : 0x2b)) {
              auto final = checked(decode(word, it->payload));
              if (final["count"] != expected ||
                  (action == "dictionary" && final["version"] != ack["version"]))
                throw failure(6, "Perf end count/version mismatch");
              ended = true;
            }
            it = incoming.erase(it);
            end = clock::now() + std::chrono::milliseconds(timeout_ms);
          } else
            ++it;
        }
        if (clock::now() > end)
          throw failure(6, "Incomplete Perf transaction");
        if (!ended)
          pump();
      }
      if (rows.size() != expected)
        throw failure(6, "Perf record count mismatch: expected " +
                             std::to_string(expected) + ", got " +
                             std::to_string(rows.size()) + ", ack " +
                             ack.dump());
      if (action == "dictionary") { perf_dictionary = std::move(next_dictionary); perf_version = ack["version"]; }
      return rows;
    }
    throw failure(2, "Unknown Perf action");
  }
  throw failure(2, "Unknown command group");
}
} // namespace frame
