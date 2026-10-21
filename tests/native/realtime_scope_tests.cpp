// SPDX-License-Identifier: MIT
#include "realtime_scope.hpp"
#include <fstream>
#include <iostream>
using namespace frame;
static void Require(bool condition)
{
    if (!condition)
        throw std::runtime_error("scope assertion failed");
}
static bytes Frame(unsigned index, const bytes &payload)
{
    bytes b{0xEA, static_cast<std::uint8_t>(index)};
    b.insert(b.end(), payload.begin(), payload.end());
    put(b, static_cast<std::uint32_t>(payload.size()), 2);
    std::uint8_t sum = 0;

    for (auto value : b)
        sum = static_cast<std::uint8_t>(sum + value);
    b.push_back(sum);
    return b;
}
int main(int argc, char **argv)
{
    RealtimeScopeState state;
    state.channels    = {{1, 6, 4}, {32, 3, 2}};
    state.payloadSize = 6;
    RealtimeScopeDecoder decoder(state);
    auto b = Frame(254, {0xEA, 0xEB, 0x34, 0x12, 0x85, 0xFF});

    for (auto byte : b)
        decoder.Feed(std::span(&byte, 1));
    Require(    state.samples.size() == 1
             && state.samples[0].values[0] == 0x1234EBEA
             && state.samples[0].values[31] == -123);
    decoder.Feed(Frame(255, {0, 0, 0, 0, 0, 0}));
    decoder.Feed(Frame(0, {0, 0, 0, 0, 0, 0}));
    Require(    state.missing == 0
             && state.next == 3);
    decoder.Feed(Frame(0, {0, 0, 0, 0, 0, 0}));
    Require(state.duplicates == 1);
    decoder.Feed(Frame(3, {0, 0, 0, 0, 0, 0}));
    Require(    state.missing == 2
             && std::isnan(state.samples[3].values[0])
             && state.next == 6);
    b.back() ^= 1;
    decoder.Feed(b);
    Require(    state.rejected == 1
             &&!state.fault.empty());
    state.ResetCapture();
    decoder.Reset();
    state.channels    = {{1, 9, 4}, {2, 10, 8}, {3, 7, 8}, {4, 8, 8}, {5, 11, 1}};
    state.payloadSize = 29;
    bytes payload;
    const auto append = [&payload](std::uint64_t bits, unsigned size)
    {
        for (unsigned i = 0; i < size; ++i)
            payload.push_back(static_cast<std::uint8_t>(bits >> (8 * i)));
    };
    append(std::bit_cast<std::uint32_t>(-1.25f), 4);
    append(std::bit_cast<std::uint64_t>(2.5), 8);
    append(UINT64_MAX, 8);
    append(1234567890123ull, 8);
    payload.push_back(1);
    decoder.Feed(Frame(0, payload));
    Require(    state.samples[0].values[0] == -1.25
             && state.samples[0].values[1] == 2.5
             && state.samples[0].values[2] == -1
             && state.samples[0].values[3] == 1234567890123.0
             && state.samples[0].values[4] == 1);
    state.ResetCapture();

    for (unsigned i = 0; i <= 32768; ++i)
        decoder.Feed(Frame(i, payload));
    Require(    !state.fault.empty()
             && state.samples.size() == 32768);

    if (argc == 2)
    {
        std::ifstream input(argv[1], std::ios::binary);
        Require(input.good());
        bytes fixture((std::istreambuf_iterator<char>(input)), {});
        RealtimeScopeState firmware;
        firmware.channels    = {{1, 6, 4}, {32, 3, 2}};
        firmware.payloadSize = 6;
        RealtimeScopeDecoder production(firmware);
        production.Feed(fixture);
        Require(    firmware.samples.size() == 1
                 && firmware.samples[0].values[0] == 0x1234EBEA
                 && firmware.samples[0].values[31] == -123);
    }
    std::cout
        << "PASS: fragmentation, sparse types, EA/EB payload, wrap/gaps/duplicates, checksum, bounded queue and firmware interop\n";
}
