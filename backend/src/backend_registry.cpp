// SPDX-License-Identifier: MIT
#include "backend_registry.hpp"
#include <algorithm>
#include <cstring>
#include <functional>
#include <set>
#include <utility>

#pragma section(".frmod$a", read)
#pragma section(".frmod$z", read)
extern "C" {
__declspec(allocate(".frmod$a")) extern const frame::ModuleRegistration *const frame_modules_begin = nullptr;
__declspec(allocate(".frmod$z")) extern const frame::ModuleRegistration *const frame_modules_end = nullptr;
}
namespace frame {
void BackendRegistry::Mutable() const { if (frozen_) throw failure(2, "Backend registry is frozen"); }
void BackendRegistry::Service(ServiceRegistration r) {
  Mutable();
  if (r.name.empty() || services_.contains(r.name)) throw failure(2, "Duplicate or unnamed backend service: " + r.name);
  auto key = r.name; services_.emplace(std::move(key), std::move(r));
}
void BackendRegistry::Commands(std::string owner, std::string group, std::initializer_list<const char *> actions,
                               CommandHandler handler, CommandPolicy policy) {
  Mutable();
  if (owner.empty() || group.empty() || !handler || actions.size() == 0) throw failure(2, "Invalid command registration");
  std::set<std::string> unique;
  for (const char *action : actions)
    if (!action || !unique.insert(action).second || commands_.contains({group, action}))
      throw failure(2, "Duplicate or invalid command registration: " + group);
  for (const auto &action : unique) commands_.emplace(std::make_pair(group, action), CommandRegistration{owner, group, action, handler, policy});
}
void BackendRegistry::Protocol(ProtocolRegistration r) {
  Mutable();
  if (r.name.empty() || !r.create || protocols_.contains(r.name)) throw failure(2, "Duplicate or invalid protocol: " + r.name);
  auto key = r.name; protocols_.emplace(std::move(key), std::move(r));
}
void BackendRegistry::Report(ReportRegistration r) {
  Mutable();
  if (!r.handle || r.protocol.empty() || r.group > 255 || r.word > 255) throw failure(2, "Invalid report registration");
  for (const auto &item : reports_)
    if (item.protocol == r.protocol && item.group == r.group && item.word == r.word)
      throw failure(2, "Duplicate report registration");
  reports_.push_back(std::move(r));
}
void BackendRegistry::Validate() {
  Mutable(); order_.clear();
  std::map<std::string, unsigned> marks;
  std::function<void(const std::string &)> visit = [&](const std::string &name) {
    if (!services_.contains(name)) throw failure(2, "Missing service dependency: " + name);
    if (marks[name] == 1) throw failure(2, "Service dependency cycle: " + name);
    if (marks[name] == 2) return;
    marks[name] = 1;
    for (const auto &dependency : services_.at(name).dependencies) visit(dependency);
    marks[name] = 2; order_.push_back(name);
  };
  for (const auto &[name, service] : services_) visit(name);
  auto owner = [&](const std::string &name) { if (!services_.contains(name)) throw failure(2, "Unknown registration owner: " + name); };
  for (const auto &[key, command] : commands_) {
    owner(command.owner);
    if (!command.policy.protocol.empty() && !protocols_.contains(command.policy.protocol)) throw failure(2, "Command requires missing protocol");
  }
  for (const auto &[key, protocol] : protocols_) owner(protocol.owner);
  for (const auto &[key, stream] : streams_) owner(stream.owner);
  for (const auto &report : reports_) { owner(report.owner); if (!protocols_.contains(report.protocol)) throw failure(2, "Report requires missing protocol"); }
  frozen_ = true;
}
void BackendRegistry::Start(runtime &context) {
  if (!frozen_ || !started_.empty()) throw failure(2, "Invalid service start state");
  started_.reserve(order_.size());
  try {
    for (const auto &name : order_) {
      const auto &service = services_.at(name);
      started_.push_back(name);
      if (service.start) service.start(context);
    }
  } catch (...) { Stop(context); throw; }
}
void BackendRegistry::Stream(StreamRegistration r) {
  Mutable();
  if (r.group.empty() || !r.stop || !r.prepare || !r.finalize || streams_.contains(r.group))
    throw failure(2, "Duplicate or invalid stream registration");
  auto key = r.group; streams_.emplace(std::move(key), std::move(r));
}
const StreamRegistration &BackendRegistry::FindStream(std::string_view group) const {
  auto it = streams_.find(std::string(group));
  if (it == streams_.end()) throw failure(2, "Unknown stream: " + std::string(group));
  return it->second;
}
void BackendRegistry::Disconnected(runtime &context) const {
  for (auto it = order_.rbegin(); it != order_.rend(); ++it)
    if (auto callback = services_.at(*it).disconnected) callback(context);
}
void BackendRegistry::Stop(runtime &context) noexcept {
  for (auto it = started_.rbegin(); it != started_.rend(); ++it)
    if (auto stop = services_.at(*it).stop) stop(context);
  started_.clear();
}
const CommandRegistration &BackendRegistry::Find(std::string_view group, std::string_view action) const {
  auto it = commands_.find({std::string(group), std::string(action)});
  if (it == commands_.end()) throw failure(2, "Unknown command: " + std::string(group) + " " + std::string(action));
  return it->second;
}
const ProtocolRegistration &BackendRegistry::FindProtocol(std::string_view name) const {
  auto it = protocols_.find(std::string(name));
  if (it == protocols_.end()) throw failure(2, "Unknown protocol: " + std::string(name));
  return it->second;
}
bool BackendRegistry::DispatchReport(std::string_view protocol, runtime &context, const packet &message) const {
  if (message.ack) return false;
  for (const auto &report : reports_)
    if (report.protocol == protocol && report.group == message.group && report.word == message.word)
      return report.handle(context, message);
  return false;
}
json BackendRegistry::Catalog() const {
  json commands = json::array(), protocols = json::array(), reports = json::array(), services = json::array(), streams = json::array();
  for (const auto &[key, c] : commands_) commands.push_back({{"group", c.group}, {"action", c.action}, {"service", c.owner}, {"lane", c.policy.lane == ExecutionLane::Core ? "core" : "probe"}, {"protocol", c.policy.protocol}});
  for (const auto &[key, p] : protocols_) protocols.push_back({{"name", p.name}, {"service", p.owner}});
  for (const auto &r : reports_) reports.push_back({{"protocol", r.protocol}, {"group", r.group}, {"word", r.word}, {"service", r.owner}});
  for (const auto &name : order_) services.push_back({{"name", name}, {"dependencies", services_.at(name).dependencies}});
  for (const auto &[name, stream] : streams_) streams.push_back({{"group", name}, {"service", stream.owner}, {"retained_limit", stream.retainedLimit}});
  return {{"services", services}, {"commands", commands}, {"protocols", protocols}, {"reports", reports}, {"streams", streams}};
}
void RegisterLinkedModules(BackendRegistry &registry) {
  std::set<std::string> names;
  auto first = reinterpret_cast<std::uintptr_t>(&frame_modules_begin) + sizeof(frame_modules_begin);
  auto last = reinterpret_cast<std::uintptr_t>(&frame_modules_end);
  if (last < first || (last - first) % sizeof(frame_modules_begin)) throw failure(2, "Invalid module section layout");
  for (auto address = first; address < last; address += sizeof(frame_modules_begin)) {
    const ModuleRegistration *module = nullptr;
    std::memcpy(&module, reinterpret_cast<const void *>(address), sizeof(module));
    if (!module) continue; // Linker alignment padding.
    if (!module->name || !module->install || !names.insert(module->name).second) throw failure(2, "Invalid linked module registration");
    module->install(registry);
  }
  if (names.empty()) throw failure(2, "No backend modules linked");
}
} // namespace frame
