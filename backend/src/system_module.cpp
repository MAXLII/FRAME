// SPDX-License-Identifier: MIT
#include "runtime.hpp"
#include "discovery.hpp"
namespace frame {
static json Status(runtime &r, operation &) { return json::parse(r.snapshot()); }
static json Catalog(runtime &r, operation &) { return r.registry.Catalog(); }
static json Connect(runtime &r, operation &op) { return r.connect_device(op); }
static json Disconnect(runtime &r, operation &op) { return r.disconnect_device(op); }
static json Discover(runtime &r, operation &op) {
  return ethernet_discovery::scan(op.command, [&] { r.guard(op); if (r.serial.opened()) r.pump(0); });
}
static void Install(BackendRegistry &registry) {
  registry.Service({"system", {}});
  registry.Commands("system", "status", {""}, Status);
  registry.Commands("system", "backend", {"catalog"}, Catalog);
  registry.Commands("system", "connect", {""}, Connect, {ExecutionLane::Core,false,true});
  registry.Commands("system", "serial", {"connect"}, Connect, {ExecutionLane::Core,false,true});
  registry.Commands("system", "disconnect", {""}, Disconnect, {ExecutionLane::Core,false,true});
  registry.Commands("system", "ethernet", {"discover"}, Discover);
}
FRAME_REGISTER_MODULE(frame_module_system, Install)
} // namespace frame
