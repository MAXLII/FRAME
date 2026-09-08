// Real CTRL_C_EVENT delivery in an isolated hidden console; no desktop input.
#define WIN32_LEAN_AND_MEAN
#include <Windows.h>
#include <chrono>
#include <iostream>
#include <nlohmann/json.hpp>
#include <sstream>
#include <thread>
#include <string>
int wmain(int argc, wchar_t **argv) {
  if (argc != 3 && argc != 4)
    return 2;
  bool ndjson = argc == 4 && std::wstring(argv[3]) == L"--ndjson";
  SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
  HANDLE read = nullptr, write = nullptr;
  if (!CreatePipe(&read, &write, &sa, 0))
    return 2;
  SetHandleInformation(read, HANDLE_FLAG_INHERIT, 0);
  HANDLE input =
      CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa,
                  OPEN_EXISTING, 0, nullptr);
  STARTUPINFOW start{};
  start.cb = sizeof(start);
  start.dwFlags = STARTF_USESHOWWINDOW | STARTF_USESTDHANDLES;
  start.wShowWindow = SW_HIDE;
  start.hStdOutput = write;
  start.hStdError = write;
  start.hStdInput = input;
  PROCESS_INFORMATION process{};
  std::wstring command = L"\"" + std::wstring(argv[1]) +
                         L"\" wave capture --replay \"" +
                         std::wstring(argv[2]) + L"\" --duration 60 " + (ndjson ? L"--ndjson" : L"--json");
  if (!CreateProcessW(argv[1], command.data(), nullptr, nullptr, TRUE,
                      CREATE_NEW_CONSOLE, nullptr, nullptr, &start, &process))
    return 2;
  CloseHandle(write);
  CloseHandle(input);
  CloseHandle(process.hThread);
  std::string output;
  std::jthread output_reader([&] {
    char buffer[16384]; DWORD count=0;
    while(ReadFile(read,buffer,sizeof(buffer),&count,nullptr)&&count)output.append(buffer,count);
  });
  Sleep(2000);
  FreeConsole();
  bool attached = AttachConsole(process.dwProcessId) != FALSE;
  SetConsoleCtrlHandler(nullptr, TRUE);
  bool delivered =
      attached && GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0) != FALSE;
  Sleep(100);
  FreeConsole();
  WaitForSingleObject(process.hProcess,7000);
  DWORD code = 0;
  GetExitCodeProcess(process.hProcess, &code);
  if (code == STILL_ACTIVE) {
    TerminateProcess(process.hProcess, 1);
    WaitForSingleObject(process.hProcess, 2000);
  }
  output_reader.join();
  CloseHandle(read);
  CloseHandle(process.hProcess);
  try {
    nlohmann::json result;
    std::size_t records = 0;
    if(ndjson) {
      std::istringstream lines(output); std::string line;
      while(std::getline(lines,line)) {
        if(line.empty())continue;
        auto row=nlohmann::json::parse(line);
        if(row.value("kind",std::string())=="record") {
          if(row.at("index")!=records++)throw std::runtime_error("NDJSON index gap");
        } else result=std::move(row);
      }
    } else result = nlohmann::json::parse(output);
    if (!delivered || code != 130 || result["code"] != 130 ||
        result["data"]["stop_confirmed"] != true ||
        result["data"]["count"].get<int>() == 0)
      throw std::runtime_error("Ctrl+C outcome failed");
    if(ndjson && records != result["data"]["count"].get<std::size_t>())throw std::runtime_error("NDJSON cancelled tail is incomplete");
    std::cout << "PASS: real Ctrl+C, exit 130, partial records and stop ACK\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << " delivered=" << delivered << " exit=" << code
              << " output_tail=" << output.substr(output.size()>2048?output.size()-2048:0) << '\n';
    return 1;
  }
}
