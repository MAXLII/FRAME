// SPDX-License-Identifier: MIT
#include "transport.hpp"
#include <algorithm>
#include <fstream>
#include <SetupAPI.h>
#include <map>
#include <vector>
namespace frame {
std::wstring wide(const std::string &s) {
  if (s.empty())
    return {};
  int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(),
                              static_cast<int>(s.size()), nullptr, 0);
  if (!n)
    throw failure(2, "Invalid UTF-8");
  std::wstring w(n, 0);
  MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(),
                      static_cast<int>(s.size()), w.data(), n);
  return w;
}
static void wincheck(BOOL ok, const char *what) {
  if (!ok)
    throw failure(3, std::string(what) + " (Win32 " +
                         std::to_string(GetLastError()) + ")");
}
void transport::close() {
  tcp_.close();
  if (handle_ != INVALID_HANDLE_VALUE) {
    CancelIoEx(handle_, nullptr);
    CloseHandle(handle_);
    handle_ = INVALID_HANDLE_VALUE;
  }
  replay_ = nullptr;
  repeat_frame_.clear();
  replay_rx_.clear();
  endpoint.clear();
  baud_rate = 0;
  recording_.close();
}
void transport::open(const json &s, const std::function<void()> &guard) {
  close();
  if (s.contains("record")) {
    recording_.open(wide(s.at("record")), std::ios::binary);
    if (!recording_)
      throw failure(8, "Cannot create protocol recording");
  }
  if (s.contains("replay")) {
    std::ifstream f(wide(s.at("replay")));
    if (!f)
      throw failure(3, "Replay file not found");
    f >> replay_;
    if (replay_.is_object()) {
      auto spec = replay_;
      repeat_frame_ = unhex(spec.at("repeat_rx"));
      repeat_period_ = spec.value("period_ms", 10u);
      advance_tick_ = spec.value("advance_tick_100us", false);
      if (repeat_period_ == 0)
        throw failure(2, "Replay period must be positive");
      replay_ = spec.at("steps");
      repeat_due_ = std::chrono::steady_clock::now();
    }
    replay_index_ = 0;
    endpoint = "replay:" + s.at("replay").get<std::string>();
    return;
  }
  auto kind = s.value("transport", std::string("serial"));
  if (kind == "tcp") {
    auto host = s.value("host", std::string());
    auto port = s.value("tcp_port", 9000u);
    tcp_.open(host, port, guard);
    endpoint = "tcp://" + (host.find(':') == std::string::npos ? host : "["+host+"]") + ":" + std::to_string(port);
    return;
  }
  if (kind != "serial") throw failure(2, "Transport must be serial or tcp");
  auto port = s.value("port", std::string());
  if (port.empty())
    throw failure(2, "--port is required");
  auto path = wide("\\\\.\\" + port);
  handle_ = CreateFileW(path.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                        OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
  if (handle_ == INVALID_HANDLE_VALUE)
    throw failure(3, "Cannot open " + port + " (Win32 " +
                         std::to_string(GetLastError()) + ")");
  try {
    DCB d{};
    d.DCBlength = sizeof(d);
    wincheck(GetCommState(handle_, &d), "GetCommState");
    d.BaudRate = s.value("baud", 115200u);
    d.ByteSize = static_cast<BYTE>(s.value("data_bits", 8));
    d.Parity = NOPARITY;
    auto parity = s.value("parity", std::string("none"));
    if (parity == "even")
      d.Parity = EVENPARITY;
    else if (parity == "odd")
      d.Parity = ODDPARITY;
    else if (parity != "none")
      throw failure(2, "Invalid parity");
    d.fParity = d.Parity != NOPARITY;
    d.StopBits = s.value("stop_bits", 1) == 2 ? TWOSTOPBITS : ONESTOPBIT;
    d.fBinary = TRUE;
    d.fOutxCtsFlow = FALSE;
    d.fOutxDsrFlow = FALSE;
    d.fDtrControl = DTR_CONTROL_DISABLE;
    d.fRtsControl = RTS_CONTROL_DISABLE;
    d.fOutX = FALSE;
    d.fInX = FALSE;
    wincheck(SetCommState(handle_, &d), "SetCommState");
    wincheck(GetCommState(handle_, &d), "GetCommState");
    baud_rate = d.BaudRate;
    COMMTIMEOUTS t{};
    t.ReadIntervalTimeout = MAXDWORD;
    t.ReadTotalTimeoutConstant = 5;
    t.WriteTotalTimeoutConstant = 500;
    wincheck(SetCommTimeouts(handle_, &t), "SetCommTimeouts");
    PurgeComm(handle_, PURGE_RXCLEAR | PURGE_TXCLEAR);
    endpoint = port;
  } catch (...) {
    close();
    throw;
  }
}
unsigned transport::set_baud(unsigned baud) {
  if (baud == 0 || baud > 12000000) throw failure(2, "Baud must be in 1..12000000");
  if (handle_ == INVALID_HANDLE_VALUE) throw failure(3, "An open physical serial port is required");
  DCB previous{}; previous.DCBlength = sizeof(previous);
  wincheck(GetCommState(handle_, &previous), "GetCommState");
  DCB changed = previous; changed.BaudRate = baud;
  wincheck(SetCommState(handle_, &changed), "SetCommState baud");
  if (!GetCommState(handle_, &changed) || changed.BaudRate != baud) {
    if (!SetCommState(handle_, &previous)) close();
    throw failure(3, "Serial driver did not confirm requested baud rate");
  }
  baud_rate = changed.BaudRate;
  return baud_rate;
}
void transport::write(const bytes &b) {
  if (!opened())
    throw failure(3, "Device connection is closed");
  if (recording_.is_open()) {
    recording_ << json{{"tx", hex(b)}}.dump() << "\n";
    recording_.flush();
  }
  if (tcp_.opened()) { tcp_.write(b); return; }
  if (!replay_.is_null()) {
    if (replay_index_ >= replay_.size())
      throw failure(5, "Replay exhausted");
    auto step = replay_.at(replay_index_++);
    if (step.contains("tx") && unhex(step.at("tx")) != b)
      throw failure(5, "Replay TX mismatch at step " +
                           std::to_string(replay_index_));
    for (auto &block : step.at("rx"))
      replay_rx_.push_back(unhex(block));
    return;
  }
  std::size_t pos = 0;
  while (pos < b.size()) {
    OVERLAPPED ov{};
    ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!ov.hEvent)
      throw failure(3, "CreateEvent failed");
    DWORD n = 0;
    BOOL ok = WriteFile(handle_, b.data() + pos,
                        static_cast<DWORD>(b.size() - pos), &n, &ov);
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
      if (WaitForSingleObject(ov.hEvent, 1000) != WAIT_OBJECT_0) {
        CancelIoEx(handle_, &ov);
        GetOverlappedResult(handle_, &ov, &n, TRUE);
        CloseHandle(ov.hEvent);
        throw failure(4, "Serial write timeout; outcome unknown");
      }
      ok = GetOverlappedResult(handle_, &ov, &n, FALSE);
    }
    DWORD err = GetLastError();
    CloseHandle(ov.hEvent);
    if (!ok || n == 0)
      throw failure(3, "Serial write failed " + std::to_string(err));
    pos += n;
  }
}
bytes transport::read(unsigned timeout) {
  if (!opened())
    return {};
  if (tcp_.opened()) {
    auto b=tcp_.read(timeout);
    if (recording_.is_open() && !b.empty()) { recording_ << json{{"rx",hex(b)}}.dump() << "\n"; recording_.flush(); }
    return b;
  }
  if (!replay_.is_null()) {
    if (replay_rx_.empty()) {
      if (!repeat_frame_.empty() && replay_index_ == 2 &&
          std::chrono::steady_clock::now() >= repeat_due_) {
        repeat_due_ += std::chrono::milliseconds(repeat_period_);
        auto result = repeat_frame_;
        if (advance_tick_) {
          reader r(repeat_frame_);
          if (r.u8(7) != 0x40)
            throw failure(2, "Tick advancement requires a wave batch");
          auto tick = r.u32(11) + repeat_period_ * 10;
          for (unsigned i = 0; i < 4; ++i)
            repeat_frame_[11 + i] = static_cast<std::uint8_t>(tick >> (i * 8));
          auto end = 11 + r.u16(9);
          auto check = crc(std::span(repeat_frame_).first(end));
          repeat_frame_[end] = static_cast<std::uint8_t>(check);
          repeat_frame_[end + 1] = static_cast<std::uint8_t>(check >> 8);
        }
        return result;
      }
      Sleep(timeout);
      return {};
    }
    auto b = std::move(replay_rx_.front());
    replay_rx_.pop_front();
    return b;
  }
  bytes b(16384);
  OVERLAPPED ov{};
  ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  if (!ov.hEvent)
    throw failure(3, "CreateEvent failed");
  DWORD n = 0;
  BOOL ok = ReadFile(handle_, b.data(), static_cast<DWORD>(b.size()), &n, &ov);
  if (!ok && GetLastError() == ERROR_IO_PENDING) {
    auto wait = WaitForSingleObject(ov.hEvent, std::max(timeout, 50u));
    if (wait == WAIT_TIMEOUT) {
      CancelIoEx(handle_, &ov);
      ok = GetOverlappedResult(handle_, &ov, &n, TRUE);
      if (!ok && GetLastError() == ERROR_OPERATION_ABORTED) {
        CloseHandle(ov.hEvent);
        return {};
      }
    } else
      ok = GetOverlappedResult(handle_, &ov, &n, TRUE);
  }
  DWORD error = GetLastError();
  CloseHandle(ov.hEvent);
  if (!ok)
    throw failure(3, "Serial read failed " + std::to_string(error));
  b.resize(n);
  if (recording_.is_open() && !b.empty()) {
    recording_ << json{{"rx", hex(b)}}.dump() << "\n";
    recording_.flush();
  }
  return b;
}
json transport::ports() {
  // Match the actual PortName property; friendly names can be localized and
  // must never be parsed to obtain the COM endpoint.
  std::map<std::wstring, std::string> descriptions;
  struct device_list {
    HDEVINFO value = SetupDiGetClassDevsW(nullptr, nullptr, nullptr,
                                         DIGCF_PRESENT | DIGCF_ALLCLASSES);
    ~device_list() { if (value != INVALID_HANDLE_VALUE) SetupDiDestroyDeviceInfoList(value); }
  } devices;
  if (devices.value != INVALID_HANDLE_VALUE) {
    SP_DEVINFO_DATA device{};
    device.cbSize = sizeof(device);
    for (DWORD i = 0; SetupDiEnumDeviceInfo(devices.value, i, &device); ++i) {
      HKEY device_key = SetupDiOpenDevRegKey(devices.value, &device, DICS_FLAG_GLOBAL,
                                             0, DIREG_DEV, KEY_QUERY_VALUE);
      if (device_key == INVALID_HANDLE_VALUE) continue;
      wchar_t port[256]{};
      DWORD size = sizeof(port);
      auto result = RegGetValueW(device_key, nullptr, L"PortName", RRF_RT_REG_SZ,
                                 nullptr, port, &size);
      RegCloseKey(device_key);
      if (result != ERROR_SUCCESS || port[0] == 0) continue;
      for (DWORD property : {DWORD(SPDRP_FRIENDLYNAME), DWORD(SPDRP_DEVICEDESC)}) {
        DWORD required = 0, type = 0;
        SetupDiGetDeviceRegistryPropertyW(devices.value, &device, property,
                                          &type, nullptr, 0, &required);
        if (required == 0 || required > 65536) continue;
        std::vector<wchar_t> name(required / sizeof(wchar_t) + 1, 0);
        if (!SetupDiGetDeviceRegistryPropertyW(devices.value, &device, property,
              &type, reinterpret_cast<BYTE *>(name.data()), required, nullptr) || type != REG_SZ)
          continue;
        int length = WideCharToMultiByte(CP_UTF8, 0, name.data(), -1, nullptr, 0, nullptr, nullptr);
        if (length <= 1) continue;
        std::string utf8(length, 0);
        WideCharToMultiByte(CP_UTF8, 0, name.data(), -1, utf8.data(), length, nullptr, nullptr);
        utf8.pop_back();
        descriptions[port] = std::move(utf8);
        break;
      }
    }
  }
  json out = json::array();
  HKEY key{};
  if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"HARDWARE\\DEVICEMAP\\SERIALCOMM", 0,
                    KEY_READ, &key) != ERROR_SUCCESS)
    return out;
  for (DWORD i = 0;; ++i) {
    wchar_t name[512], data[512];
    DWORD nl = 512, dl = sizeof(data), type = 0;
    auto e = RegEnumValueW(key, i, name, &nl, nullptr, &type,
                           reinterpret_cast<BYTE *>(data), &dl);
    if (e == ERROR_NO_MORE_ITEMS)
      break;
    if (e == ERROR_SUCCESS && type == REG_SZ) {
      std::wstring w(data);
      out.push_back({{"port", std::string(w.begin(), w.end())},
                     {"description", descriptions.contains(w) ? descriptions.at(w) : ""}});
    }
  }
  RegCloseKey(key);
  return out;
}
} // namespace frame
