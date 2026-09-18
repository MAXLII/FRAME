// SPDX-License-Identifier: MIT
#include "runtime.hpp"
namespace frame {
json runtime::connect_device(operation &op) {
  auto &q = op.command;
    const auto selected = q.value("protocol", std::string("frame-v1"));
    const auto &definition = registry.FindProtocol(selected);
    if (!streams.empty())
      throw failure(9, "Stop acquisition jobs before reconnecting");
    StreamLink nextLink;
    nextLink.AddDecoder(definition.create(*this));
    serial.open(q, [&] { guard(op); });
    registry.Disconnected(*this);
    ++epoch_;
    incoming.clear();
    receive_link.Reset();
    receive_link = std::move(nextLink);
    protocol_name = selected;
    dst = q.value("dst", 2u);
    dynamic_dst = q.value("dynamic_dst", 0u);
    if (dst > 255 || dynamic_dst > 255) {
      serial.close();
      throw failure(2, "Address outside uint8");
    }
    /* Wire protocol selection affects sending only; the receiver keeps
     * parsing both 0xE8 and 0xE9 frames regardless of this choice. */
    const auto wire = q.value("wire", wire_mode);
    if (wire != "auto" && wire != "e8" && wire != "e9") {
      serial.close();
      throw failure(2, "wire must be auto, e8, or e9");
    }
    wire_mode = wire;
    comm_v1_negotiated = false;
    comm_v1_next_seq = 0;
    {
      /* Drop throttled monitor records that belong to the previous session. */
      std::lock_guard lock(mutex_);
      monitor_pending_ = json::array();
      monitor_flush_due_ = clock::time_point::min();
    }
    probe_comm_v1();
    return {{"connected", true}, {"endpoint", serial.endpoint}, {"wire", wire_mode}};
}
json runtime::disconnect_device(operation &) {
    if (!streams.empty())
      throw failure(9, "Cancel jobs before disconnecting");
    serial.close();
    registry.Disconnected(*this);
    ++epoch_;
    incoming.clear();
    receive_link.Reset();
    {
      /* Drop throttled monitor records that belong to the closed session. */
      std::lock_guard lock(mutex_);
      monitor_pending_ = json::array();
      monitor_flush_due_ = clock::time_point::min();
    }
    return {{"connected", false}};
}
json runtime::set_wire(operation &op) {
    const auto wire = op.command.value("wire", std::string());
    if (wire != "auto" && wire != "e8" && wire != "e9")
      throw failure(2, "wire must be auto, e8, or e9");
    wire_mode = wire;
    comm_v1_negotiated = false;
    comm_v1_next_seq = 0;
    /* Re-probe while connected so forced 0xE9 and auto mode negotiate
     * compression again; forced 0xE8 simply stays on the legacy sender. */
    probe_comm_v1();
    return {{"wire", wire_mode}, {"negotiated", comm_v1_negotiated}};
}
void runtime::begin_stream(operation &op, const std::string &group, double duration) {
  registry.FindStream(group);
  std::shared_ptr<operation> ptr;
  { std::lock_guard lock(mutex_); ptr = operations_.at(op.id); }
  streams[op.id] = {ptr, group, duration == 0 ? clock::time_point::max() : clock::now() +
    std::chrono::milliseconds(static_cast<std::int64_t>(duration * 1000))};
  stream_count_ = static_cast<unsigned>(streams.size());
}
json runtime::execute(operation &op) {
  auto &q = op.command;
  const auto &entry = registry.Find(q.value("group", std::string()), q.value("action", std::string()));
  timeout_ms = q.value("response_timeout", 1500u);
  if (timeout_ms < 10 || timeout_ms > 60000) throw failure(2, "response_timeout outside 10..60000 ms");
  if (entry.policy.lane == ExecutionLane::Probe) {
    if (entry.policy.exclusiveWrite) {
      if (stream_count_ != 0) throw failure(9, "Stop acquisition before J-Link writes");
      if (jlink_write_active_.exchange(true)) throw failure(9, "J-Link write already queued");
    }
    try {
      std::lock_guard lock(mutex_);
      op.handler = entry.handler;
      op.exclusive_write = entry.policy.exclusiveWrite;
      jlink_pending_.push_back(operations_.at(op.id));
      op.deferred = true;
    } catch (...) { if (entry.policy.exclusiveWrite) jlink_write_active_ = false; throw; }
    cv_.notify_all();
    return nullptr;
  }
  if (entry.policy.transport && !serial.opened()) {
    if (!q.contains("port") && !q.contains("replay") && q.value("transport", std::string()) != "tcp")
      throw failure(3, "Connect a device first, or provide --port / --transport tcp --host IP");
    connect_device(op);
  }
  if (!entry.policy.protocol.empty() && entry.policy.protocol != protocol_name)
    throw failure(2, "Command is not supported by the connected protocol");
  if (entry.policy.transport && !entry.policy.protocol.empty()) {
    const auto next_dst = q.value("dst", dst);
    const auto next_dynamic_dst = q.value("dynamic_dst", dynamic_dst);
    if (next_dst > 255 || next_dynamic_dst > 255)
      throw failure(2, "Address outside uint8");
    if (next_dst != dst || next_dynamic_dst != dynamic_dst) {
      if (!streams.empty())
        throw failure(9, "Stop acquisition before changing target address");
      // The core worker serializes transactions. Only change target between
      // operations, and discard device-specific state without closing the link.
      registry.Disconnected(*this);
      incoming.clear();
      receive_link.Reset();
      ++epoch_;
      dst = next_dst;
      dynamic_dst = next_dynamic_dst;
    }
  }
  auto result = entry.handler(*this, op);
  if (entry.policy.publish) publish();
  return result;
}
} // namespace frame
