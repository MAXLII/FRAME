// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include "stream_link.hpp"
#include <initializer_list>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace frame {
class runtime;
struct operation;
struct stream_job;
enum class ExecutionLane { Core, Probe };
using CommandHandler = json (*)(runtime &, operation &);
struct CommandPolicy {
  ExecutionLane lane = ExecutionLane::Core;
  bool transport = false;
  bool publish = false;
  bool exclusiveWrite = false;
  std::string protocol;
  std::string progressKind = "parameter_directory";
};
struct CommandRegistration {
  std::string owner, group, action;
  CommandHandler handler = nullptr;
  CommandPolicy policy;
};
struct ServiceRegistration {
  std::string name;
  std::vector<std::string> dependencies;
  void (*start)(runtime &) = nullptr;
  void (*stop)(runtime &) noexcept = nullptr;
  void (*disconnected)(runtime &) = nullptr;
};
struct ProtocolRegistration {
  std::string owner, name;
  std::unique_ptr<StreamDecoder> (*create)(runtime &) = nullptr;
};
struct ReportRegistration {
  std::string owner, protocol;
  unsigned group = 0, word = 0;
  bool (*handle)(runtime &, const packet &) = nullptr;
};
struct StreamRegistration {
  std::string owner, group;
  void (*stop)(runtime &, operation &) = nullptr;
  bool (*prepare)(runtime &, const stream_job &, json &data, json &record) = nullptr;
  bool (*finalize)(runtime &, json &data) = nullptr;
  std::size_t retainedLimit = 100000; // Zero retains the complete dataset.
};
class BackendRegistry final {
  std::map<std::string, ServiceRegistration> services_;
  std::map<std::pair<std::string, std::string>, CommandRegistration> commands_;
  std::map<std::string, ProtocolRegistration> protocols_;
  std::vector<ReportRegistration> reports_;
  std::map<std::string, StreamRegistration> streams_;
  std::vector<std::string> order_, started_;
  bool frozen_ = false;
  void Mutable() const;
public:
  void Service(ServiceRegistration registration);
  void Commands(std::string owner, std::string group, std::initializer_list<const char *> actions,
                CommandHandler handler, CommandPolicy policy = {});
  void Protocol(ProtocolRegistration registration);
  void Report(ReportRegistration registration);
  void Stream(StreamRegistration registration);
  void Validate();
  void Start(runtime &context);
  void Stop(runtime &context) noexcept;
  void Disconnected(runtime &context) const;
  const StreamRegistration &FindStream(std::string_view group) const;
  const CommandRegistration &Find(std::string_view group, std::string_view action) const;
  const ProtocolRegistration &FindProtocol(std::string_view name) const;
  bool DispatchReport(std::string_view protocol, runtime &context, const packet &message) const;
  json Catalog() const;
};
struct ModuleRegistration { const char *name; void (*install)(BackendRegistry &); };
void RegisterLinkedModules(BackendRegistry &registry);
} // namespace frame

// Records are constant pointers, with no global constructors or device state.
// The backend is Windows x64; /include keeps each module in optimized DLL builds.
#if defined(_MSC_VER)
#pragma section(".frmod$m", read)
#define FRAME_REGISTER_MODULE(symbol, installer) \
  namespace { const frame::ModuleRegistration symbol##_record{#symbol, installer}; } \
  extern "C" { __declspec(allocate(".frmod$m")) extern const frame::ModuleRegistration *const symbol = &symbol##_record; } \
  __pragma(comment(linker, "/include:" #symbol))
#else
#error "Implement module section discovery for this toolchain"
#endif
