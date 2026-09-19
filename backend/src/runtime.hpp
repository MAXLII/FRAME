// SPDX-License-Identifier: MIT
#pragma once
#include "acquisition.hpp"
#include "transport.hpp"
#include "stream_link.hpp"
#include "backend_registry.hpp"
#include "communication_log.hpp"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <thread>
namespace frame {
using clock = std::chrono::steady_clock;
struct operation final {
  std::uint64_t id = 0;
  json command, result;
  std::atomic_bool cancel = false;
  const operation *parent = nullptr;
  bool done = false;
  bool deferred = false, exclusive_write = false;
  CommandHandler handler = nullptr;
  clock::time_point deadline;
};
struct stream_job final {
  std::shared_ptr<operation> op;
  std::string group;
  clock::time_point end;
  bool stop_confirmed = false;
};
class symbols;
class commander;
class runtime final {
  std::mutex mutex_;
  std::condition_variable cv_;
  std::map<std::uint64_t, std::shared_ptr<operation>> operations_;
  std::deque<std::shared_ptr<operation>> pending_;
  std::jthread worker_;
  std::jthread jlink_worker_;
  std::deque<std::shared_ptr<operation>> jlink_pending_;
  std::deque<json> events_;
  void flush_monitor_locked();
  std::uint64_t event_sequence_ = 0;
  std::atomic_bool jlink_write_active_ = false;
  std::atomic_uint stream_count_ = 0;
  std::uint64_t next_ = 1, epoch_ = 0;
  std::atomic_bool stopping_ = false;
  json snapshot_;
  void run();

public:
  communication_log comm_log;
  clock::time_point diagnostic_due{}, last_rx{};
  std::uint64_t received_packets = 0, ignored_packets = 0, report_packets = 0;
  std::string last_rx_preview;
  void log_communication_state();
  BackendRegistry registry;
  std::string protocol_name = "frame-v1";
  void receive_packet(packet p);
  std::uint64_t epoch() const noexcept { return epoch_; }
  bool probe_write_active() const noexcept { return jlink_write_active_; }
  unsigned active_streams() const noexcept { return stream_count_; }
  void begin_stream(operation &op, const std::string &group, double duration);
  json connect_device(operation &op);
  json disconnect_device(operation &op);
  json set_wire(operation &op);
  transport serial;
  parser decoder;
  StreamLink receive_link;
  std::deque<packet> incoming;
  std::map<std::uint64_t, stream_job> streams;
  std::map<std::string, json> parameters;
  std::map<unsigned, json> perf_dictionary;
  unsigned perf_version = 0;
  tick_clock wave_clock, trace_clock;
  batch_integrity wave_integrity;
  std::map<std::uint64_t, json> datasets;
  std::unique_ptr<symbols> symbol_index;
  std::unique_ptr<commander> probe_session;
  json jlink_settings = json::object();
  unsigned dst = 2, dynamic_dst = 0, timeout_ms = 1500;
  std::uint64_t dropped = 0, rx_bytes = 0, tx_bytes = 0;
  runtime();
  ~runtime();
  std::uint64_t submit(json cmd);
  int result(std::uint64_t id, std::string &result);
  int cancel(std::uint64_t id);
  int release(std::uint64_t id);
  std::string snapshot();
  std::string events(std::uint64_t after, unsigned limit);
  void progress(const operation &op, json data);
  void finish(const std::shared_ptr<operation> &op, int code, json data,
              std::string error = {});
  void pump(unsigned wait = 5);
  void guard(const operation &op);
  void publish();
  void send(unsigned word, const bytes &payload);
  packet wait_packet(operation &op, unsigned word, bool ack = true,
                     const std::function<bool(const packet &)> &match = {});
  json query(operation &op, unsigned word, const bytes &payload,
             const std::function<bool(const packet &)> &match = {});
  json execute(operation &op);
  void append_stream(const std::string &group, json record);
  void clear_wave(std::uint64_t id, const std::string &reason);
  void export_dataset(std::uint64_t id, const std::string &path);
  void fail_streams(int code, const std::string &error);
  /* COMM v1 (0xE9) wire protocol state.
   * wire_mode selects the sending format only: "e8" (default) forces legacy
   * 0xE8, "e9" forces 0xE9 (RAW until negotiation completes), "auto" probes
   * the device and falls back to 0xE8.
   * comm_v1_negotiated is set by a valid CODEC_SELECT response and only gates
   * compression; it never changes the selected wire format by itself. */
  void probe_comm_v1();
  bool comm_v1_sending() const noexcept {
    return wire_mode == "e9" || (wire_mode == "auto" && comm_v1_negotiated);
  }
  /* Serial monitor: stream every user-sent, protocol-sent and received byte
   * block to the UI through throttled "serial_monitor" events. */
  void monitor(const std::string &kind, const bytes &b, const char *source = "serial");
  void flush_monitor();
  bool monitor_protocol_rx = false; // Receive owner, including replies arriving between commands.
  std::string wire_mode = "e8";
  bool comm_v1_negotiated = false;
  std::uint8_t comm_v1_next_seq = 0;
  bool comm_v1_probe_pending = false;
  std::uint8_t comm_v1_probe_seq = 0;
  std::uint8_t request_sop = 0xE8, request_seq = 0;
  json monitor_pending_ = json::array();
  clock::time_point monitor_flush_due_ = clock::time_point::min();
};
} // namespace frame
