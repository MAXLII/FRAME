// SPDX-License-Identifier: MIT
#include "frame_stream_decoder.hpp"
#include "stream_link.hpp"
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void require(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }
template<class F> void rejects(F action) {
  bool rejected = false;
  try { action(); } catch (const std::exception &) { rejected = true; }
  require(rejected, "Expected rejection");
}
// Deliberately unrelated to FRAME: '$' begins a bounded text record, LF ends it.
class TextDecoder final : public frame::StreamDecoder {
  std::vector<std::string> &output_;
  std::string partial_;
  bool active_ = false;
public:
  explicit TextDecoder(std::vector<std::string> &output) : output_(output) {}
  std::string_view Name() const noexcept override { return "test-text"; }
  void Feed(std::span<const std::uint8_t> data) override {
    for (auto b : data) {
      if (b == '$') { partial_.clear(); active_ = true; }
      else if (active_ && b == '\n') { output_.push_back(partial_); Reset(); }
      else if (active_) { if (partial_.size() == 64) Reset(); else partial_ += static_cast<char>(b); }
    }
  }
  void Reset() noexcept override { partial_.clear(); active_ = false; }
};
class FailingDecoder final : public frame::StreamDecoder {
  unsigned &resets_;
public:
  explicit FailingDecoder(unsigned &resets) : resets_(resets) {}
  std::string_view Name() const noexcept override { return "failing"; }
  void Feed(std::span<const std::uint8_t>) override { throw std::runtime_error("decoder error"); }
  void Reset() noexcept override { ++resets_; }
};
}
int main() {
  try {
    frame::packet packet; packet.word = 2; packet.payload = {1, 5, 42, 0, 0, 0, 'X'};
    auto wire = frame::encode(packet);
    frame::parser parser;
    std::vector<frame::packet> packets;
    std::vector<std::string> texts;
    frame::StreamLink link;
    link.AddDecoder(std::make_unique<frame::FrameStreamDecoder>(parser, [&](frame::packet p) { packets.push_back(std::move(p)); }));
    link.AddDecoder(std::make_unique<TextDecoder>(texts));
    rejects([&] { link.AddDecoder(std::make_unique<TextDecoder>(texts)); });
    frame::bytes mixed{'$', 'o', 'n', 'e', '\n'};
    mixed.insert(mixed.end(), wire.begin(), wire.end());
    mixed.insert(mixed.end(), wire.begin(), wire.end());
    mixed.insert(mixed.end(), {'$', 't', 'w', 'o', '\n'});
    link.Push(mixed);
    require(link.Process(0) == 0 && link.PendingBytes() == mixed.size(), "Zero budget must preserve pending bytes");
    while (link.PendingBytes()) require(link.Process(3) <= 3, "Per-round processing budget exceeded");
    require(packets.size() == 2 && packets[0].payload == packet.payload, "Fragmented/coalesced binary frames");
    require(texts == std::vector<std::string>({"one", "two"}), "Independent text protocol on the same link");
    rejects([&] { link.AddDecoder(std::make_unique<TextDecoder>(texts)); });
    auto corrupt = wire; corrupt[11] ^= 0x01;
    link.Push(corrupt); link.Process(); link.Push(wire); link.Process();
    require(packets.size() == 3 && parser.rejected > 0, "CRC rejection and resynchronization");
    link.Push(std::span(wire).first(8)); link.Process();
    link.Push(frame::bytes{'$', 'o', 'l', 'd'}); link.Process();
    link.Push(frame::bytes{1, 2}); // Also discard queued, not-yet-decoded bytes on reconnect.
    link.Reset();
    require(link.PendingBytes() == 0 && link.DecoderCount() == 2, "Reset retains bindings and discards queued bytes");
    link.Push(std::span(wire).subspan(8)); link.Process();
    link.Push(frame::bytes{'\n'}); link.Process();
    require(packets.size() == 3 && texts.size() == 2, "Partial state must not cross reconnect");
    for (auto b : wire) { link.Push(std::span(&b, 1)); link.Process(1); }
    require(packets.size() == 4, "Single-byte incremental decoding");

    std::vector<std::string> otherTexts;
    frame::StreamLink other(8); other.AddDecoder(std::make_unique<TextDecoder>(otherTexts));
    other.Push(frame::bytes{'$', 'a'}); other.Process();
    link.Push(frame::bytes{'$', 'b', '\n'}); link.Process();
    other.Push(frame::bytes{'\n'}); other.Process();
    require(otherTexts == std::vector<std::string>({"a"}) && texts.back() == "b", "State isolation between links");
    other.Push(frame::bytes(8, 0)); rejects([&] { other.Push(frame::bytes{1}); });
    require(other.PendingBytes() == 8, "Overflow must not partially append or drop input");
    other.Reset();
    unsigned resets = 0;
    frame::StreamLink failed; failed.AddDecoder(std::make_unique<FailingDecoder>(resets));
    failed.Push(frame::bytes{1, 2}); rejects([&] { failed.Process(); });
    require(resets == 1 && failed.PendingBytes() == 0 && failed.Process() == 0, "Decoder failure must reset partial state and never replay bytes");
    std::cout << "PASS: protocol fan-out, independent state, byte budgets, fragmentation/coalescing, CRC recovery, reconnect, queue overflow and decoder failure\n";
    return 0;
  } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
