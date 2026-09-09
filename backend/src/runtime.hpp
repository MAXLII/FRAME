// SPDX-License-Identifier: MIT
#pragma once
#include "acquisition.hpp"
#include "transport.hpp"
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
  std::uint64_t event_sequence_ = 0;
  std::atomic_bool jlink_write_active_ = false;
  std::atomic_uint stream_count_ = 0;
  std::uint64_t next_ = 1, epoch_ = 0;
  std::atomic_bool stopping_ = false;
  json snapshot_;
  void run();

public:
  transport serial;
  parser decoder;
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
  bool receive_sfra_report(const packet &report);
  void guard(const operation &op);
  void publish();
  void send(unsigned word, const bytes &payload);
  packet wait_packet(operation &op, unsigned word, bool ack = true,
                     const std::function<bool(const packet &)> &match = {});
  json query(operation &op, unsigned word, const bytes &payload,
             const std::function<bool(const packet &)> &match = {});
  json execute(operation &op);
  json jlink(operation &op);
  void append_stream(const std::string &group, json record);
  void clear_wave(std::uint64_t id, const std::string &reason);
  void export_dataset(std::uint64_t id, const std::string &path);
  void fail_streams(int code, const std::string &error);
};
} // namespace frame
