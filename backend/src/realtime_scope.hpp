// SPDX-License-Identifier: MIT
#pragma once
#include "protocol.hpp"
#include "stream_link.hpp"
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <deque>
#include <limits>

namespace frame
{
// Entity: one native runtime owns one scope session. Prior: device ACK precedes
// layout changes. Time: bounded pending samples, modulo-256 wire counter.
class RealtimeScopeState final
{
  public:
    struct Channel
    {
        unsigned number, type, size;
    };
    struct Sample
    {
        std::uint64_t index;
        std::array<double, 32> values{};
    };
    std::vector<Channel> channels;
    std::deque<Sample> samples;
    unsigned transaction = 0, payloadSize = 0;
    std::uint64_t next = 0, missing = 0, duplicates = 0, rejected = 0;
    bool haveIndex = false, running = false;
    bool configurationStaged = false, sampleFrequencyKnown = false;
    unsigned sampleFrequency = 0;
    std::uint8_t lastIndex   = 0;
    std::string fault;
    std::chrono::steady_clock::time_point diagnosticDue{};
    static unsigned TypeSize(unsigned type)
    {
        constexpr unsigned sizes[] = {0, 1, 1, 2, 2, 4, 4, 8, 8, 4, 8, 1};
        return type < std::size(sizes) ? sizes[type] : 0;
    }
    void ResetCapture()
    {
        samples.clear();
        next = missing = duplicates = rejected = 0;
        haveIndex                              = false;
        fault.clear();
    }
    void Data(const bytes &frame)
    {
        if (!fault.empty())
            return;
        unsigned delta = haveIndex ? (unsigned(frame[1]) + 256u - lastIndex) % 256u : 1u;

        if (!delta)
        {
            ++duplicates;
            return;
        }
        // TCP preserves order. A discontinuity indicates a broken acquisition;
        // preserve sample positions using gaps, never join unrelated samples.

        if (samples.size() + delta > 32768)
        {
            fault   = "实时示波器接收队列溢出";
            running = false;
            return;
        }

        for (unsigned i = 1; i < delta; ++i)
        {
            Sample gap{next++};
            gap.values.fill(std::numeric_limits<double>::quiet_NaN());
            samples.push_back(gap);
            ++missing;
        }
        Sample sample{next++};
        unsigned offset = 2;

        for (const auto &channel : channels)
        {
            std::uint64_t bits = 0;

            for (unsigned i = 0; i < channel.size; ++i)
                bits |= std::uint64_t(frame[offset++]) << (8 * i);
            double value;

            if (channel.type == 9)
                value = std::bit_cast<float>(static_cast<std::uint32_t>(bits));
            else if (channel.type == 10)
                value = std::bit_cast<double>(bits);
            else if (channel.type == 11)
                value = bits != 0 ? 1.0 : 0.0;
            else if (channel.type % 2 == 1)
            {
                if (    channel.size < 8
                     && (bits & (std::uint64_t(1) << (channel.size * 8 - 1))))
                    bits |= (~std::uint64_t(0)) << (channel.size * 8);
                value = static_cast<double>(std::bit_cast<std::int64_t>(bits));
            }
            else
                value = static_cast<double>(bits);
            sample.values[channel.number - 1] = value;
        }
        samples.push_back(sample);
        haveIndex = true;
        lastIndex = frame[1];
    }
};

class RealtimeScopeDecoder final : public StreamDecoder
{
    RealtimeScopeState &state_;
    bytes pending_;

  public:
    explicit RealtimeScopeDecoder(RealtimeScopeState &state)
        : state_(state)
    {
    }
    std::string_view Name() const noexcept override
    {
        return "realtime-scope";
    }
    void Reset() noexcept override
    {
        pending_.clear();
    }
    void Feed(std::span<const std::uint8_t> input) override
    {
        pending_.insert(pending_.end(), input.begin(), input.end());
        std::size_t consumed = 0;

        while (consumed < pending_.size())
        {
            const auto *p        = pending_.data() + consumed;
            const auto available = pending_.size() - consumed;
            std::size_t total    = 0;

            if (    *p == 0xEA
                 && state_.payloadSize != 0)
                total = state_.payloadSize + 5;
            else
            {
                ++state_.rejected;
                ++consumed;
                continue;
            }

            if (available < total)
                break;
            std::uint8_t sum = 0;

            for (std::size_t i = 0; i + 1 < total; ++i)
                sum = static_cast<std::uint8_t>(sum + p[i]);

            if (    sum != p[total - 1]
                 || (    *p == 0xEA
                      && (p[total - 3] + (unsigned(p[total - 2]) << 8)) != state_.payloadSize))
            {
                ++state_.rejected;
                state_.fault = "实时示波器帧校验或长度错误";
                consumed += total;
                continue;
            }

            state_.Data(bytes(p, p + total));
            consumed += total;
        }
        pending_.erase(pending_.begin(), pending_.begin() + static_cast<std::ptrdiff_t>(consumed));
    }
};
} // namespace frame
