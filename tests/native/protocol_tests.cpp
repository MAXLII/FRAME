#include "acquisition.hpp"
#include "protocol.hpp"
#include <fstream>
#include <iostream>
using namespace frame;
static void check(bool ok, const char *text) {
  if (!ok)
    throw std::runtime_error(text);
}
int main(int argc, char **argv) {
  try {
    check(argc == 2, "fixture path required");
    std::ifstream f(argv[1]);
    json fixtures;
    f >> fixtures;
    unsigned tests = 0;
    for (auto &vector : fixtures) {
      auto b = unhex(vector["frame"]);
      for (std::size_t split = 0; split <= b.size(); ++split) {
        parser p;
        auto a = p.feed(std::span(b).first(split));
        auto c = p.feed(std::span(b).subspan(split));
        a.insert(a.end(), c.begin(), c.end());
        check(a.size() == 1, "fragmented frame");
        check(a[0].payload == unhex(vector["payload"]), "payload equivalence");
        check(encode(a[0]) == b, "encode equivalence");
        auto decoded = decode(a[0].word, a[0].payload);
        check(!decoded.is_null(), "decode");
        for (auto item = vector["expected_native"].begin();
             item != vector["expected_native"].end(); ++item)
          check(decoded.at(item.key()) == item.value(),
                "golden payload semantics");
        ++tests;
      }
      auto corrupt = b;
      corrupt[11] ^= 1;
      corrupt.insert(corrupt.end(), b.begin(), b.end());
      parser p;
      check(p.feed(corrupt).size() == 1, "CRC recovery");
      auto joined = b;
      joined.insert(joined.end(), b.begin(), b.end());
      parser concatenated;
      check(concatenated.feed(joined).size() == 2, "concatenated frames");
      ++tests;
    }
    for (auto s : {"F", "GG", "0x12"}) {
      bool rejected = false;
      try {
        unhex(s);
      } catch (...) {
        rejected = true;
      }
      check(rejected, "invalid hex rejection");
      ++tests;
    }
    check(crc(bytes{'1', '2', '3', '4', '5', '6', '7', '8', '9'}) == 0x29b1,
          "CRC known answer");
    bool overflow = false;
    try {
      raw_value(256, 1);
    } catch (...) {
      overflow = true;
    }
    check(overflow, "type overflow");
    check(decode(0x0c, {})["success"] == true, "E507 empty wave ACK");
    tick_clock ticks;
    check(ticks.extend(0xfffffffe) == 0xfffffffeull, "counter init");
    check(ticks.extend(2) == 0x100000002ull && ticks.wraps == 1,
          "counter wrap");
    ticks.extend(1);
    check(ticks.out_of_order == 1, "out of order timestamp");
    batch_integrity batches;
    batches.observe(1, 4, 0, 2);
    batches.observe(1, 4, 1, 1);
    batches.observe(2, 4, 0, 4);
    check(batches.missing == 2 && batches.duplicates == 1,
          "missing and duplicate sample indexes");
    for (auto input : {"42garbage", "NaN", "1e999"}) {
      bool bad = false;
      try {
        raw_value(input, 6);
      } catch (...) {
        bad = true;
      }
      check(bad, "strict numeric input");
    }
    check(parameter(unhex("0106cdcc8c3f58"), 6)["value"].get<float>() > 1.099f,
          "float parameter endian");
    check(parameter(unhex("0104ffffffff58"), 6)["value"] == -1,
          "signed parameter decode");
    for (auto word : {0x19, 0x1f, 0x30, 0x35, 0x27, 0x39}) {
      bool bad = false;
      try {
        decode(static_cast<std::uint8_t>(word), bytes{0});
      } catch (...) {
        bad = true;
      }
      check(bad, "truncated business payload");
    }
    std::cout << "PASS " << tests + 2 << " protocol checks\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
