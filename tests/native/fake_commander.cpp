// Deliberately buffered test double for the persistent Commander pipe protocol.
#include <fstream>
#include <iostream>
#include <string>
#include <map>
#include <sstream>
int main(int argc, char **argv) {
  bool hang = false;
  bool memory_fixture = false;
  bool unmapped_fixture = false;
  bool list_fixture = false, ring_fixture = false, moved_fixture = false;
  for (int i = 1; i < argc; ++i)
    if (std::string(argv[i]) == "LIST" || std::string(argv[i]) == "LISTRING" || std::string(argv[i]) == "LISTMOVE") {
      memory_fixture=true;list_fixture=true;ring_fixture=std::string(argv[i])=="LISTRING";moved_fixture=std::string(argv[i])=="LISTMOVE";
    } else if (std::string(argv[i]) == "UNMAPPED") {memory_fixture=true;unmapped_fixture=true;}
    else if (std::string(argv[i]) == "TESTMEM") memory_fixture = true;
    else if (std::string(argv[i]) == "HANG")
      hang = true;
  std::string line;
  std::map<unsigned, unsigned char> memory;
  if(list_fixture){
    auto store=[&](unsigned address,unsigned value){for(unsigned i=0;i<4;++i)memory[address+i]=static_cast<unsigned char>(value>>(i*8));};
    store(0x20001000,101);store(0x20001004,0x20001010);store(0x20001010,202);store(0x20001014,ring_fixture?0x20001000:0);
  }
  while (std::getline(std::cin, line)) {
    if (line == "exit")
      return 0;
    if (hang)
      continue;
    if (line.starts_with("savebin \"")) {
      auto end = line.find('"', 9);
      if (end == std::string::npos)
        return 2;
      std::ofstream file(line.substr(9, end - 9), std::ios::binary);
      auto comma = line.rfind(',');
      auto size = std::stoul(line.substr(comma + 1), nullptr, 0);
      auto first_comma = line.find(',', end);
      auto address = static_cast<unsigned>(std::stoul(line.substr(first_comma + 1, comma - first_comma - 1), nullptr, 0));
      if (size > 4096) return 3;
      for (unsigned i = 0; i < size; ++i) {
        unsigned word = memory_fixture ? (unmapped_fixture ? 0x20001008u : moved_fixture ? 0x20001010u : 0x20001000u) : 0u;
        auto value = memory.contains(address + i) ? memory[address + i] : ((word >> ((i % 4) * 8)) & 255);
        file.put(static_cast<char>(value));
      }
    } else if (line.starts_with("w1 ") || line.starts_with("w2 ") || line.starts_with("w4 ")) {
      std::istringstream command(line.substr(3));unsigned address=0,value=0;command>>std::hex>>address>>value;
      for(unsigned i=0;i<static_cast<unsigned>(line[1]-'0');++i)memory[address+i]=static_cast<unsigned char>(value>>(i*8));
    } else
      std::cout << "Test Commander accepted command\n";
  }
  return 0;
}
