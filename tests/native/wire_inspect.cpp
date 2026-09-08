#include "protocol.hpp"
#include <fstream>
#include <iostream>
#include <map>
int main(int argc, char **argv) {
  if (argc != 2)
    return 2;
  std::ifstream input(argv[1]);
  frame::parser parser;
  std::map<unsigned, unsigned> counts;
  unsigned packets = 0;
  std::string line;
  while (std::getline(input, line)) {
    auto item = frame::json::parse(line);
    if (item.contains("tx")) {
      auto b = frame::unhex(item["tx"]);
      if (b.size() > 8 && b[7] >= 0x26 && b[7] <= 0x2b)
        std::cout << "TX " << frame::hex(b) << '\n';
    }
    if (!item.contains("rx"))
      continue;
    for (auto &p : parser.feed(frame::unhex(item["rx"]))) {
      ++packets;
      ++counts[p.word];
      if (p.word >= 0x26 && p.word <= 0x2b) {
        std::cout << "RX word=" << unsigned(p.word)
                  << " ack=" << unsigned(p.ack)
                  << " payload=" << frame::hex(p.payload) << '\n';
      }
    }
  }
  std::cout << "packets=" << packets << " bad=" << parser.rejected << '\n';
  for (auto &[word, n] : counts)
    std::cout << word << ":" << n << " ";
  return 0;
}
