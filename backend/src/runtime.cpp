// SPDX-License-Identifier: MIT
#include "runtime.hpp"
#include "commander.hpp"
#include "symbols.hpp"
#include <filesystem>
#include <fstream>
#include <future>
namespace frame {
runtime::runtime() {
  publish();
  jlink_worker_ = std::jthread([this] {
    while (!stopping_) {
      std::shared_ptr<operation> op;
      {
        std::unique_lock lock(mutex_);
        cv_.wait_for(lock, std::chrono::milliseconds(20),
                     [this] { return stopping_ || !jlink_pending_.empty(); });
        if (stopping_)
          break;
        if (jlink_pending_.empty())
          continue;
        op = jlink_pending_.front();
        jlink_pending_.pop_front();
      }
      try {
        guard(*op);
        finish(op, 0, jlink(*op));
      } catch (const failure &e) {
        finish(op, e.code, nullptr, e.what());
      } catch (const std::exception &e) {
        finish(op, 2, nullptr, e.what());
      }
      if (op->command.value("action", std::string()) == "write")
        jlink_write_active_ = false;
    }
  });
  worker_ = std::jthread([this] { run(); });
}
runtime::~runtime() {
  stopping_ = true;
  {
    std::lock_guard lock(mutex_);
    for (auto &[id, op] : operations_)
      op->cancel = true;
  }
  cv_.notify_all();
  if (worker_.joinable())
    worker_.join();
  if (jlink_worker_.joinable())
    jlink_worker_.join();
  serial.close();
}
std::uint64_t runtime::submit(json cmd) {
  if (!cmd.is_object() || !cmd.contains("group") || !cmd["group"].is_string())
    throw failure(2, "Command object requires a group");
  for (auto key : {"baud", "dst", "dynamic_dst", "timeout", "response_timeout",
                   "id", "dataset", "offset", "limit", "period", "count",
                   "data_bits", "stop_bits", "revision", "probe", "tcp_port", "scan_ms", "discovery_port"})
    if (cmd.contains(key) &&
        (!cmd[key].is_number_integer() || cmd[key].get<std::int64_t>() < 0))
      throw failure(2, std::string(key) + " requires a nonnegative integer");
  if (cmd.value("dst", 2ull) > 255 || cmd.value("dynamic_dst", 0ull) > 255)
    throw failure(2, "Address outside uint8");
  if (cmd.value("tcp_port",9000ull) == 0 || cmd.value("tcp_port",9000ull) > 65535)
    throw failure(2,"TCP port outside 1..65535");
  auto timeout = cmd.value("timeout", 30000ull);
  if (timeout < 10 || timeout > 86400000)
    throw failure(2, "timeout outside 10..86400000 ms");
  if (cmd.value("baud", 115200ull) == 0 ||
      cmd.value("baud", 115200ull) > 12000000)
    throw failure(2, "Invalid baud rate");
  if (cmd.value("probe", 0ull) > UINT32_MAX ||
      cmd.value("id", 0ull) > UINT32_MAX)
    throw failure(2, "probe or id outside uint32");
  if (cmd.contains("period") &&
      (cmd.value("period", 0ull) < 1 || cmd.value("period", 0ull) > 60000))
    throw failure(2, "period outside 1..60000 ms");
  if (cmd.contains("response_timeout") &&
      (cmd.value("response_timeout", 0ull) < 10 ||
       cmd.value("response_timeout", 0ull) > 60000))
    throw failure(2, "response_timeout outside 10..60000 ms");
  auto bits = cmd.value("data_bits", 8ull);
  if (bits < 5 || bits > 8)
    throw failure(2, "data_bits outside 5..8");
  auto stops = cmd.value("stop_bits", 1ull);
  if (stops != 1 && stops != 2)
    throw failure(2, "stop_bits must be 1 or 2");
  std::lock_guard lock(mutex_);
  if (stopping_ || operations_.size() >= 128)
    throw failure(9, "Operation capacity reached");
  auto op = std::make_shared<operation>();
  op->id = next_++;
  op->deadline = clock::now() + std::chrono::milliseconds(timeout);
  op->command = std::move(cmd);
  operations_[op->id] = op;
  pending_.push_back(op);
  cv_.notify_one();
  return op->id;
}
int runtime::result(std::uint64_t id, std::string &text) {
  std::lock_guard lock(mutex_);
  auto it = operations_.find(id);
  if (it == operations_.end())
    return -1;
  if (!it->second->done)
    return 1;
  text =
      it->second->result.dump(-1, ' ', false, json::error_handler_t::replace);
  return 0;
}
int runtime::cancel(std::uint64_t id) {
  std::lock_guard lock(mutex_);
  auto it = operations_.find(id);
  if (it == operations_.end())
    return -1;
  it->second->cancel = true;
  return 0;
}
int runtime::release(std::uint64_t id) {
  std::lock_guard lock(mutex_);
  auto it = operations_.find(id);
  if (it == operations_.end())
    return -1;
  if (!it->second->done)
    return 1;
  operations_.erase(it);
  return 0;
}
std::string runtime::snapshot() {
  std::lock_guard lock(mutex_);
  return snapshot_.dump(-1, ' ', false, json::error_handler_t::replace);
}
std::string runtime::events(std::uint64_t after, unsigned limit) {
  std::lock_guard lock(mutex_);
  json rows = json::array();
  for (auto &event : events_)
    if (event["sequence"].get<std::uint64_t>() > after &&
        rows.size() < std::min(limit, 256u))
      rows.push_back(event);
  return json{
      {"events", rows},
      {"latest", event_sequence_},
      {"lost",
       !events_.empty() &&
           after + 1 < events_.front()["sequence"].get<std::uint64_t>()}}
      .dump();
}
void runtime::progress(const operation &op, json data) {
  std::lock_guard lock(mutex_);
  if (events_.size() >= 1024) events_.pop_front();
  auto group = op.command.value("group", "");
  events_.push_back({{"sequence", ++event_sequence_}, {"kind", group == "section" ? "section_nodes" : group == "perf" ? "perf_samples" : "parameter_directory"},
                     {"operation_id", op.id}, {"data", std::move(data)}});
}
void runtime::finish(const std::shared_ptr<operation> &op, int code, json data,
                     std::string error) {
  std::lock_guard lock(mutex_);
  op->result = {{"operation_id", op->id},
                {"code", code},
                {"ok", code == 0},
                {"error", error},
                {"data", std::move(data)}};
  op->done = true;
  if (events_.size() >= 1024)
    events_.pop_front();
  events_.push_back({{"sequence", ++event_sequence_},
                     {"kind", "operation_completed"},
                     {"operation_id", op->id},
                     {"code", code}});
}
void runtime::guard(const operation &op) {
  if (op.cancel || (op.parent && op.parent->cancel) || stopping_)
    throw failure(130, "Operation cancelled");
  if (clock::now() > op.deadline)
    throw failure(4, "Operation timed out; remote outcome may be unknown");
}
void runtime::publish() {
  json jobs = json::array();
  for (auto &[id, s] : streams)
    jobs.push_back({{"id", id}, {"group", s.group}});
  json sets = json::array();
  for (auto &[id, d] : datasets)
    sets.push_back({{"id", id},
                    {"group", d["group"]},
                    {"state", d.value("state", std::string())},
                    {"generation", d.value("generation", 0ull)},
                    {"count", d["records"].size()},
                    {"dropped", d.value("dropped", 0)}});
  std::lock_guard lock(mutex_);
  for (auto &[id, op] : operations_)
    if (!op->done && !streams.contains(id) &&
        op->command.value("group", std::string()) != "status")
      jobs.push_back({{"id", id},
                      {"group", op->command.value("group", std::string())},
                      {"background_stream", false}});
  snapshot_ = {{"connected", serial.opened()},
               {"baud", serial.baud_rate},
               {"endpoint", serial.endpoint},
               {"epoch", epoch_},
               {"rx_bytes", rx_bytes},
               {"tx_bytes", tx_bytes},
               {"rejected", decoder.rejected},
               {"dropped", dropped},
               {"jobs", jobs},
               {"datasets", sets}};
}
void runtime::clear_wave(std::uint64_t id, const std::string &reason) {
  auto &data = datasets.at(id);
  if (data.value("group", "") != "wave") throw failure(2, "Waveform dataset required");
  data["revision_base"] = data.value("revision_base", 0ull) + data["records"].size() + 1;
  data["records"] = json::array();
  data["generation"] = data.value("generation", 0ull) + 1;
  data["clear_reason"] = reason;
  data["dropped"] = 0;
  data["segment"] = data.value("segment", 0u) + 1;
}
void runtime::append_stream(const std::string &group, json record) {
  for (auto &[id, s] : streams)
    if (s.group == group) {
      auto &data = datasets[id];
      if (group == "wave") { record["segment"] = data.value("segment", 0u); record["period_ms"] = data.value("period_ms", 10u); }
      if (group == "trace" && record.contains("tick_extended"))
        record["time"] = record["tick_extended"].get<double>() *
                         data["control"].value("unit_us", 100u) / 1e6;
      if (group == "trace" && s.op->command.contains("filter") &&
          !s.op->command["filter"].get<std::string>().empty()) {
        auto filter = "," + s.op->command["filter"].get<std::string>() + ",";
        if (filter.find("," + record["line"].dump() + ",") == std::string::npos)
          continue;
      }
      auto &rows = data["records"];
      if (group != "wave" && rows.size() >= 100000) {
        rows.erase(rows.begin(), rows.begin() + 4096);
        data["dropped"] = data.value("dropped", 0) + 4096;
      }
      rows.push_back(record);
    }
}
bool runtime::receive_sfra_report(const packet &report) {
  if (report.ack || (report.word != 0x36 && report.word != 0x37)) return false;
  auto row = decode(report.word, report.payload);
  for (auto &[id, data] : datasets) {
    if (data.value("group", std::string()) != "sfra" || data.value("state", std::string()) != "running" ||
        data.value("epoch", 0ull) != epoch_ || data["metadata"]["id"] != row["id"] || data["metadata"]["tag"] != row["tag"]) continue;
    auto &records=data["records"];
    if (report.word==0x36) {
      if(row.value("status",0)!=0 || row.value("index",0u)>=1000000) {data["partial"]=true;return true;}
      auto duplicate=std::find_if(records.begin(),records.end(),[&](const json &item){return item["index"]==row["index"];});
      if(duplicate==records.end())records.push_back(row);
      else {data["duplicates"]=data.value("duplicates",0u)+1;if(*duplicate!=row)data["partial"]=true;}
      std::sort(records.begin(),records.end(),[](const json &a,const json &b){return a["index"]<b["index"];});
    } else {
      auto expected=row.value("count",0u);bool complete=records.size()==expected;
      for(unsigned index=0;index<records.size();++index)complete=complete&&records[index]["index"]==index;
      data["metadata"]=row;data["partial"]=data.value("partial",false)||!complete;
      data["state"]=data["partial"].get<bool>()?"partial":"complete";
    }
    return true;
  }
  return false;
}
void runtime::pump(unsigned wait) {
  auto b = serial.read(wait);
  if (b.empty())
    return;
  rx_bytes += b.size();
  append_stream("serial", {{"hex", hex(b)},
                           {"host_seconds", std::chrono::duration<double>(
                                                clock::now().time_since_epoch())
                                                .count()}});
  for (auto &p : decoder.feed(b)) {
    if (p.group != 1 || !(p.dst == 1 || p.dst == 0) || p.src != dst)
      continue;
    if ((p.word==0x36||p.word==0x37)&&!p.ack&&receive_sfra_report(p)) {
      continue;
    } else if (p.word == 0x40 && !p.ack) {
      auto batch = decode(p.word, p.payload);
      auto tick = batch["tick_100us"].get<std::uint32_t>();
      // 0x40 is the ordered PLECS simulation-time protocol. A new sample
      // returning to an earlier time starts a new simulation, not a MCU epoch.
      bool restarted = false;
      for (auto &[id, stream] : streams) if (stream.group == "wave") {
        auto &data = datasets[id];
        bool new_connection = data.value("simulation_epoch", epoch_) != epoch_;
        auto previous = data.value("simulation_tick", tick);
        bool backwards = batch["first"] == 0 && tick < previous && previous - tick <= 0x80000000u;
        if (new_connection || backwards) {
          clear_wave(id, "simulation_restart");
          restarted = true;
        }
        data["simulation_epoch"] = epoch_;
        if (batch["first"] == 0) data["simulation_tick"] = tick;
      }
      if (restarted) { wave_clock = {}; wave_integrity = {}; }
      wave_integrity.observe(tick, batch["total"], batch["first"],
                             static_cast<unsigned>(batch["items"].size()));
      auto extended = wave_clock.extend(tick);
      for (auto row : batch["items"]) {
        row["time"] = double(extended) / 10000;
        row["time_source"] = "device_100us";
        append_stream("wave", row);
      }
    } else if (p.word == 7 && !p.ack) {
      reader wave(p.payload);
      if (p.payload.size() == 6 && wave.u8(0) == 0 &&
          (wave.u32(2) == 0xAAAAAAAA || wave.u32(2) == 0x55555555))
        continue;
      auto row = parameter(p.payload, 6);
      row["time"] =
          std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch())
              .count();
      row["time_source"] = "host_receive";
      append_stream("wave", row);
    } else if (p.word == 0x2d && !p.ack) {
      auto row = decode(p.word, p.payload);
      row["tick_extended"] = trace_clock.extend(row["tick"]);
      append_stream("trace", row);
    } else {
      if (incoming.size() >= 4096) {
        incoming.pop_front();
        ++dropped;
      }
      incoming.push_back(std::move(p));
    }
  }
}
void runtime::send(unsigned word, const bytes &payload) {
  packet p;
  p.src = 1;
  p.dst = static_cast<std::uint8_t>(dst);
  p.dynamic_dst = static_cast<std::uint8_t>(dynamic_dst);
  p.word = static_cast<std::uint8_t>(word);
  p.ack = 0;
  p.payload = payload;
  auto b = encode(p);
  serial.write(b);
  tx_bytes += b.size();
}
packet runtime::wait_packet(operation &op, unsigned word, bool ack,
                            const std::function<bool(const packet &)> &match) {
  auto end = clock::now() + std::chrono::milliseconds(timeout_ms);
  while (true) {
    guard(op);
    for (auto it = incoming.begin(); it != incoming.end(); ++it)
      if (it->word == word && (it->ack != 0) == ack && (!match || match(*it))) {
        auto p = std::move(*it);
        incoming.erase(it);
        return p;
      }
    if (clock::now() > end)
      throw failure(4, "Response timeout for command " + std::to_string(word));
    pump();
  }
}
json runtime::query(operation &op, unsigned word, const bytes &payload,
                    const std::function<bool(const packet &)> &match) {
  send(word, payload);
  auto p = wait_packet(op, word, true, match);
  auto result = decode(static_cast<std::uint8_t>(word), p.payload);
  if (result.contains("status") && result["status"] != 0)
    throw failure(7, "Device status " + result["status"].dump());
  if (result.contains("success") && !result["success"].get<bool>())
    throw failure(7, "Device reported failure");
  if (result.contains("accepted") && !result["accepted"].get<bool>())
    throw failure(7, "Device rejected request");
  return result;
}
void runtime::export_dataset(std::uint64_t id, const std::string &path) {
  auto it = datasets.find(id);
  if (it == datasets.end())
    throw failure(2, "Unknown dataset");
  auto dest = std::filesystem::path(wide(path));
  auto writer = std::async(std::launch::async, [data = it->second, dest] {
    auto temp = dest;
    temp += L".partial." + std::to_wstring(GetCurrentProcessId()) + L"." +
            std::to_wstring(clock::now().time_since_epoch().count());
    std::ofstream f(temp, std::ios::binary);
    if (!f)
      throw failure(8, "Cannot create export");
    if (dest.extension() == L".csv") {
      auto &rows = data["records"];
      if (!rows.empty()) {
        std::vector<std::string> keys;
        for (auto item = rows[0].begin(); item != rows[0].end(); ++item)
          keys.push_back(item.key());
        auto cell = [&f](std::string s) {
          f << '"';
          for (auto c : s) {
            if (c == '"')
              f << '"';
            f << c;
          }
          f << '"';
        };
        for (std::size_t i = 0; i < keys.size(); ++i) {
          if (i)
            f << ',';
          cell(keys[i]);
        }
        f << '\n';
        for (auto &row : rows) {
          for (std::size_t i = 0; i < keys.size(); ++i) {
            if (i)
              f << ',';
            cell(row.contains(keys[i]) ? (row[keys[i]].is_string()
                                              ? row[keys[i]].get<std::string>()
                                              : row[keys[i]].dump())
                                       : "");
          }
          f << '\n';
        }
      }
    } else
      f << data.dump(2);
    f.flush();
    if (!f)
      throw failure(8, "Export write failed");
    f.close();
    if (!MoveFileExW(temp.c_str(), dest.c_str(),
                     MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
      throw failure(8, "Export replace failed");
  });
  while (writer.wait_for(std::chrono::milliseconds(0)) !=
         std::future_status::ready) {
    if (serial.opened())
      pump();
    else
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  writer.get();
}
void runtime::fail_streams(int code, const std::string &error) {
  for (auto &[id, s] : streams) {
    auto &data = datasets[id];
    data["state"] = "partial";
    data["partial"] = true;
    data["stop_confirmed"] = false;
    data["error"] = error;
    json result = {{"dataset_id", id},
                   {"count", data["records"].size()},
                   {"partial", true},
                   {"stop_confirmed", false}};
    if (s.op->command.contains("output")) {
      try {
        export_dataset(id, s.op->command["output"]);
      } catch (const std::exception &e) {
        result["export_error"] = e.what();
      }
    }
    finish(s.op, code, result, error);
  }
  streams.clear();
  stream_count_ = 0;
}
void runtime::run() {
  while (!stopping_) {
    std::shared_ptr<operation> op;
    {
      std::unique_lock lock(mutex_);
      if (pending_.empty() && !serial.opened() && streams.empty())
        cv_.wait_for(lock, std::chrono::milliseconds(10));
      if (!pending_.empty()) {
        op = pending_.front();
        pending_.pop_front();
      }
    }
    if (op) {
      try {
        guard(*op);
        auto data = execute(*op);
        auto group = op->command.value("group", std::string());
        auto action = op->command.value("action", std::string());
        if (group == "connect" || group == "disconnect" ||
            (group == "serial" && (action == "connect" || action == "baud")))
          publish(); // Connection completion must expose the new state immediately.
        if (!streams.contains(op->id) &&
            op->command.value("group", std::string()) != "jlink") {
          int result_code =
              data.is_object() && data.value("partial", false) ? 6 : 0;
          finish(op, result_code, std::move(data));
        }
      } catch (const failure &e) {
        json partial = nullptr;
        if (datasets.contains(op->id)) {
          auto &d = datasets[op->id];
          d["state"] = "partial";
          d["error"] = e.what();
          partial = {{"dataset_id", op->id},
                     {"count", d["records"].size()},
                     {"partial", true}};
          if (op->command.contains("output")) {
            try {
              export_dataset(op->id, op->command["output"]);
            } catch (const std::exception &ex) {
              partial["export_error"] = ex.what();
            }
          }
        }
        finish(op, e.code, partial, e.what());
        if (e.code == 4 || e.code == 130) {
          serial.close();
          incoming.clear();
          decoder.reset();
          ++epoch_;
          fail_streams(3, "Serial session invalidated by failed transaction; "
                          "remote stop not confirmed");
        }
      } catch (const std::exception &e) {
        finish(op, 2, nullptr, e.what());
      }
    }
    try {
      if (serial.opened())
        pump();
    } catch (const std::exception &e) {
      serial.close();
      fail_streams(3, e.what());
    }
    for (auto it = streams.begin(); it != streams.end();) {
      auto &s = it->second;
      bool expired =
          s.op->command.contains("timeout") && clock::now() >= s.op->deadline;
      if (s.op->cancel || expired || clock::now() >= s.end ||
          (s.op->command.value("count", 0ull) > 0 &&
           datasets[it->first]["records"].size() +
                   datasets[it->first].value("dropped", 0ull) >=
               s.op->command.value("count", 0ull))) {
        std::string stop_error;
        bool confirmed = s.stop_confirmed;
        try {
          operation stop_op;
          stop_op.deadline = clock::now() + std::chrono::seconds(3);
          if (!confirmed && s.group == "wave")
            query(stop_op, 0x0c, {0});
          if (!confirmed && s.group == "trace")
            query(stop_op, 0x2c, {0});
          confirmed = true;
        } catch (const std::exception &e) {
          stop_error = e.what();
        }
        auto id = it->first;
        datasets[id]["state"] = s.op->cancel ? "cancelled"
                                : expired    ? "partial"
                                             : "complete";
        datasets[id]["partial"] = datasets[id].value("dropped", 0) > 0 ||
                                  s.op->cancel.load() || expired || !confirmed;
        datasets[id]["stop_confirmed"] = confirmed;
        if (s.group == "wave")
          datasets[id]["integrity"] = {
              {"missing",
               wave_integrity.missing + wave_integrity.pending_missing()},
              {"duplicates", wave_integrity.duplicates},
              {"time_wraps", wave_clock.wraps},
              {"out_of_order", wave_clock.out_of_order}};
        if (s.group == "trace")
          datasets[id]["integrity"] = {
              {"time_wraps", trace_clock.wraps},
              {"out_of_order", trace_clock.out_of_order}};
        bool integrity_failed =
            s.group == "wave" &&
            (wave_integrity.missing || wave_integrity.pending_missing() ||
             wave_integrity.duplicates || wave_clock.out_of_order);
        integrity_failed = integrity_failed ||
                           (s.group == "trace" && trace_clock.out_of_order);
        if (integrity_failed)
          datasets[id]["partial"] = true;
        try {
          auto path = s.op->command.value("output", std::string());
          if (!path.empty())
            export_dataset(id, path);
        } catch (const std::exception &e) {
          stop_error = e.what();
        }
        finish(s.op,
               stop_error.empty() ? (s.op->cancel       ? 130
                                     : expired          ? 4
                                     : integrity_failed ? 6
                                                        : 0)
                                  : 8,
               {{"dataset_id", id},
                {"count", datasets[id]["records"].size()},
                {"stop_confirmed", confirmed},
                {"partial", datasets[id]["partial"]},
                {"integrity", datasets[id].value("integrity", json::object())},
                {"dropped", datasets[id].value("dropped", 0)}},
               stop_error);
        it = streams.erase(it);
        stream_count_ = static_cast<unsigned>(streams.size());
        if (!confirmed) {
          serial.close();
          incoming.clear();
          decoder.reset();
          ++epoch_;
          fail_streams(3, "Serial session invalidated after unconfirmed stop");
          break;
        }
      } else
        ++it;
    }
    publish();
  }
  try {
    if (serial.opened()) {
      for (auto &[id, s] : streams) {
        if (s.group == "wave")
          send(0x0c, {0});
        if (s.group == "trace")
          send(0x2c, {0});
      }
    }
  } catch (...) {
  }
  serial.close();
}
} // namespace frame
