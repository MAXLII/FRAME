// SPDX-License-Identifier: MIT
#include "backend_registry.hpp"
#include <iostream>
#include <stdexcept>
// This standalone registry test links no production runtime. The registry only
// forwards an opaque context; the real runtime is exercised through C ABI tests.
namespace frame { class runtime { public: std::vector<std::string> events; }; }
using namespace frame;
static void Require(bool value, const char *message) { if (!value) throw std::runtime_error(message); }
template<class F> static void Reject(F action) {
  try { action(); } catch (const failure &e) { Require(e.code == 2, "registry error classification"); return; }
  throw std::runtime_error("registration unexpectedly accepted");
}
static json Handle(runtime &, operation &) { return 17; }
class TextDecoder final : public StreamDecoder {
public:
  std::string_view Name() const noexcept override { return "test-text"; }
  void Feed(std::span<const std::uint8_t>) override {}
  void Reset() noexcept override {}
};
static std::unique_ptr<StreamDecoder> Create(runtime &) { return std::make_unique<TextDecoder>(); }
static bool Report(runtime &r, const packet &) { r.events.push_back("report"); return true; }
static void StartBase(runtime &r) { r.events.push_back("base+"); }
static void StopBase(runtime &r) noexcept { r.events.push_back("base-"); }
static void StartChild(runtime &r) { r.events.push_back("child+"); }
static void StopChild(runtime &r) noexcept { r.events.push_back("child-"); }
static void FailStart(runtime &r) { r.events.push_back("child+"); throw std::runtime_error("fixture failure"); }
static void Install(BackendRegistry &r) {
  r.Service({"registry-test", {}});
  r.Commands("registry-test", "test", {"echo"}, Handle);
  r.Protocol({"registry-test", "test-text", Create});
  r.Report({"registry-test", "test-text", 2, 3, Report});
}
FRAME_REGISTER_MODULE(frame_registry_test_module, Install)
int main() {
  try {
    runtime context;
    BackendRegistry registry;
    RegisterLinkedModules(registry); // Release /OPT:REF must retain this record.
    registry.Validate();
    Require(registry.Find("test", "echo").handler == Handle, "linked command registration");
    Require(registry.FindProtocol("test-text").create(context)->Name() == "test-text", "protocol factory");
    Reject([&] { registry.Commands("registry-test", "test", {"later"}, Handle); });
    Reject([&] { registry.Find("test", "missing"); });
    Reject([&] { registry.FindProtocol("missing"); });
    packet report; report.group = 2; report.word = 3; report.ack = false;
    Require(registry.DispatchReport("test-text", context, report), "registered report dispatch");
    report.ack = true;
    Require(!registry.DispatchReport("test-text", context, report), "ACK must reach transaction matcher");
    report.ack = false;
    Require(!registry.DispatchReport("other", context, report), "protocol isolation");
    for (int mode = 0; mode < 5; ++mode) {
      BackendRegistry bad;
      if (mode == 0) { bad.Service({"a", {"missing"}}); Reject([&] { bad.Validate(); }); }
      if (mode == 1) { bad.Service({"a", {"b"}}); bad.Service({"b", {"a"}}); Reject([&] { bad.Validate(); }); }
      if (mode == 2) { bad.Commands("absent", "test", {"a"}, Handle); Reject([&] { bad.Validate(); }); }
      if (mode == 3) { bad.Service({"a", {}}); Reject([&] { bad.Service({"a", {}}); }); }
      if (mode == 4) { bad.Service({"a", {}}); bad.Commands("a", "test", {"a"}, Handle, {ExecutionLane::Core,true,false,false,"absent"}); Reject([&] { bad.Validate(); }); }
    }
    BackendRegistry duplicates;
    Install(duplicates);
    Reject([&] { duplicates.Commands("registry-test", "test", {"new", "echo"}, Handle); });
    Reject([&] { duplicates.Find("test", "new"); }); // No partial registration on conflict.
    Reject([&] { duplicates.Protocol({"registry-test", "test-text", Create}); });
    Reject([&] { duplicates.Report({"registry-test", "test-text", 2, 3, Report}); });
    for (bool fail : {false, true}) {
      BackendRegistry lifecycle;
      lifecycle.Service({"child", {"base"}, fail ? FailStart : StartChild, StopChild});
      lifecycle.Service({"base", {}, StartBase, StopBase});
      lifecycle.Validate(); context.events.clear();
      bool caught = false;
      try { lifecycle.Start(context); } catch (const std::runtime_error &) { caught = true; }
      Require(caught == fail, "start failure propagation");
      if (!fail) Require(context.events == std::vector<std::string>{"base+", "child+"}, "dependency start order");
      lifecycle.Stop(context); lifecycle.Stop(context);
      Require(context.events == std::vector<std::string>{"base+", "child+", "child-", "base-"}, "reverse cleanup / failure rollback / idempotent stop");
    }
    std::cout << "registry: linked registration, validation, routing and lifecycle passed\n";
  } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
