// SPDX-License-Identifier: MIT
#include "service_support.hpp"
namespace frame {
static json Handle(runtime &r, operation &op) {
  auto &q = op.command;
  auto group = q.value("group", std::string()), action = q.value("action", std::string());
  if (group == "serial" && action == "ports")
    return transport::ports();
  if (group == "serial" && action == "baud") {
    auto baud = r.serial.set_baud(q.at("baud").get<unsigned>());
    return {{"baud", baud}, {"endpoint", r.serial.endpoint}};
  }
    if (!r.streams.empty())
      throw failure(9, "Raw serial requires idle protocol jobs");
    auto b = q.contains("hex") ? unhex(q.at("hex")) : bytes();
    if (q.contains("text")) {
      auto text = q.at("text").get<std::string>();
      b.assign(text.begin(), text.end());
    }
    if (action == "send" || action == "raw") {
      r.monitor_protocol_rx = false;
      double duration = q.value("duration", 0.2),
             interval = q.value("interval", 0.0);
      if (!std::isfinite(duration) || duration < 0 || duration > 86400 ||
          !std::isfinite(interval) || interval < 0 || interval > 86400)
        throw failure(2, "Invalid serial duration/interval");
      if (b.size() > 1024 * 1024 || r.datasets.size() >= 32)
        throw failure(9, "Serial data capacity exceeded");
      if (!q.contains("timeout"))
        op.deadline = clock::now() +
                      std::chrono::milliseconds(
                          static_cast<std::int64_t>(duration * 1000) + 3000);
      auto &dataset = r.datasets[op.id];
      dataset = {{"schema_version", 1},
                 {"group", "serial"},
                 {"state", "running"},
                 {"records", json::array()},
                 {"dropped", 0}};
      auto &blocks = dataset["records"];
      std::size_t retained = 0;
      /* Append one direction-tagged block, evicting the oldest blocks when the
       * retained byte quota is exceeded. */
      auto push_block = [&](const char *dir, const char *monitor_kind, const bytes &data) {
        while (!blocks.empty() && retained + data.size() > 8 * 1024 * 1024) {
          retained -= blocks[0]["bytes"].get<std::size_t>();
          blocks.erase(blocks.begin());
          dataset["dropped"] = dataset["dropped"].get<unsigned>() + 1;
        }
        json block = {{"dir", dir}, {"hex", hex(data)}, {"bytes", data.size()}};
        blocks.push_back(block);
        retained += data.size();
        r.monitor(monitor_kind, data);
      };
      if (!b.empty()) {
        r.serial.write(b);
        r.tx_bytes += b.size();
        push_block("tx", "user_tx", b);
      }
      auto end = clock::now() +
                 std::chrono::milliseconds(static_cast<int>(duration * 1000));
      auto next = clock::now() +
                  std::chrono::milliseconds(static_cast<int>(interval * 1000));
      while (clock::now() < end) {
        r.guard(op);
        auto data = r.serial.read(10);
        if (!data.empty()) {
          r.rx_bytes += data.size();
          push_block("rx", "rx", data);
        }
        if (interval > 0 && clock::now() >= next) {
          r.serial.write(b);
          r.tx_bytes += b.size();
          push_block("tx", "user_tx", b);
          next = clock::now() +
                 std::chrono::milliseconds(static_cast<int>(interval * 1000));
        }
      }
      dataset["state"] = "complete";
      dataset["partial"] = dataset["dropped"] != 0;
      if (q.contains("output")) {
        r.export_dataset(op.id, q.at("output"));
      }
      return {{"dataset_id", op.id},
              {"records", blocks},
              {"count", blocks.size()},
              {"partial", dataset["partial"]}};
    }
    throw failure(2, "Unknown serial action");
  throw failure(2, "Unsupported serial command" );
}
static void Install(BackendRegistry &registry) {
  registry.Service({"serial", {}}); registry.Commands("serial", "serial", {"ports"}, Handle); registry.Commands("serial", "serial", {"baud"}, Handle, {ExecutionLane::Core,false,true}); registry.Commands("serial", "serial", {"send","raw"}, Handle, {ExecutionLane::Core,true});
}
FRAME_REGISTER_MODULE(frame_module_serial, Install)
} // namespace frame
