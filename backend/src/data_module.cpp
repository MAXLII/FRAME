// SPDX-License-Identifier: MIT
#include "service_support.hpp"
namespace frame {
void runtime::clear_wave(std::uint64_t id, const std::string &reason) {
  auto &data = datasets.at(id);
  if (data.value("group", "") != "wave") throw failure(2, "Waveform dataset required");
  data["revision_base"] = data.value("revision_base", 0ull) + data["records"].size() + 1;
  data["records"] = json::array();
  data["generation"] = data.value("generation", 0ull) + 1;
  data["clear_reason"] = reason;
  data["dropped"] = 0;
  data["segment"] = data.value("segment", 0u) + 1;
}

static json Handle(runtime &r, operation &op) {
  auto &q = op.command;
  auto group = q.value("group", std::string()), action = q.value("action", std::string());
    if (action == "save") {
      if (!q.contains("records") || !q["records"].is_array() || q["records"].size() > 100000)
        throw failure(2, "Expected at most 100000 records");
      // Reuse the backend's atomic file exporter without retaining a dataset.
      r.datasets[op.id] = {{"schema_version", 1}, {"group", "perf"}, {"state", "complete"}, {"records", q["records"]}};
      try { r.export_dataset(op.id, q.at("output")); } catch (...) { r.datasets.erase(op.id); throw; }
      r.datasets.erase(op.id);
      return {{"path", q.at("output")}};
    }
    auto id = q.value("dataset", std::uint64_t(0));
    if (!r.datasets.contains(id))
      throw failure(2, "Unknown dataset");
    if (action == "release") {
      if (r.streams.contains(id))
        throw failure(9, "Dataset is still acquiring");
      r.datasets.erase(id);
      return {{"released", id}};
    }
    if (action == "export") {
      r.export_dataset(id, q.at("output"));
      return {{"path", q.at("output")}};
    }
    auto &d = r.datasets[id];
    auto &rows = d["records"];
    if (action == "clear") {
      r.clear_wave(id, "manual");
      if (r.streams.contains(id)) r.wave_integrity = {};
      return {{"dataset_id", id}, {"generation", d["generation"]}, {"cleared", true}};
    }
    if (action == "view") {
      if (d.value("group", "") != "wave")
        throw failure(2, "Waveform dataset required");
      double seconds = q.value("seconds", 30.0);
      if (!std::isfinite(seconds) || seconds < 0 || seconds > 86400)
        throw failure(2, "View seconds must be in [0,86400]");
      double last = rows.empty() ? 0.0 : rows.back().value("time", 0.0);
      double first = rows.empty() ? 0.0 : rows.front().value("time", 0.0);
      double right = q.value("right", last);
      double left = q.value("left", seconds == 0 ? first : std::max(first, right - seconds));
      if (!std::isfinite(left) || !std::isfinite(right) || left > right)
        throw failure(2, "Invalid waveform viewport");
      std::map<std::string, std::vector<const json *>> series;
      std::map<std::string, const json *> latest_records;
      for (const auto &row : rows) {
        latest_records[row.value("name", "?")] = &row;
        double time = row.value("time", 0.0);
        if (time >= left && time <= right)
          series[row.value("name", "?")].push_back(&row);
      }
      json visible = json::array();
      // First/min/max/last per bucket preserve peaks; originals remain exportable.
      for (const auto &[name, points] : series) {
        auto stride = std::max<std::size_t>(1, (points.size() + 999) / 1000);
        for (std::size_t i = 0; i < points.size(); i += stride) {
          auto end = std::min(points.size(), i + stride);
          auto lo = i, hi = i;
          for (auto j = i + 1; j < end; ++j) {
            if ((*points[j])["value"] < (*points[lo])["value"]) lo = j;
            if ((*points[j])["value"] > (*points[hi])["value"]) hi = j;
          }
          std::set<std::size_t> selected{i, lo, hi, end - 1};
          for (auto j : selected) visible.push_back(*points[j]);
        }
      }
      std::stable_sort(visible.begin(), visible.end(), [](const json &a, const json &b) {
        return a.value("time", 0.0) < b.value("time", 0.0);
      });
      json latest = json::array();
      for (const auto &[name, record] : latest_records) latest.push_back(*record);
      return {{"records", visible}, {"latest_records", latest}, {"total", rows.size()},
              {"dataset_id", id}, {"generation", d.value("generation", 0ull)}, {"left", left}, {"right", right}};
    }
    auto revision = d.value("revision_base", 0ull) + d.value("dropped", 0ull) + rows.size();
    if (q.contains("revision") && q["revision"] != revision)
      throw failure(
          6,
          "Dataset revision changed; restart paging from the current snapshot");
    auto offset = q.value("offset", std::size_t(0)),
         limit = q.value("limit", std::size_t(1000));
    limit = std::min<std::size_t>(limit, 10000);
    json out = json::object();
    for (auto item = d.begin(); item != d.end(); ++item)
      if (item.key() != "records")
        out[item.key()] = item.value();
    out["records"] = json::array();
    for (auto i = std::min(offset, rows.size());
         i < std::min(rows.size(), offset + limit); ++i)
      out["records"].push_back(rows[i]);
    out["total"] = rows.size();
    out["dataset_id"] = id;
    out["revision"] = revision;
    return out;
  throw failure(2, "Unsupported data command" );
}
static void Install(BackendRegistry &registry) {
  registry.Service({"data", {}}); registry.Commands("data", "data", {"save","release","export","clear","view","read"}, Handle);
}
FRAME_REGISTER_MODULE(frame_module_data, Install)
} // namespace frame
