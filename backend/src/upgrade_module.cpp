// SPDX-License-Identifier: MIT
#include "runtime.hpp"
#include "firmware_image.hpp"
#include <algorithm>
namespace frame {
static json Inspect(runtime &, operation &op) {
  return firmware_image::load(op.command.at("path").get<std::string>()).describe();
}
static json Download(runtime &r, operation &op) {
  const auto image = firmware_image::load(op.command.at("path").get<std::string>());
  if (r.wire_mode != "e8") throw failure(2, "This Shuttle endpoint implements published E8; select wire=e8");
  if (r.active_streams()) throw failure(7, "Stop active capture streams before firmware download");
  if (r.probe_write_active()) throw failure(9, "Wait for the active probe write before firmware download");
  const auto exchange = [&](unsigned word, const bytes &payload, std::size_t reply_size) {
    for (unsigned attempt = 0; attempt < 3; ++attempt) {
      r.guard(op); r.pump(0);
      std::erase_if(r.incoming, [word](const packet &p) { return p.word == word && p.ack; });
      r.send(word, payload);
      try {
        return r.wait_packet(op, word, true, [&](const packet &p) {
          return p.payload.size() == reply_size && p.dynamic_src == r.dynamic_dst && p.dynamic_dst == 0;
        }).payload;
      } catch (const failure &e) {
        r.guard(op); if (e.code != 4 || attempt == 2) throw;
      }
    }
    throw failure(4, "Firmware response unavailable");
  };
  auto reply = exchange(0x08, image.info(op.command.value("force", false)), 3);
  if (reply[0] != 1) throw failure(7, "Firmware INFO rejected; reason mask=" + std::to_string(reader(reply).u16(1)));
  while (exchange(0x09, {}, 1)[0] != 1) { r.guard(op); r.pump(10); }
  for (std::size_t offset = 0; offset < image.size(); offset += 1024) {
    const auto block = image.block(offset);
    bool accepted = false;
    for (unsigned attempt = 0; attempt < 3 && !accepted; ++attempt) accepted = exchange(0x0A, block, 1)[0] == 1;
    if (!accepted) throw failure(7, "Firmware DATA rejected at offset " + std::to_string(offset));
    r.progress(op, {{"kind","firmware_download"},{"bytes",std::min(offset+1024,image.size())},{"total",image.size()}});
  }
  if (exchange(0x0B, image.end(), 1)[0] != 1) throw failure(7, "Device rejected final image validation/commit");
  auto result = image.describe(); result["committed"] = true; result["running"] = "not confirmed";
  return result;
}
static void Install(BackendRegistry &registry) {
  registry.Service({"upgrade", {"frame-protocol"}});
  registry.Commands("upgrade", "upgrade", {"inspect"}, Inspect);
  registry.Commands("upgrade", "upgrade", {"download"}, Download,
    {ExecutionLane::Core, true, true, true, "frame-v1", "firmware_download"});
}
FRAME_REGISTER_MODULE(frame_module_upgrade, Install)
} // namespace frame
