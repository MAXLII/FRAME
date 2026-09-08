// SPDX-License-Identifier: MIT
#include "commander.hpp"
#include <fstream>
namespace frame {
void commander::close() noexcept {
  if (process_) {
    if (input_) {
      DWORD n;
      WriteFile(input_, "exit\n", 5, &n, nullptr);
    }
    if (WaitForSingleObject(process_, 1000) == WAIT_TIMEOUT) {
      TerminateProcess(process_, 130);
      WaitForSingleObject(process_, 1000);
    }
    CloseHandle(process_);
    process_ = nullptr;
  }
  if (input_) {
    CloseHandle(input_);
    input_ = nullptr;
  }
  if (output_) {
    CloseHandle(output_);
    output_ = nullptr;
  }
  if (!directory_.empty()) {
    std::error_code ec;
    std::filesystem::remove_all(directory_, ec);
    directory_.clear();
  }
  identity.clear();
}
std::string commander::drain() {
  std::string text;
  DWORD available = 0;
  while (output_ &&
         PeekNamedPipe(output_, nullptr, 0, nullptr, &available, nullptr) &&
         available) {
    char buffer[4096];
    DWORD read = 0;
    if (!ReadFile(output_, buffer, std::min<DWORD>(available, sizeof(buffer)),
                  &read, nullptr))
      break;
    text.append(buffer, read);
    if (text.size() > 65536)
      text.erase(0, text.size() - 65536);
  }
  return text;
}
void commander::open(const std::string &executable, const std::string &device,
                     unsigned probe, const std::function<void()> &guard,
                     const std::string &interface_name, unsigned speed) {
  if ((interface_name != "SWD" && interface_name != "JTAG") || speed < 1 || speed > 50000)
    throw failure(2, "Invalid J-Link interface or speed");
  close();
  if (executable.find_first_of("\"\r\n") != std::string::npos)
    throw failure(2, "Invalid executable path");
  SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
  HANDLE child_input = nullptr, child_output = nullptr;
  if (!CreatePipe(&child_input, &input_, &sa, 0))
    throw failure(3, "Cannot create Commander input pipe");
  if (!CreatePipe(&output_, &child_output, &sa, 0)) {
    CloseHandle(child_input);
    close();
    throw failure(3, "Cannot create Commander output pipe");
  }
  SetHandleInformation(input_, HANDLE_FLAG_INHERIT, 0);
  SetHandleInformation(output_, HANDLE_FLAG_INHERIT, 0);
  STARTUPINFOW si{};
  si.cb = sizeof(si);
  si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
  si.wShowWindow = SW_HIDE;
  si.hStdInput = child_input;
  si.hStdOutput = child_output;
  si.hStdError = child_output;
  PROCESS_INFORMATION pi{};
  auto command = wide("\"" + executable + "\" -NoGui 1 -device " + device +
                      " -if " + interface_name + " -speed " + std::to_string(speed) + " -autoconnect 1 -ExitOnError 1");
  if (probe)
    command += wide(" -USB " + std::to_string(probe));
  auto ok =
      CreateProcessW(wide(executable).c_str(), command.data(), nullptr, nullptr,
                     TRUE, CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi);
  CloseHandle(child_input);
  CloseHandle(child_output);
  if (!ok) {
    close();
    throw failure(3, "Cannot start Commander");
  }
  process_ = pi.hProcess;
  CloseHandle(pi.hThread);
  auto directory =
      std::filesystem::temp_directory_path() /
      (L"frame-commander-" + std::to_wstring(GetCurrentProcessId()) + L"-" +
       std::to_wstring(pi.dwProcessId));
  if (!std::filesystem::create_directory(directory)) {
    close();
    throw failure(8, "Commander temporary session directory already exists");
  }
  directory_ = directory;
  try {
    exchange("connect", guard);
    identity = executable + "|" + device + "|" + std::to_string(probe) + "|" + interface_name + "|" + std::to_string(speed);
  } catch (...) {
    close();
    throw;
  }
}
std::string commander::exchange(const std::string &command,
                                const std::function<void()> &guard) {
  if (!alive())
    throw failure(3, "Commander session is closed");
  auto marker = directory_ / (std::to_wstring(++sequence_) + L".bin");
  // Commander buffers stdout when redirected. A one-byte SRAM save, executed
  // after the requested command, is an explicit completion fence on E507.
  auto line =
      command + "\nsavebin \"" + marker.string() + "\", 0x20000000, 0x1\n";
  DWORD count = 0;
  std::string output;
  try {
    if (!WriteFile(input_, line.data(), static_cast<DWORD>(line.size()), &count,
                   nullptr) ||
        count != line.size())
      throw failure(3, "Commander input failed");
    while (true) {
      guard();
      output += drain();
      if (output.size() > 65536)
        output.erase(0, output.size() - 65536);
      std::error_code ec;
      auto size = std::filesystem::file_size(marker, ec);
      if (!ec && size == 1) {
        std::filesystem::remove(marker, ec);
        return output;
      }
      if (!alive())
        throw failure(3, "Commander exited: " + output);
      Sleep(5);
    }
  } catch (...) {
    close();
    throw;
  }
}
} // namespace frame
