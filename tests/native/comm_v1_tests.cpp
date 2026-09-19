// SPDX-License-Identifier: MIT
// COMM v1 (0xE9) protocol and codec native tests for the FRAME backend.
#include "protocol.hpp"
#include <iostream>
using namespace frame;
static void check(bool ok, const char *text) {
  if (!ok)
    throw std::runtime_error(text);
}
int main() {
  try {
    // SUM known answers.
    check(sum(bytes{0x01, 0xFF}) == 0x55, "sum zero maps to 0x55");
    check(sum(bytes{0x12, 0x34}) == 0x46, "sum plain value");

    // RLE document example: 12 34 00 00 00 00 00 AB -> 01 12 34 82 00 00 AB.
    {
      const bytes input = {0x12, 0x34, 0x00, 0x00, 0x00, 0x00, 0x00, 0xAB};
      bytes output(32, 0);
      check(codec_encode(codec::rle, input, 300, output), "rle encodes example");
      check(output == bytes{0x01, 0x12, 0x34, 0x82, 0x00, 0x00, 0xAB},
            "rle example golden bytes");
      bytes decoded(32, 0);
      check(codec_decode(codec::rle, output, 300, decoded), "rle decodes example");
      check(decoded == input, "rle roundtrip bytes");
    }

    // RLE long repeat: 300 x 0xAA encodes to three repeat tokens (6 bytes).
    {
      bytes input(300, 0xAA), output(64, 0);
      check(codec_encode(codec::rle, input, 600, output), "rle long repeat");
      check(output.size() == 6, "rle long repeat length");
      bytes decoded(512, 0);
      check(codec_decode(codec::rle, output, 600, decoded), "rle long repeat decode");
      check(decoded.size() == 300, "rle long repeat decode length");
    }

    // DICT roundtrip with preset codebook entries.
    {
      const std::string text = "counter ok 12";
      bytes output(64, 0), decoded(64, 0);
      check(codec_encode(codec::dict,
                         std::span<const std::uint8_t>(
                             reinterpret_cast<const std::uint8_t *>(text.data()),
                             text.size()),
                         300, output),
            "dict encodes");
      check(output.size() < text.size(), "dict compresses known text");
      check(codec_decode(codec::dict, output, 300, decoded), "dict decodes");
      check(decoded.size() == text.size() &&
                std::string_view(reinterpret_cast<const char *>(decoded.data()),
                                 decoded.size()) == text,
            "dict roundtrip bytes");
      // Invalid token 0xC0 rejected.
      check(!codec_decode(codec::dict, bytes{0xC0}, 300, decoded),
            "dict rejects invalid token");
    }

    // LZSS roundtrip with periodic content.
    {
      bytes input(200, 0), output(300, 0), decoded(300, 0);
      for (std::size_t i = 0; i < input.size(); ++i)
        input[i] = static_cast<std::uint8_t>("abcd"[i % 4]);
      check(codec_encode(codec::lzss, input, 300, output), "lzss encodes");
      check(output.size() < input.size(), "lzss compresses periodic data");
      check(codec_decode(codec::lzss, output, 300, decoded), "lzss decodes");
      check(decoded == input, "lzss roundtrip bytes");
      // Offset beyond history rejected.
      check(!codec_decode(codec::lzss, bytes{0x83, 0x7F}, 300, decoded),
            "lzss rejects offset beyond history");
    }

    // Limit bound aborts encoding.
    {
      bytes input(64, 0x00), output(128, 0);
      check(!codec_encode(codec::rle, input, 1, output), "rle aborts at limit");
      check(!codec_encode(codec::rle, input, 0, output), "rle rejects zero limit");
    }

    // ZERO (nibble zero-count) codec: golden table and roundtrips.
    {
      // Bytes 01 23 45 67 89 AB CD EF carry nibbles 0..F, which encode to the
      // 80-bit table stream padded to 10 bytes (MSB-first).
      const bytes input = {0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF};
      bytes encoded(32, 0);
      check(codec_encode(codec::zero, input, 300, encoded), "zero encodes table");
      check(encoded == bytes{0x48, 0x86, 0xCC, 0x61, 0xDC, 0xE3, 0x87, 0xBC, 0xF1, 0xE1},
            "zero golden bytes");
      bytes decoded(32, 0);
      check(codec_decode(codec::zero, encoded, 300, decoded), "zero decodes golden");
      check(decoded == input, "zero roundtrip");

      // Dense zeros compress 16 bytes to 8.
      bytes zeros(16, 0x00), small(32, 0), back(32, 0);
      check(codec_encode(codec::zero, zeros, 300, small), "zero compresses zeros");
      check(small.size() == 8, "zero zeros length");
      check(codec_decode(codec::zero, small, 300, back), "zero decodes zeros");
      check(back == zeros, "zero zeros roundtrip");

      // All-padding input and unterminated runs are rejected.
      check(!codec_decode(codec::zero, bytes{0xFF}, 300, back),
            "zero rejects all-padding input");
      check(!codec_decode(codec::zero, bytes{0x00}, 300, back),
            "zero rejects unterminated run");

      // The limit bound aborts encoding.
      check(!codec_encode(codec::zero, zeros, 8, small), "zero aborts at limit");
      bytes too_small(1, 0);
      check(!codec_encode(codec::zero, bytes{0xFF}, 300, too_small),
            "zero rejects output capacity before writing a second byte");
      check(!codec_encode(codec::zero, bytes{0x00, 0x00, 0x00}, 300, too_small),
            "zero checks capacity even when most encoded bits are zero");
      bytes exact(2, 0);
      check(codec_encode(codec::zero, bytes{0xFF}, 300, exact) && exact.size() == 2,
            "zero accepts exact output capacity");
    }

    // Codebook CRC32 golden value (matches device code/lib/codec_dict.c).
    check(codebook_crc32() == 0xB6DD009Du, "codebook crc32 golden");

    // encode_v1: pure command wire golden layout.
    {
      packet p;
      p.src = 2;
      p.dst = 1;
      p.group = 5;
      p.word = 0x21;
      p.ack = 0;
      p.seq = 6;
      p.payload.clear();
      const auto wire = encode_v1(p);
      check(wire.size() == 6, "v1 pure command length");
      check(wire[0] == 0xE9, "v1 SOP");
      check((wire[4] & 0x40u) != 0, "v1 CMD bit set");
      check((wire[4] & 0x38u) == 0, "v1 codec RAW");
      check(wire[5] == sum(std::span(wire).first(5)), "v1 SUM");
      // Cross-checked golden bytes shared with the device host test.
      check(wire == bytes{0xE9, 0x0E, 0x08, 0x2A, 0x44, 0x6D},
            "v1 pure command golden bytes");
      // MSG little-endian roundtrip through the parser.
      parser parser_instance;
      auto got = parser_instance.feed(wire);
      check(got.size() == 1, "v1 pure command parses");
      check(got[0].seq == 6 && got[0].src == 2 && got[0].dst == 1 &&
                got[0].group == 5 && got[0].word == 0x21 && got[0].ack == 0,
            "v1 pure command fields");
    }

    // encode_v1: 256-byte incompressible payload uses LEN 0x00 and roundtrips.
    {
      packet p;
      p.src = 2;
      p.dst = 1;
      p.group = 1;
      p.word = 0x17;
      p.seq = 1;
      p.payload.resize(256);
      for (std::size_t i = 0; i < p.payload.size(); ++i)
        p.payload[i] = static_cast<std::uint8_t>(i); // strictly increasing: no repeats
      const auto wire = encode_v1(p);
      check(wire.size() == 263, "v1 256 B wire length");
      check(wire[5] == 0, "v1 256 B LEN zero");
      parser parser_instance;
      auto got = parser_instance.feed(wire);
      check(got.size() == 1 && got[0].payload == p.payload, "v1 256 B roundtrip");
    }

    // encode_v1: compression selection kicks in for repetitive payloads.
    {
      packet p;
      p.src = 2;
      p.dst = 1;
      p.group = 1;
      p.word = 0x17;
      p.seq = 2;
      p.payload.assign(100, 0x55);
      const auto wire = encode_v1(p);
      const auto msg = static_cast<std::uint32_t>(wire[1]) |
                       (static_cast<std::uint32_t>(wire[2]) << 8) |
                       (static_cast<std::uint32_t>(wire[3]) << 16) |
                       (static_cast<std::uint32_t>(wire[4]) << 24);
      check(((msg >> 27) & 7u) != 0, "v1 repetitive payload compressed");
      check(wire.size() < 107, "v1 compressed wire shorter");
      parser parser_instance;
      auto got = parser_instance.feed(wire);
      check(got.size() == 1 && got[0].payload == p.payload,
            "v1 compressed roundtrip");
    }

    // encode_v1: CODEC_SELECT stays RAW.
    {
      packet p;
      p.src = 1;
      p.dst = 2;
      p.group = 0;
      p.word = 0;
      p.seq = 5;
      p.payload = codec_select_request();
      const auto wire = encode_v1(p);
      const auto msg = static_cast<std::uint32_t>(wire[1]) |
                       (static_cast<std::uint32_t>(wire[2]) << 8) |
                       (static_cast<std::uint32_t>(wire[3]) << 16) |
                       (static_cast<std::uint32_t>(wire[4]) << 24);
      check(((msg >> 27) & 7u) == 0, "CODEC_SELECT request RAW");
      check(wire.size() == 14, "CODEC_SELECT request length (7 B payload RAW)");
    }

    // is_codec_select_response accepts a valid answer and rejects a corrupt one.
    {
      packet response;
      response.sop = 0xE9;
      response.group = 0;
      response.word = 0;
      response.ack = 1;
      response.payload = {0, 1, 0, 1, 0, 0, 0, 0};
      // Independent device-format fixture: result/codec/id/version/CRC32 LE.
      response.payload = {0, 1, 0, 1, 0x9D, 0x00, 0xDD, 0xB6};
      check(is_codec_select_response(response), "CODEC_SELECT response valid");
      response.payload[0] = 1;
      check(!is_codec_select_response(response), "CODEC_SELECT result nonzero rejected");
      response.payload[0] = 0;
      response.payload[7] ^= 1;
      check(!is_codec_select_response(response), "CODEC_SELECT CRC mismatch rejected");
      response.payload[7] ^= 1;
      for (unsigned i = 1; i <= 3; ++i) {
        response.payload[i] ^= 1;
        check(!is_codec_select_response(response), "CODEC_SELECT identity mismatch rejected");
        response.payload[i] ^= 1;
      }
      response.sop = 0xE8;
      check(!is_codec_select_response(response), "legacy packet cannot negotiate E9");
      parser device;
      auto answer = device.feed(unhex("E90808008008000100019D00DDB6B3"));
      check(answer.size() == 1 && is_codec_select_response(answer[0]),
            "independent device response wire golden negotiates");
    }

    // encode_v1 range rejection.
    {
      packet p;
      p.src = 2;
      p.dst = 1;
      p.group = 1;
      p.word = 0x40; // beyond 0..63
      bool rejected = false;
      try {
        encode_v1(p);
      } catch (const failure &) {
        rejected = true;
      }
      check(rejected, "v1 word range rejected");
    }

    // Parser: corrupt SUM drops the wire, mixed 0xE8/0xE9 stream decodes both.
    {
      packet p;
      p.src = 2;
      p.dst = 1;
      p.group = 1;
      p.word = 0x17;
      p.seq = 3;
      p.payload = {0x11, 0x22, 0x33, 0x44};
      auto wire = encode_v1(p);
      wire.back() ^= 1;
      parser parser_instance;
      check(parser_instance.feed(wire).empty(), "v1 bad SUM dropped");
      check(parser_instance.rejected != 0, "v1 bad SUM counted");

      auto legacy = encode(p);
      auto v1 = encode_v1(p);
      bytes joined;
      joined.insert(joined.end(), legacy.begin(), legacy.end());
      joined.insert(joined.end(), v1.begin(), v1.end());
      parser mixed;
      auto got = mixed.feed(joined);
      check(got.size() == 2 && got[0].sop == 0xE8 && got[1].sop == 0xE9,
            "mixed legacy and v1 frames retain wire identity");
      bytes invalid_header = {0xE9, 0, 0, 0, 0x38, 0};
      invalid_header.insert(invalid_header.end(), legacy.begin(), legacy.end());
      parser noise;
      auto recovered = noise.feed(invalid_header);
      check(recovered.size() == 1 && recovered[0].payload == p.payload && noise.rejected != 0,
            "invalid E9 CODEC must not block a following legacy frame");
    }

    // Parser: fragmented v1 feed across every split point.
    {
      packet p;
      p.src = 2;
      p.dst = 1;
      p.group = 1;
      p.word = 0x17;
      p.seq = 4;
      p.payload = {0xAA, 0xBB, 0xCC, 0xDD};
      const auto wire = encode_v1(p);
      for (std::size_t split = 0; split <= wire.size(); ++split) {
        parser parser_instance;
        auto first = parser_instance.feed(std::span(wire).first(split));
        auto second = parser_instance.feed(std::span(wire).subspan(split));
        first.insert(first.end(), second.begin(), second.end());
        check(first.size() == 1 && first[0].payload == p.payload,
              "v1 fragmented feed");
      }
    }

    std::cout << "PASS comm v1 checks\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
}
