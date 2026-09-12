// SPDX-License-Identifier: MIT
#include "runtime.hpp"
#include "frame_stream_decoder.hpp"
namespace frame {
void runtime::receive_packet(packet p) {
  ++received_packets;
  if (p.group != 1 || !(p.dst == 1 || p.dst == 0) || p.src != dst) { ++ignored_packets; return; }
  if (registry.DispatchReport(protocol_name, *this, p)) { ++report_packets; return; }
  if (comm_log.enabled() && p.ack) comm_log.write("ack_received", {{"word", p.word}, {"source", p.src}, {"bytes", p.payload.size()}});
  if (incoming.size() >= 4096) { incoming.pop_front(); ++dropped; }
  incoming.push_back(std::move(p));
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
  if (comm_log.enabled()) comm_log.write("tx_begin", {{"word", word}, {"dst", dst}, {"bytes", b.size()}, {"prefix", hex(bytes(b.begin(), b.begin() + std::min<std::size_t>(b.size(), 48)))}});
  serial.write(b);
  tx_bytes += b.size();
  if (comm_log.enabled()) comm_log.write("tx_end", {{"word", word}, {"tx_bytes", tx_bytes}});
}
packet runtime::wait_packet(operation &op, unsigned word, bool ack,
                            const std::function<bool(const packet &)> &match) {
  auto end = clock::now() + std::chrono::milliseconds(timeout_ms);
  if (comm_log.enabled()) comm_log.write("ack_wait_begin", {{"id", op.id}, {"word", word}, {"ack", ack}, {"timeout_ms", timeout_ms}});
  while (true) {
    guard(op);
    for (auto it = incoming.begin(); it != incoming.end(); ++it)
      if (it->word == word && (it->ack != 0) == ack && (!match || match(*it))) {
        auto p = std::move(*it);
        incoming.erase(it);
        if (comm_log.enabled()) comm_log.write("ack_matched", {{"id", op.id}, {"word", word}});
        return p;
      }
    if (clock::now() > end) {
      if (comm_log.enabled()) comm_log.write("ack_timeout", {{"id", op.id}, {"word", word}, {"rx_bytes", rx_bytes}, {"rejected", decoder.rejected}});
      throw failure(4, "Response timeout for command " + std::to_string(word));
    }
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

static std::unique_ptr<StreamDecoder> Create(runtime &r) {
  return std::make_unique<FrameStreamDecoder>(r.decoder, [&r](packet p) { r.receive_packet(std::move(p)); });
}
static void Start(runtime &r) { r.receive_link.AddDecoder(r.registry.FindProtocol(r.protocol_name).create(r)); }
static void Stop(runtime &r) noexcept { r.receive_link.Reset(); }
static void Install(BackendRegistry &registry) {
  registry.Service({"frame-protocol", {"system"}, Start, Stop});
  registry.Protocol({"frame-protocol", "frame-v1", Create});
}
FRAME_REGISTER_MODULE(frame_module_protocol, Install)
} // namespace frame
