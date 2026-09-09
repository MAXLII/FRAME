#include "frame/api.hpp"
#include "protocol.hpp"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <thread>
using json = nlohmann::json;
using namespace std::chrono_literals;
static void require(bool ok, const char *text) {
  if (!ok)
    throw std::runtime_error(text);
}
struct backend {
  void *h = frame_create();
  backend() { require(h != nullptr, "create"); }
  ~backend() { frame_destroy(h); }
};
static std::uint64_t submit(backend &b, json command) {
  auto s = command.dump();
  std::uint64_t id = 0;
  require(frame_submit(b.h, s.data(), static_cast<std::uint32_t>(s.size()),
                       &id) == 0,
          "submit");
  return id;
}
static json wait(backend &b, std::uint64_t id) {
  auto end = std::chrono::steady_clock::now() + 5s;
  std::uint32_t n = 0;
  while (frame_result(b.h, id, nullptr, 0, &n) == 1) {
    require(std::chrono::steady_clock::now() < end, "wait deadline");
    std::this_thread::sleep_for(5ms);
  }
  std::string s(n, '\0');
  require(frame_result(b.h, id, s.data(), n, &n) == 0, "copy result");
  auto result = json::parse(s);
  require(frame_release(b.h, id) == 0, "release");
  return result;
}
static json call(backend &b, json q) { return wait(b, submit(b, q)); }
struct replay_file {
  std::filesystem::path path =
      std::filesystem::temp_directory_path() /
      ("frame-replay-test-" +
       std::to_string(
           std::chrono::steady_clock::now().time_since_epoch().count()) +
       ".json");
  explicit replay_file(const json &data) { std::ofstream(path) << data.dump(); }
  ~replay_file() {
    std::error_code error;
    std::filesystem::remove(path, error);
  }
};
static std::string response(unsigned word, frame::bytes payload,
                            bool ack = true) {
  frame::packet packet;
  packet.word = static_cast<std::uint8_t>(word);
  packet.payload = std::move(payload);
  packet.ack = ack;
  return frame::hex(frame::encode(packet));
}
int main(int argc, char **argv) {
  try {
    require(argc == 3, "fixture directory and fake Commander required");
    auto fixture = std::filesystem::path(argv[1]);
    {
      auto ack=[](unsigned count,unsigned seq){frame::bytes b{1,0};frame::put(b,count,2);frame::put(b,seq,4);frame::put(b,7,4);b.push_back(0);return b;};
      auto entry=[](unsigned index,unsigned id,unsigned type,const std::string &name){frame::bytes b;frame::put(b,1,4);frame::put(b,index,2);frame::put(b,2,2);frame::put(b,id,2);b.push_back(static_cast<std::uint8_t>(type));b.push_back(static_cast<std::uint8_t>(name.size()));b.insert(b.end(),name.begin(),name.end());return b;};
      auto end=[](unsigned count,unsigned seq,bool dictionary){frame::bytes b;frame::put(b,seq,4);frame::put(b,count,2);b.insert(b.end(),{0,0});if(dictionary)frame::put(b,7,4);return b;};
      auto samples=[](unsigned seq,unsigned id,unsigned type){frame::bytes b;frame::put(b,seq,4);frame::put(b,0,2);frame::put(b,1,2);frame::put(b,id,2);frame::put(b,10,4);frame::put(b,20,4);if(type==1)frame::put(b,1000,4);frame::putf(b,1.5f);frame::putf(b,2.5f);return b;};
      frame::packet query;query.src=1;query.dst=2;query.word=0x26;query.ack=false;query.payload=frame::bytes(8,0);
      replay_file replay(json::array({
        json{{"tx",frame::hex(frame::encode(query))},{"rx",{response(0x26,ack(2,1))+response(0x27,entry(0,1,1,"task"),false)+response(0x27,entry(1,2,2,"irq"),false)+response(0x28,end(2,1,true),false)}}},
        json{{"rx",{response(0x29,ack(1,2))+response(0x2a,samples(2,1,1),false)+response(0x2b,end(1,2,false),false)}}},
        json{{"rx",{response(0x29,ack(1,3))+response(0x2a,samples(3,2,2),false)+response(0x2b,end(1,3,false),false)}}}}));
      backend b;auto task=call(b,{{"group","perf"},{"action","samples"},{"filter",1},{"replay",replay.path.string()}});require(task["ok"]&&task["data"][0]["name"]=="task","First filtered Perf pull synchronizes complete dictionary");
      auto irq=call(b,{{"group","perf"},{"action","samples"},{"filter",2}});require(irq["ok"]&&irq["data"][0]["name"]=="irq","Switching Perf type retains dictionary coverage");
    }
    {
      backend b;
      auto settings=json{{"group","jlink"},{"action","connect"},{"jlink_exe",argv[2]},{"interface","JTAG"},{"speed",4000}};
      auto first=call(b,settings);require(first["ok"]&&first["data"]["interface"]=="JTAG"&&first["data"]["speed"]==4000,"J-Link selected interface/speed");
      require(call(b,settings)["data"]["session_reused"]==true,"J-Link session reused with identical settings");
      settings["speed"]=1000;require(call(b,settings)["data"]["session_reused"]==false,"J-Link changing speed must reopen Commander");
      settings["interface"]="SWD -command reset";require(call(b,settings)["code"]==2,"J-Link interface is validated before launching commands");
    }
    {
      auto path=std::filesystem::temp_directory_path()/"frame-section-parity.map";
      std::ofstream(path)<<"  0x20000000 z_task\n  0x20000004 irq_node\n";
      backend b;
      auto rows=json::array({json{{"index",0},{"address",0x20000004}},json{{"index",1},{"address",0x20000000}}});
      auto mapped=call(b,{{"group","section"},{"action","resolve"},{"map",path.string()},{"records",rows}});
      require(mapped["ok"]&&mapped["data"][0]["name"]=="irq_node"&&mapped["data"][1]["name"]=="z_task","Offline MAP lookup preserves list traversal order");
      auto csv=path;csv.replace_extension("csv");
      auto saved=call(b,{{"group","data"},{"action","save"},{"records",json::array({json{{"name","comma,quote\""},{"value",1.25}}})},{"output",csv.string()}});
      require(saved["ok"],"Perf CSV uses backend exporter");std::ifstream file(csv);std::string text((std::istreambuf_iterator<char>(file)),{});require(text.find("\"comma,quote\"\"\"")!=std::string::npos,"CSV escapes commas and quotes");file.close();
      require(call(b,{{"group","status"}})["data"]["datasets"].empty(),"Perf export does not leak datasets");std::filesystem::remove(csv);std::filesystem::remove(path);
    }
    {
      auto tx=[](unsigned word){frame::packet p;p.src=1;p.dst=2;p.ack=false;p.word=static_cast<std::uint8_t>(word);p.payload={0,0,0,0};return frame::hex(frame::encode(p));};
      frame::bytes scope(36,0),started(20,0),done(20,0);started[2]=1;started[3]=1;started[10]=2;started[16]=9;done=started;done[2]=5;done[3]=0;done[4]=1;done[5]=1;
      auto point=[](unsigned index,unsigned tag){frame::bytes b{0,0,0,0};frame::put(b,index,2);frame::put(b,0,2);frame::put(b,tag,4);frame::putf(b,10.f+index*10);frame::putf(b,1.f);frame::putf(b,-30.f);return response(0x36,b,false);};
      replay_file replay({{"repeat_rx",point(0,9)+point(0,8)},{"period_ms",10},{"steps",json::array({json{{"tx",tx(0x19)},{"rx",{response(0x19,scope)}}},json{{"tx",tx(0x32)},{"rx",{response(0x32,started)+point(1,9)}}},json{{"tx",tx(0x30)},{"rx",{response(0x30,frame::bytes(48,0))+response(0x37,done,false)}}}})}});
      backend b;require(call(b,{{"group","connect"},{"replay",replay.path.string()}})["ok"],"SFRA report replay connect");
      auto start=call(b,{{"group","sfra"},{"action","start"},{"id",0}});require(start["ok"],"SFRA start");auto id=start["data"]["dataset_id"];
      std::this_thread::sleep_for(80ms);auto data=call(b,{{"group","data"},{"action","read"},{"dataset",id}});
      require(data["data"]["records"].size()==2&&data["data"]["state"]=="running","SFRA points visible before done; duplicate and old tag isolated");
      require(data["data"]["records"][0]["index"]==0,"SFRA reports sorted by sweep index");
      call(b,{{"group","sfra"},{"action","info"},{"id",0}});data=call(b,{{"group","data"},{"action","read"},{"dataset",id}});
      require(data["data"]["state"]=="complete","SFRA done report completes live dataset");
    }
    {
      auto step=[](unsigned word,unsigned id,frame::bytes reply){frame::packet request;request.src=1;request.dst=2;request.ack=false;request.word=static_cast<std::uint8_t>(word);request.payload={static_cast<std::uint8_t>(id),0,0,0};return json{{"tx",frame::hex(frame::encode(request))},{"rx",{response(word,reply)}}};};
      frame::bytes sfra(48,0),idle(36,0),running(36,0),triggered(36,0),startAck(8,0),triggerAck(8,0);
      idle[0]=running[0]=triggered[0]=startAck[0]=triggerAck[0]=3;running[2]=1;triggered[2]=2;triggerAck[2]=1;
      replay_file replay({{"repeat_rx",""},{"steps",json::array({step(0x30,0,sfra),step(0x1b,3,startAck),step(0x19,3,idle),step(0x19,3,running),step(0x1c,3,triggerAck),step(0x19,3,triggered)})}});
      backend b;require(call(b,{{"group","connect"},{"replay",replay.path.string()}})["ok"],"scope transition replay");
      auto started=call(b,{{"group","scope"},{"action","start"},{"id",3}});
      require(started["ok"]&&started["data"]["state"]==1,"start must resolve stale idle ACK through state query");
      auto triggeredResult=call(b,{{"group","scope"},{"action","trigger"},{"id",3}});
      require(triggeredResult["ok"]&&triggeredResult["data"]["state"]==2,"trigger must resolve stale running ACK through state query");
    }
    {
      frame::packet command;command.src=1;command.dst=2;command.ack=false;command.word=6;frame::put(command.payload,20,4);
      replay_file replay({{"repeat_rx",""},{"steps",json::array({{{"tx",frame::hex(frame::encode(command))},{"rx",{response(6,command.payload)}}}})}});
      backend b;
      auto connected=call(b,{{"group","connect"},{"replay",replay.path.string()}});
      if(!connected["ok"].get<bool>())throw std::runtime_error(connected.dump());
      require(call(b,{{"group","wave"},{"action","period"},{"period",20}})["ok"],"period update must receive ACK");
      auto invalid=json{{"group","wave"},{"action","period"},{"period",0}}.dump();std::uint64_t unused=0;
      require(frame_submit(b.h,invalid.data(),static_cast<std::uint32_t>(invalid.size()),&unused)!=0,"invalid period rejected");
    }
    {
      backend b;
      auto connection =
          call(b, {{"group", "connect"},
                   {"replay", (fixture / "parameter-session.json").string()}});
      require(connection["ok"], "connect replay");
      auto list = call(b, {{"group", "param"}, {"action", "list"}});
      require(list["data"].size() == 1, "directory count");
      auto read = call(
          b,
          {{"group", "param"}, {"action", "read"}, {"name", "TEST_COUNTER"}});
      require(read["data"]["value"] == 42, "parameter read");
      auto unknown = call(b, {{"group", "bad"}});
      require(unknown["code"] == 2, "invalid group");
    }
    {
      backend b;
      auto acquire =
          submit(b, {{"group", "wave"},
                     {"action", "capture"},
                     {"replay", (fixture / "wave-periodic.json").string()},
                     {"duration", 0}});
      std::this_thread::sleep_for(100ms);
      auto status = call(b, {{"group", "status"}});
      require(status["data"]["jobs"].size() == 1,
              "stream must not block commands");
      require(frame_cancel(b.h, acquire) == 0, "cancel accepted");
      auto done = wait(b, acquire);
      require(done["code"] == 130 && done["data"]["stop_confirmed"] == true,
              "cancel with stop ACK");
      auto data = call(b, {{"group", "data"},
                           {"action", "read"},
                           {"dataset", acquire},
                           {"limit", 10}});
      require(data["data"]["records"].size() == 10, "dataset page");
      require(data["data"]["records"][0]["time_source"] == "device_100us" &&
              data["data"]["records"][0]["time"].get<double>() < 100,
              "PLECS keeps uploaded simulation seconds");
      require(data["data"]["state"] == "cancelled", "cancelled dataset marked");
      auto view = call(b, {{"group", "data"}, {"action", "view"},
                           {"dataset", acquire}, {"seconds", 0}});
      require(view["ok"] && view["data"]["total"] >= 10,
              "continuous capture retains history after cancellation");
      require(call(b, {{"group", "data"},
                       {"action", "release"},
                       {"dataset", acquire}})["ok"],
              "dataset release");
    }
    {
      backend b;
      auto id =
          submit(b, {{"group", "wave"},
                     {"action", "capture"},
                     {"replay", (fixture / "wave-periodic.json").string()},
                     {"duration", .15}});
      auto result = wait(b, id);
      require(result["ok"] && result["data"]["count"].get<int>() >= 160,
              "periodic replay throughput");
      std::uint32_t n = 0;
      require(frame_events(b.h, 0, 32, nullptr, 0, &n) == 2, "event sizing");
      std::string text(n, '\0');
      require(frame_events(b.h, 0, 32, text.data(), n, &n) == 0,
              "event batch read");
      require(json::parse(text)["events"].size() > 0, "completion event");
    }
    {
      json spec;
      std::ifstream(fixture / "wave-periodic.json") >> spec;
      spec["repeat_rx"] = response(7, {1, 6, 0, 0, 128, 63, 'A'}, false);
      spec["advance_tick_100us"] = false;
      replay_file replay(spec);
      backend b;
      const auto before = std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
      auto capture = submit(b, {{"group", "wave"}, {"action", "capture"},
                           {"replay", replay.path.string()}, {"duration", 0}});
      std::this_thread::sleep_for(100ms);
      require(frame_cancel(b.h, capture) == 0, "cancel MCU capture");
      wait(b, capture);
      auto page = call(b, {{"group", "data"}, {"action", "read"},
                           {"dataset", capture}, {"limit", 1}});
      const auto &sample = page["data"]["records"].at(0);
      const auto after = std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
      require(sample["time_source"] == "host_receive" && sample["time"].get<double>() >= before && sample["time"].get<double>() <= after,
              "MCU timestamps use Unix wall clock, not uptime");
    }
    {
      json spec;
      std::ifstream(fixture / "wave-periodic.json") >> spec;
      auto packet = spec["repeat_rx"].get<std::string>();
      std::string burst;
      for (int i = 0; i < 64; ++i) burst += packet;
      spec["repeat_rx"] = burst;
      spec["advance_tick_100us"] = false;
      spec["period_ms"] = 1;
      replay_file replay(spec);
      backend b;
      auto id = submit(b, {{"group", "wave"}, {"action", "capture"},
                           {"replay", replay.path.string()}, {"duration", 0}});
      auto deadline = std::chrono::steady_clock::now() + 15s;
      json page;
      do {
        std::this_thread::sleep_for(30ms);
        page = call(b, {{"group", "data"}, {"action", "read"},
                        {"dataset", id}, {"limit", 1}});
        require(std::chrono::steady_clock::now() < deadline, "history load deadline");
      } while (!page["ok"] || page["data"]["total"].get<int>() < 110000);
      require(page["data"]["dropped"] == 0, "wave history must not evict at 100000");
      auto stopped = call(b, {{"group", "wave"}, {"action", "stop"}});
      require(stopped["ok"], "continuous capture manual stop");
      auto done = wait(b, id);
      require(done["data"]["stop_confirmed"] == true, "continuous stop acknowledged");
      auto view = call(b, {{"group", "data"}, {"action", "view"},
                           {"dataset", id}, {"seconds", 0}});
      require(view["ok"] && view["data"]["total"] >= 110000 &&
                  view["data"]["records"].size() < 100000,
              "full history viewport samples display without deleting originals");
      auto first = call(b, {{"group", "data"}, {"action", "read"},
                            {"dataset", id}, {"limit", 1}});
      require(first["data"]["records"] == page["data"]["records"],
              "oldest sample survives full history rendering");
    }
    {
      backend b;
      std::vector<std::uint64_t> ids;
      for (int i = 0; i < 128; ++i)
        ids.push_back(submit(b, {{"group", "status"}}));
      auto text = json{{"group", "status"}}.dump();
      std::uint64_t id;
      require(frame_submit(b.h, text.data(),
                           static_cast<std::uint32_t>(text.size()), &id) == -9,
              "operation quota");
      for (auto i : ids)
        require(wait(b, i)["ok"], "queued completion");
      require(call(b, {{"group", "status"}})["ok"], "capacity reclaimed");
    }
    {
      backend b;
      auto result =
          call(b, {{"group", "wave"},
                   {"action", "capture"},
                   {"replay", (fixture / "wave-periodic.json").string()},
                   {"duration", 30},
                   {"timeout", 100}});
      require(result["code"] == 4 && result["data"]["stop_confirmed"] == true,
              "explicit stream deadline stops device and retains partial data");
    }
    {
      backend b;
      auto result = call(b, {{"group", "param"},
                             {"action", "read"},
                             {"name", "TEST_COUNTER"},
                             {"replay", (fixture / "timeout.json").string()},
                             {"response_timeout", 20}});
      require(result["code"] == 4, "timeout classification");
      require(call(b, {{"group", "status"}})["data"]["connected"] == false,
              "timeout invalidates connection against late ACK");
    }
    {
      backend b;
      std::uint64_t id;
      require(frame_submit(b.h, "{", 1, &id) == -2, "invalid JSON ABI");
      require(frame_cancel(b.h, 99999) == -1, "unknown operation");
    }
    {
      backend b;
      auto first = call(
          b,
          {{"group", "jlink"}, {"action", "connect"}, {"jlink_exe", argv[2]}});
      require(first["ok"] && first["data"]["session_reused"] == false,
              "Commander starts with buffered stdout");
      require(call(b, {{"group", "jlink"},
                       {"action", "connect"}})["data"]["session_reused"] ==
                  true,
              "persistent Commander connection");
      auto probe = submit(b, {{"group", "jlink"},
                              {"action", "connect"},
                              {"device", "HANG"},
                              {"timeout", 500}});
      auto wave =
          submit(b, {{"group", "wave"},
                     {"action", "capture"},
                     {"replay", (fixture / "wave-periodic.json").string()},
                     {"duration", .1}});
      require(wait(b, wave)["ok"],
              "J-Link wait must not block serial acquisition");
      require(wait(b, probe)["code"] == 4,
              "J-Link deadline terminates its owned process");
      require(call(b, {{"group", "status"}})["data"]["connected"] == true,
              "J-Link timeout leaves serial session valid");
    }
    {
      backend b;
      auto partial =
          call(b, {{"group", "scope"},
                   {"action", "pull"},
                   {"replay", (fixture / "scope-partial.json").string()},
                   {"response_timeout", 20}});
      require(partial["code"] == 4 && partial["data"]["count"] == 1,
              "Scope timeout preserves received samples");
      auto page = call(b, {{"group", "data"},
                           {"action", "read"},
                           {"dataset", partial["data"]["dataset_id"]}});
      require(page["data"]["records"][0]["tag"] == 7 &&
                  page["data"]["state"] == "partial",
              "Scope partial dataset and tag");
    }
    {
      json periodic;
      std::ifstream(fixture / "wave-periodic.json") >> periodic;
      periodic["steps"].back()["rx"] = json::array();
      replay_file broken_stop(periodic);
      backend b;
      auto result = call(b, {{"group", "wave"},
                             {"action", "capture"},
                             {"replay", broken_stop.path.string()},
                             {"duration", .1},
                             {"response_timeout", 20}});
      require(result["code"] == 8 && result["data"]["stop_confirmed"] == false,
              "unconfirmed stop classification");
      require(call(b, {{"group", "status"}})["data"]["connected"] == false,
              "failed stop invalidates session");
    }
    {
      auto ack = response(0x2c, {1, 1, 100, 0});
      replay_file trace(json::array({
          json{{"rx", {ack, response(0x2d, {1, 0, 0, 0, 123, 0}, false)}}},
          json{{"rx", {ack}}}}));
      backend b;
      auto id = submit(b, {{"group", "trace"},
                           {"action", "capture"},
                           {"replay", trace.path.string()},
                           {"duration", 0}});
      std::this_thread::sleep_for(80ms);
      require(frame_cancel(b.h, id) == 0, "trace cancellation");
      auto result = wait(b, id);
      require(result["code"] == 130 &&
                  result["data"]["stop_confirmed"] == true &&
                  result["data"]["count"].get<int>() > 0,
              "Trace partial data and stop ACK");
    }
    {
      frame::bytes info(48);
      info[5] = 1;
      info[10] = 2;
      info[12] = 1;
      replay_file incomplete(
          json::array({json{{"rx", {response(0x30, info)}}}}));
      backend b;
      auto result = call(b, {{"group", "sfra"},
                             {"action", "points"},
                             {"replay", incomplete.path.string()}});
      require(result["code"] == 7,
              "SFRA ready with partial table is not a completed sweep");
    }
    {
      auto bits=[](float v){return std::bit_cast<std::uint32_t>(v);};
      auto row=[&](float data,float maximum,float minimum,bool flags){
        frame::bytes b{4,6};frame::put(b,bits(data),4);frame::put(b,bits(maximum),4);frame::put(b,bits(minimum),4);if(flags)b.push_back(0);
        b.insert(b.end(),{'G','A','I','N'});return b;
      };
      frame::bytes write{4};frame::put(write,bits(1.25f),4);frame::put(write,bits(20.f),4);frame::put(write,bits(-1.f),4);write.insert(write.end(),{'G','A','I','N'});
      frame::packet expected;expected.src=1;expected.dst=2;expected.word=3;expected.ack=0;expected.payload=write;
      replay_file parameters(json::array({
          json{{"rx",{response(1,{1,0,0,0}),response(4,row(1.f,10.f,0.f,true),false)}}},
          json{{"tx",frame::hex(frame::encode(expected))},{"rx",{response(3,row(1.25f,20.f,-1.f,false))}}}}));
      backend b;
      require(call(b,{{"group","param"},{"action","list"},{"replay",parameters.path.string()}})["ok"],"FP32 parameter catalog");
      auto result=call(b,{{"group","param"},{"action","write"},{"name","GAIN"},{"value","1.25"},{"min","-1"},{"max","20"}});
      require(result["ok"]&&result["data"]["value"]==1.25&&result["data"]["min"]==-1&&result["data"]["max"]==20,"FP32 data and edited bounds sent/read back");
      require(result["data"]["verification"]=="write_ack"&&result["data"]["ack_received"]==true,"complete write ACK needs no second read");
      require(call(b,{{"group","param"},{"action","write"},{"name","GAIN"},{"value","1"},{"min","5"},{"max","2"}})["code"]==2,"Reject reversed edited bounds before sending");
      for(unsigned scenario=0;scenario<5;++scenario){
        frame::packet listRequest;listRequest.src=1;listRequest.dst=2;listRequest.ack=0;listRequest.word=1;
        json replies=json::array();
        if(scenario!=3){replies.push_back(response(1,{1,0,0,0}));replies.push_back(response(4,row(scenario==1?1.f:1.25f,scenario==2?10.f:20.f,-1.f,true),false));}
        auto catalog=row(1.f,10.f,0.f,true);
        if(scenario==4)catalog[1]=7;
        auto writeRequest=expected;
        if(scenario==4){writeRequest.payload={4};for(unsigned i=0;i<12;++i)writeRequest.payload.push_back(0);writeRequest.payload.insert(writeRequest.payload.end(),{'G','A','I','N'});}
        replay_file missingAck(json::array({
          json{{"rx",{response(1,{1,0,0,0}),response(4,catalog,false)}}},
          json{{"tx",frame::hex(frame::encode(writeRequest))},{"rx",json::array()}},
          json{{"tx",frame::hex(frame::encode(listRequest))},{"rx",replies}}}));
        backend fallback;
        require(call(fallback,{{"group","param"},{"action","list"},{"replay",missingAck.path.string()}})["ok"],"fallback catalog");
        auto confirmed=call(fallback,{{"group","param"},{"action","write"},{"name","GAIN"},{"value","1.25"},{"min","-1"},{"max","20"},{"response_timeout",30}});
        if(scenario==0)require(confirmed["ok"]&&confirmed["data"]["verification"]=="directory_readback"&&confirmed["data"]["ack_received"]==false,"missing ACK succeeds only after fresh value and bounds verification");
        else require(confirmed["code"]==(scenario>=3?4:7),"mismatch, unavailable readback and unconfirmed commands stay failures");
      }
    }
    std::cout << "PASS: ABI, events, quotas, persistent session, paging, "
                 "concurrency, cancellation, stop ACK and timeout isolation\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
