// SPDX-License-Identifier: MIT
#include "service_support.hpp"
namespace frame {
static json Handle(runtime &r, operation &op) {
  auto &q = op.command;
  auto group = q.value("group", std::string()), action = q.value("action", std::string());
    bool scope = group == "scope";
    auto b = object_payload(q);
    unsigned id = b[0];
    auto match = [id](const packet &p) {
      return !p.payload.empty() && p.payload[0] == id;
    };
    if (action == "list") {
      unsigned word = scope ? 0x18 : 0x2f;
      r.send(word, {0});
      json rows = json::array();
      for (unsigned i = 0; i < 256; ++i) {
        auto p = r.wait_packet(op, word);
        auto item = decode(static_cast<std::uint8_t>(word), p.payload);
        rows.push_back(item);
        if (item["last"] != 0)
          return rows;
      }
      throw failure(6, "Object enumeration exceeded quota");
    }
    if (action == "info")
      return r.query(op, scope ? 0x19 : 0x30, b, match);
    if (action == "channels" && scope) {
      auto info = r.query(op, 0x19, b, match);
      json rows = json::array();
      for (unsigned i = 0; i < info["channels"].get<unsigned>(); ++i) {
        b[1] = static_cast<std::uint8_t>(i);
        rows.push_back(r.query(op, 0x1a, b, match));
      }
      return rows;
    }
    if (action == "configure" && !scope) {
      bytes cfg{static_cast<std::uint8_t>(id), 3, 0, 0};
      auto start = q.at("start_hz").get<float>(),
           stop = q.at("stop_hz").get<float>(),
           amplitude = q.at("amplitude").get<float>();
      if (!(start > 0 && stop >= start && amplitude > 0 &&
            std::isfinite(stop) && std::isfinite(amplitude)))
        throw failure(2, "Invalid sweep configuration");
      putf(cfg, start);
      putf(cfg, stop);
      putf(cfg, amplitude);
      return r.query(op, 0x31, cfg, match);
    }
    std::map<std::string, unsigned> controls =
        scope ? std::map<std::string, unsigned>{{"start", 0x1b},
                                                {"trigger", 0x1c},
                                                {"stop", 0x1d},
                                                {"reset", 0x1e}}
              : std::map<std::string, unsigned>{
                    {"start", 0x32}, {"stop", 0x33}, {"reset", 0x34}};
    if (controls.contains(action)) {
      if(!scope&&action=="start"&&r.datasets.size()>=32)throw failure(9,"Dataset quota exceeded");
      if (action == "start") {
        auto other =
            r.query(op, scope ? 0x30 : 0x19, object_payload(json{{"id", 0}}));
        if (other.value("busy", 0) != 0 || other.value("state", 0) == 1)
          throw failure(9, "Other active capture must be stopped first");
      }
      auto ack = r.query(op, controls[action], b, match);
      if(!scope){
        if(action=="start"){
          r.datasets[op.id]={{"schema_version",1},{"group","sfra"},{"state","running"},{"epoch",r.epoch()},{"metadata",ack},{"records",json::array()},{"partial",false}};
          for(auto it=r.incoming.begin();it!=r.incoming.end();){if(r.registry.DispatchReport(r.protocol_name, r, *it))it=r.incoming.erase(it);else ++it;}
          return {{"dataset_id",op.id},{"metadata",ack}};
        }
        for(auto &[datasetId,data]:r.datasets)if(data.value("group",std::string())=="sfra"&&data.value("state",std::string())=="running"&&data["metadata"]["id"]==id){data["state"]="stopped";data["partial"]=true;}
      }
      if (scope && (action == "start" || action == "trigger")) {
        // Control ACK can precede the sampling task's state transition.
        const auto deadline = clock::now() + std::chrono::milliseconds(500);
        const unsigned expected = action == "start" ? 1u : 2u;
        do {
          r.guard(op); r.pump(10);
          auto info = r.query(op, 0x19, b, match);
          if (info.value("state", 0u) == expected || info.value("ready", 0u) != 0)
            return info;
          ack = std::move(info);
        } while (clock::now() < deadline);
        ack["transition_pending"] = true;
      }
      return ack;
    }
    if (action == "pull" || action == "points") {
      auto info = r.query(op, scope ? 0x19 : 0x30, b, match);
      if (info["ready"] == 0)
        throw failure(7, "Device data is not ready");
      if (!scope &&
          (info["done"] == 0 || info["table_length"] != info["count"]))
        throw failure(7, "SFRA sweep is not complete; query info until done");
      auto count = info["count"].get<unsigned>(),
           tag = info["tag"].get<unsigned>();
      if (count > 1000000 || r.datasets.size() >= 32)
        throw failure(9, "Dataset quota exceeded");
      auto &d = r.datasets[op.id];
      d = {{"schema_version", 1},
           {"group", group},
           {"metadata", info},
           {"state", "partial"},
           {"records", json::array()}};
      for (unsigned index = 0; index < count; ++index) {
        r.guard(op);
        bytes request = scope ? bytes{static_cast<std::uint8_t>(id), 0, 0, 0}
                              : bytes{static_cast<std::uint8_t>(id), 0};
        put(request, index, scope ? 4 : 2);
        put(request, tag, 4);
        auto item = r.query(op, scope ? 0x1f : 0x35, request,
                          [id, index, tag, scope](const packet &p) {
                            try {
                              auto r = decode(scope ? 0x1f : 0x35, p.payload);
                              return r["id"] == id && r["index"] == index;
                            } catch (...) {
                              return false;
                            }
                          });
        if (item["tag"] != tag)
          throw failure(6, "Capture changed during pull");
        if (scope)
          item["time"] = double(index) * info["period_us"].get<double>() / 1e6;
        d["records"].push_back(item);
      }
      d["state"] = "complete";
      if (q.contains("output"))
        r.export_dataset(op.id, q["output"]);
      return {{"dataset_id", op.id}, {"count", count}, {"metadata", info}};
    }
    throw failure(2, "Unknown capture action");
  throw failure(2, "Unsupported capture command" );
}
static bool ReceiveSfra(runtime &r, const packet &report) {
  if (report.ack || (report.word != 0x36 && report.word != 0x37)) return false;
  auto row = decode(report.word, report.payload);
  for (auto &[id, data] : r.datasets) {
    if (data.value("group", std::string()) != "sfra" || data.value("state", std::string()) != "running" ||
        data.value("epoch", 0ull) != r.epoch() || data["metadata"]["id"] != row["id"] || data["metadata"]["tag"] != row["tag"]) continue;
    auto &records=data["records"];
    if (report.word==0x36) {
      if(row.value("status",0)!=0 || row.value("index",0u)>=1000000) {data["partial"]=true;return true;}
      auto duplicate=std::find_if(records.begin(),records.end(),[&](const json &item){return item["index"]==row["index"];});
      if(duplicate==records.end())records.push_back(row);
      else {data["duplicates"]=data.value("duplicates",0u)+1;if(*duplicate!=row)data["partial"]=true;}
      std::sort(records.begin(),records.end(),[](const json &a,const json &b){return a["index"]<b["index"];});
    } else {
      auto expected=row.value("count",0u);bool complete=records.size()==expected;
      for(unsigned index=0;index<records.size();++index)complete=complete&&records[index]["index"]==index;
      data["metadata"]=row;data["partial"]=data.value("partial",false)||!complete;
      data["state"]=data["partial"].get<bool>()?"partial":"complete";
    }
    return true;
  }
  return false;
}
static void Disconnected(runtime &r) {
  for (auto &[id, data] : r.datasets)
    if (data.value("group", std::string()) == "sfra" && data.value("state", std::string()) == "running") {
      data["state"] = "partial"; data["partial"] = true;
    }
}
static void Install(BackendRegistry &registry) {
  registry.Report({"capture", "frame-v1", 1, 0x36, ReceiveSfra});
  registry.Report({"capture", "frame-v1", 1, 0x37, ReceiveSfra});
  registry.Service({"capture", {"frame-protocol","data"}, nullptr, nullptr, Disconnected});
  registry.Commands("capture", "scope", {"list","info","channels","start","trigger","stop","reset","pull"}, Handle, CommandPolicy{ExecutionLane::Core, true, false, false, "frame-v1"});
  registry.Commands("capture", "sfra", {"list","info","configure","start","stop","reset","points"}, Handle, CommandPolicy{ExecutionLane::Core, true, false, false, "frame-v1"});
}
FRAME_REGISTER_MODULE(frame_module_capture, Install)
} // namespace frame
