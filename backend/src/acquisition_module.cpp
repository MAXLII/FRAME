// SPDX-License-Identifier: MIT
#include "service_support.hpp"
namespace frame {
static json Handle(runtime &r, operation &op) {
  auto &q = op.command;
  auto group = q.value("group", std::string()), action = q.value("action", std::string());
    unsigned control = group == "wave" ? 0x0c : 0x2c;
    if (group == "wave" && action == "period") {
      auto period = q.value("period", 0u);
      if (period == 0 || period > 60000) throw failure(2, "Period must be in 1..60000 ms");
      bytes payload; put(payload, period, 4); auto ack = r.query(op, 6, payload);
      for (auto &[id, stream] : r.streams) if (stream.group == "wave") r.datasets[id]["period_ms"] = period;
      return ack;
    }
    if (action == "stop") {
      auto ack = r.query(op, control, {0});
      for (auto &[id, s] : r.streams)
        if (s.group == group) {
          s.stop_confirmed = true;
          s.end = clock::now();
        }
      return ack;
    }
    if (action == "status")
      return json::parse(r.snapshot());
    if (action != "capture" && action != "start")
      throw failure(2, "Expected capture/start/stop/status");
    if (r.probe_write_active())
      throw failure(9, "J-Link write is active");
    for (auto &[id, s] : r.streams)
      if (s.group == group)
        throw failure(9, "Acquisition already running");
    auto resume = group == "wave" ? q.value("resume_dataset", std::uint64_t(0)) : 0;
    if (resume && (!r.datasets.contains(resume) || r.datasets[resume]["group"] != "wave" || r.datasets[resume]["state"] == "running"))
      throw failure(2, "Resume requires a stopped wave dataset");
    if (r.streams.size() >= 4 || (r.datasets.size() >= 32 && !resume))
      throw failure(9, "Dataset/job quota reached");
    double duration = q.value("duration", 10.0);
    if (!std::isfinite(duration) || duration < 0 || duration > 86400)
      throw failure(2, "Duration must be in [0,86400]; 0 means continuous capture");
    if (q.value("period", 10u) == 0 || q.value("period", 10u) > 60000)
      throw failure(2, "Period must be in 1..60000 ms");
    if (group == "wave") {
      r.wave_clock = {};
      r.wave_integrity = {};
      bytes b;
      put(b, q.value("period", 10u), 4);
      r.send(6, b);
      r.wait_packet(op, 6);
    }
    if (group == "trace")
      r.trace_clock = {};
    auto ack = r.query(op, control, {1});
    r.datasets[op.id] = {{"schema_version", 1}, {"group", group},
                       {"state", "running"},  {"records", json::array()},
                       {"control", ack},      {"dropped", 0}};
    if (group == "wave") {
      r.datasets[op.id]["period_ms"] = q.value("period", 10u);
      r.datasets[op.id]["segment"] = resume ? r.datasets[resume].value("segment", 0u) + 1 : 0;
      if (resume) {
        for (const auto *field : {"generation", "revision_base", "simulation_tick", "simulation_epoch"})
          if (r.datasets[resume].contains(field)) r.datasets[op.id][field] = r.datasets[resume][field];
        r.datasets[op.id]["records"] = std::move(r.datasets[resume]["records"]);
        r.datasets[op.id]["dropped"] = r.datasets[resume].value("dropped", 0);
        r.datasets.erase(resume);
      }
    }
    r.begin_stream(op, group, duration);
    return {{"dataset_id", op.id}};
  throw failure(2, "Unsupported acquisition command" );
}
static bool ReceiveSimulation(runtime &r, const packet &p) {
      auto batch = decode(p.word, p.payload);
      auto tick = batch["tick_100us"].get<std::uint32_t>();
      // 0x40 is the ordered PLECS simulation-time protocol. A new sample
      // returning to an earlier time starts a new simulation, not a MCU epoch.
      bool restarted = false;
      for (auto &[id, stream] : r.streams) if (stream.group == "wave") {
        auto &data = r.datasets[id];
        bool new_connection = data.value("simulation_epoch", r.epoch()) != r.epoch();
        auto previous = data.value("simulation_tick", tick);
        bool backwards = batch["first"] == 0 && tick < previous && previous - tick <= 0x80000000u;
        if (new_connection || backwards) {
          r.clear_wave(id, "simulation_restart");
          restarted = true;
        }
        data["simulation_epoch"] = r.epoch();
        if (batch["first"] == 0) data["simulation_tick"] = tick;
      }
      if (restarted) { r.wave_clock = {}; r.wave_integrity = {}; }
      r.wave_integrity.observe(tick, batch["total"], batch["first"],
                             static_cast<unsigned>(batch["items"].size()));
      auto extended = r.wave_clock.extend(tick);
      for (auto row : batch["items"]) {
        row["time"] = double(extended) / 10000;
        row["time_source"] = "device_100us";
        r.append_stream("wave", row);
      }
  return true;
}
static bool ReceiveMcu(runtime &r, const packet &p) {
      reader wave(p.payload);
      if (p.payload.size() == 6 && wave.u8(0) == 0 &&
          (wave.u32(2) == 0xAAAAAAAA || wave.u32(2) == 0x55555555))
        return true;
      auto row = parameter(p.payload, 6);
      row["time"] =
          std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch())
              .count();
      row["time_source"] = "host_receive";
      r.append_stream("wave", row);
  return true;
}
static bool ReceiveTrace(runtime &r, const packet &p) {
      auto row = decode(p.word, p.payload);
      row["tick_extended"] = r.trace_clock.extend(row["tick"]);
      r.append_stream("trace", row);
  return true;
}
static void StopWave(runtime &r, operation &op) { r.query(op, 0x0c, {0}); }
static void StopTrace(runtime &r, operation &op) { r.query(op, 0x2c, {0}); }
static bool PrepareWave(runtime &, const stream_job &, json &data, json &record) {
  record["segment"] = data.value("segment", 0u);
  record["period_ms"] = data.value("period_ms", 10u);
  return true;
}
static bool PrepareTrace(runtime &, const stream_job &stream, json &data, json &record) {
  if (record.contains("tick_extended"))
    record["time"] = record["tick_extended"].get<double>() * data["control"].value("unit_us", 100u) / 1e6;
  const auto filter = stream.op->command.value("filter", std::string());
  return filter.empty() || ("," + filter + ",").find("," + record["line"].dump() + ",") != std::string::npos;
}
static bool FinalizeWave(runtime &r, json &data) {
  const auto &integrity = r.wave_integrity;
  const auto &time = r.wave_clock;
  data["integrity"] = {{"missing", integrity.missing + integrity.pending_missing()},
    {"duplicates", integrity.duplicates}, {"time_wraps", time.wraps}, {"out_of_order", time.out_of_order}};
  return integrity.missing || integrity.pending_missing() || integrity.duplicates || time.out_of_order;
}
static bool FinalizeTrace(runtime &r, json &data) {
  data["integrity"] = {{"time_wraps", r.trace_clock.wraps}, {"out_of_order", r.trace_clock.out_of_order}};
  return r.trace_clock.out_of_order != 0;
}
static void Install(BackendRegistry &registry) {
  registry.Stream({"acquisition", "wave", StopWave, PrepareWave, FinalizeWave, 0});
  registry.Stream({"acquisition", "trace", StopTrace, PrepareTrace, FinalizeTrace});
  registry.Report({"acquisition", "frame-v1", 1, 0x40, ReceiveSimulation});
  registry.Report({"acquisition", "frame-v1", 1, 7, ReceiveMcu});
  registry.Report({"acquisition", "frame-v1", 1, 0x2d, ReceiveTrace});
  registry.Service({"acquisition", {"frame-protocol","data"}}); registry.Commands("acquisition", "wave", {"period","capture","start","stop","status"}, Handle, CommandPolicy{ExecutionLane::Core, true, false, false, "frame-v1"}); registry.Commands("acquisition", "trace", {"capture","start","stop","status"}, Handle, CommandPolicy{ExecutionLane::Core, true, false, false, "frame-v1"});
}
FRAME_REGISTER_MODULE(frame_module_acquisition, Install)
} // namespace frame
