// SPDX-License-Identifier: MIT
#include "runtime.hpp"
#include "commander.hpp"
#include "symbols.hpp"
#include <filesystem>
#include <fstream>
#include <future>
namespace frame {
runtime::runtime() {
  comm_log.write("runtime_start", {{"pid", GetCurrentProcessId()}, {"build", __DATE__ " " __TIME__}});
  RegisterLinkedModules(registry);
  registry.Validate();
  registry.Start(*this);
  try {
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
        finish(op, 0, op->handler(*this, *op));
      } catch (const failure &e) {
        finish(op, e.code, nullptr, e.what());
      } catch (const std::exception &e) {
        finish(op, 2, nullptr, e.what());
      }
      if (op->exclusive_write)
        jlink_write_active_ = false;
    }
  });
  worker_ = std::jthread([this] { run(); });
  } catch (...) {
    stopping_ = true;
    cv_.notify_all();
    if (jlink_worker_.joinable()) jlink_worker_.join();
    registry.Stop(*this);
    throw;
  }
}
runtime::~runtime() {
  comm_log.write("runtime_shutdown_begin");
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
  registry.Stop(*this);
  comm_log.write("runtime_shutdown_end");
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
  if (comm_log.enabled() && op->command.value("group", "") != "data" && op->command.value("group", "") != "status")
    comm_log.write("operation_submitted", {{"id", op->id}, {"group", op->command.value("group", "")}, {"action", op->command.value("action", "")}});
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
  if (!it->second->cancel.exchange(true)) comm_log.write("cancel_requested", {{"id", id}});
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
  const auto &entry = registry.Find(op.command.value("group", std::string()), op.command.value("action", std::string()));
  events_.push_back({{"sequence", ++event_sequence_}, {"kind", entry.policy.progressKind},
                     {"operation_id", op.id}, {"data", std::move(data)}});
}
void runtime::finish(const std::shared_ptr<operation> &op, int code, json data,
                     std::string error) {
  if (comm_log.enabled() && (code != 0 || (op->command.value("group", "") != "data" && op->command.value("group", "") != "status")))
    comm_log.write("operation_end", {{"id", op->id}, {"group", op->command.value("group", "")}, {"action", op->command.value("action", "")}, {"code", code}, {"error", error}});
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
void runtime::append_stream(const std::string &group, json record) {
  for (auto &[id, s] : streams)
    if (s.group == group) {
      auto &data = datasets[id];
      const auto &definition = registry.FindStream(group);
      if (!definition.prepare(*this, s, data, record)) continue;
      auto &rows = data["records"];
      if (definition.retainedLimit != 0 && rows.size() >= definition.retainedLimit) {
        auto count = std::min<std::size_t>(4096, rows.size());
        rows.erase(rows.begin(), rows.begin() + count);
        data["dropped"] = data.value("dropped", 0ull) + count;
      }
      rows.push_back(record);
    }
}
void runtime::log_communication_state() {
  if (!comm_log.enabled() || clock::now() < diagnostic_due) return;
  diagnostic_due = clock::now() + std::chrono::seconds(1);
  json counts = json::array();
  for (const auto &[id, stream] : streams)
    counts.push_back({{"id", id}, {"group", stream.group}, {"records", datasets.at(id)["records"].size()}});
  comm_log.write("communication_state", {{"connected", serial.opened()}, {"endpoint", serial.endpoint},
      {"epoch", epoch_}, {"rx_bytes", rx_bytes}, {"tx_bytes", tx_bytes}, {"rejected", decoder.rejected},
      {"packets", received_packets}, {"ignored_packets", ignored_packets}, {"reports", report_packets},
      {"pending_bytes", receive_link.PendingBytes()}, {"unmatched_packets", incoming.size()}, {"dropped", dropped},
      {"rx_idle_ms", last_rx == clock::time_point{} ? -1 : std::chrono::duration_cast<std::chrono::milliseconds>(clock::now() - last_rx).count()},
      {"last_rx_prefix", last_rx_preview}, {"streams", counts}});
}
void runtime::pump(unsigned wait) {
  log_communication_state();
  if (receive_link.PendingBytes() != 0) { receive_link.Process(); return; }
  auto b = serial.read(wait);
  if (b.empty())
    return;
  rx_bytes += b.size();
  if (comm_log.enabled()) {
    last_rx = clock::now();
    last_rx_preview = hex(bytes(b.begin(), b.begin() + std::min<std::size_t>(b.size(), 48)));
  }
  append_stream("serial", {{"hex", hex(b)},
                           {"host_seconds", std::chrono::duration<double>(
                                                clock::now().time_since_epoch())
                                                .count()}});
  receive_link.Push(b);
  receive_link.Process();
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
  registry.Disconnected(*this);
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
    log_communication_state();
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
      if (comm_log.enabled() && op->command.value("group", "") != "data" && op->command.value("group", "") != "status")
        comm_log.write("operation_begin", {{"id", op->id}, {"group", op->command.value("group", "")},
            {"action", op->command.value("action", "")}, {"command_preview", op->command.dump().substr(0, 2048)}});
      try {
        guard(*op);
        auto data = execute(*op);
        if (!streams.contains(op->id) && !op->deferred) {
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
          receive_link.Reset();
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
      comm_log.write("receive_error", {{"error", e.what()}});
      serial.close();
      receive_link.Reset();
      incoming.clear();
      ++epoch_;
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
          if (!confirmed) registry.FindStream(s.group).stop(*this, stop_op);
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
        bool integrity_failed = registry.FindStream(s.group).finalize(*this, datasets[id]);
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
          receive_link.Reset();
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
        operation stop_op;
        stop_op.deadline = clock::now() + std::chrono::milliseconds(250);
        registry.FindStream(s.group).stop(*this, stop_op);
      }
    }
  } catch (...) {
  }
  serial.close();
}
} // namespace frame
