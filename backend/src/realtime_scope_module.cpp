// SPDX-License-Identifier: MIT
#include "runtime.hpp"
namespace frame
{
static bytes Request(runtime &r,
                     operation &op,
                     unsigned word,
                     const bytes &payload = {})
{
    auto &s = r.realtime_scope;
    const unsigned id = s.transaction = (s.transaction + 1u) & 65535u;
    bytes b{static_cast<std::uint8_t>(word)};
    put(b, id, 2);
    b.insert(b.end(), payload.begin(), payload.end());
    r.send(0x3A, b);
    auto response = r.wait_packet(op,
                                  0x3A,
                                  true,
                                  [word, id](const packet &p)
                                  {
                                      return p.payload.size() >= 4
                                          && p.payload[0] == word
                                          && reader(p.payload).u16(1) == id;
                                  }).payload;

    if (response[3])
        throw failure(7, "示波器设备拒绝操作，状态 " + std::to_string(response[3]));
    return bytes(response.begin() + 4, response.end());
}
static json Handle(runtime &r, operation &op)
{
    auto &s            = r.realtime_scope;
    const auto &q      = op.command;
    const auto action  = q.value("action", std::string());
    const bool control = q.value("group", std::string()) == "realtime-scope-control";

    if (    action == "configure"
         || (    control
              && action == "set-channel"))
    {
        const auto &channels = q.at("channels");

        if (    !channels.is_array()
             || (    !control
                  && channels.empty())
             || channels.size() > 32)
            throw failure(2, "需要 1～32 个通道");
        std::vector<RealtimeScopeState::Channel> layout;
        unsigned payloadSize = 0;
        std::uint32_t mask   = 0;
        std::vector<bytes> commands;

        for (const auto &channel : channels)
        {
            const auto number = channel.at("channel").get<unsigned>(), type = channel.at("type").get<unsigned>();
            const auto address = channel.at("address").get<std::uint64_t>();
            unsigned size      = RealtimeScopeState::TypeSize(type);

            if (    !number
                 || number > 32
                 || !size
                 || !address
                 || address > UINT32_MAX
                 || (mask & (1u << (number - 1))))
                throw failure(2, "通道、类型或地址无效");
            mask |= 1u << (number - 1);
            layout.push_back({number, type, size});
            payloadSize += size;
            bytes b{static_cast<std::uint8_t>(number), static_cast<std::uint8_t>(type)};
            put(b, static_cast<std::uint32_t>(address), 4);
            commands.push_back(b);
        }
        std::sort(layout.begin(), layout.end(), [](auto a, auto b) { return a.number < b.number; });

        if (control)
        {
            const bool incremental = action == "set-channel"
                                  && s.configurationStaged
                                  &&!s.running;
            const unsigned changed = action == "set-channel" ? q.at("channel").get<unsigned>() : 0u;

            if (    action == "set-channel"
                 && (    changed == 0u
                      || changed > 32u))
                throw failure(2, "通道序号须为 1～32");
            s.configurationStaged = false;
            const auto rate       = [&s](const bytes &ack)
            {
                if (ack.size() >= 4)
                {
                    s.sampleFrequency      = reader(ack).u32(0);
                    s.sampleFrequencyKnown = true;
                }
            };

            if (!incremental)
            {
                Request(r, op, 2);
                s.running = false;
                rate(Request(r, op, 3));

                for (const auto &command : commands)
                    rate(Request(r, op, 4, command));
            }
            else
            {
                const auto found = std::find_if(commands.begin(),
                                                commands.end(),
                                                [changed](const bytes &command) { return command[0] == changed; });
                rate(Request(r,
                             op,
                             4,
                             found != commands.end() ? *found
                                                     : bytes{static_cast<std::uint8_t>(changed), 1u, 0u, 0u, 0u, 0u}));
            }
            s.configurationStaged = true;
        }
        s.channels    = std::move(layout);
        s.payloadSize = payloadSize;
        s.ResetCapture();
        return {{"configured", true},
                {"payload_bytes", payloadSize},
                {"sample_frequency", s.sampleFrequency},
                {"sample_frequency_available", s.sampleFrequencyKnown}};
    }

    if (action == "start")
    {
        if (    control
             && q.contains("frequency"))
            throw failure(2, "采样率由下位机固定，请查询设备能力；启动命令不接受采样率设置");
        const auto rate = q.value("frequency", 0u);

        if (    s.channels.empty()
             || (    !control
                  &&!rate))
            throw failure(2, "通道为空或采样率超限");

        if (    control
             && s.configurationStaged)
        {
            const auto ack = Request(r, op, 5);

            if (    ack.size() < 2
                 || reader(ack).u16(0) != s.payloadSize)
                throw failure(7, "设备通道布局不一致");

            if (ack.size() >= 6)
            {
                s.sampleFrequency      = reader(ack).u32(2);
                s.sampleFrequencyKnown = true;
            }
            s.configurationStaged = false;
        }

        if (    control
             && s.sampleFrequencyKnown
             && s.sampleFrequency == 0u)
            throw failure(7, "设备尚未接入采样中断，当前采样率为 0 Hz");
        s.ResetCapture();
        bytes b;

        if (!control)
            put(b, rate, 4);
        const auto ack = control ? Request(r, op, 6, b) : b;

        if (ack.size() < 4)
            throw failure(7, "采样率应答不完整");
        const unsigned actual = unsigned(ack[0]) | (unsigned(ack[1]) << 8) | (unsigned(ack[2]) << 16)
                              | (unsigned(ack[3]) << 24);

        if (    actual == 0u
             || (    rate != 0u
                  && actual != rate))
            throw failure(7, "设备采样率不一致");
        s.running = true;
        return {{"frequency", actual}, {"bytes_per_second", std::uint64_t(actual) * (s.payloadSize + 5)}};
    }

    if (action == "stop")
    {
        if (control)
            Request(r, op, 2);
        s.running = false;
        return {{"stopped", true}};
    }

    if (action == "capabilities")
    {
        const auto b = Request(r, op, 1);

        if (    b.size() < 42
             || b[0] != 1
             || b[1] != 32)
            throw failure(7, "设备示波器能力不匹配");
        s.sampleFrequencyKnown = b.size() >= 46;
        s.sampleFrequency      = s.sampleFrequencyKnown ? reader(b).u32(42) : 0u;
        return {{"version", b[0]},
                {"channels", b[1]},
                {"max_frequency", reader(b).u32(2)},
                {"sample_frequency", s.sampleFrequency},
                {"sample_frequency_available", s.sampleFrequencyKnown},
                {"byte_budget", reader(b).u32(6)},
                {"elf_sha256", hex(bytes(b.begin() + 10, b.begin() + 42))}};
    }

    if (action == "status")
    {
        const auto device = Request(r, op, 7);

        if (device.size() < 18)
            throw failure(7, "状态应答不完整");
        json status{{"running", device[0] != 0},
                    {"data_connected", device[17] != 0},
                    {"samples", reader(device).u32(1)},
                    {"overflows", reader(device).u32(5)},
                    {"queue_count", reader(device).u32(9)},
                    {"timing_fault", reader(device).u32(13)},
                    {"link_fault", device.size() >= 22 ? reader(device).u32(18) : 0u},
                    {"fault",
                     reader(device).u32(5)
                          || reader(device).u32(13)
                         ? (reader(device).u32(5) ? "设备采样缓存溢出，采集已停止" : "设备采样中断超时，采集已停止")
                         : ""}};

        if (device.size() >= 30)
        {
            status["queue_high_water"] = reader(device).u32(22);
            status["dequeued"]         = reader(device).u32(26);
        }
        r.comm_log.write("realtime_scope_device", status);
        return status;
    }

    if (action == "drain")
    {
        r.pump(1);
        json rows        = json::array();
        const auto count = std::min<std::size_t>(s.samples.size(), 8192);

        for (std::size_t i = 0; i < count; ++i)
        {
            const auto &sample = s.samples.front();
            json values        = json::array();

            for (const auto &channel : s.channels)
            {
                const auto value = sample.values[channel.number - 1];
                values.push_back(std::isfinite(value) ? json(value) : json(nullptr));
            }
            rows.push_back({{"index", sample.index}, {"values", std::move(values)}});
            s.samples.pop_front();
        }

        if (    clock::now() >= s.diagnosticDue
             || !s.fault.empty())
        {
            s.diagnosticDue = clock::now() + std::chrono::seconds(1);
            r.comm_log.write("realtime_scope_rx",
                             {{"samples", s.next},
                              {"missing", s.missing},
                              {"duplicates", s.duplicates},
                              {"rejected", s.rejected},
                              {"pending", s.samples.size()},
                              {"running", s.running},
                              {"fault", s.fault}});
        }
        return {{"rows", std::move(rows)},
                {"missing", s.missing},
                {"duplicates", s.duplicates},
                {"rejected", s.rejected},
                {"pending", s.samples.size()},
                {"fault", s.fault},
                {"running", s.running}};
    }
    throw failure(2, "未知实时示波器操作");
}
static std::unique_ptr<StreamDecoder> Create(runtime &r)
{
    return std::make_unique<RealtimeScopeDecoder>(r.realtime_scope);
}
static void Disconnected(runtime &r)
{
    r.realtime_scope = {};
}
static void Install(BackendRegistry &registry)
{
    registry.Service({"realtime-scope", {"system"}, nullptr, nullptr, Disconnected});
    registry.Protocol({"realtime-scope", "realtime-scope", Create});
    registry.Commands("realtime-scope",
                      "realtime-scope-control",
                      {"capabilities", "configure", "set-channel", "start", "stop", "status"},
                      Handle,
                      {ExecutionLane::Core, true, false, false, "frame-v1"});
    registry.Commands("realtime-scope",
                      "realtime-scope",
                      {"configure", "start", "stop", "drain"},
                      Handle,
                      {ExecutionLane::Core, true, false, false, "realtime-scope"});
}
FRAME_REGISTER_MODULE(frame_module_realtime_scope, Install)
} // namespace frame
