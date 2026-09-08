// SPDX-License-Identifier: MIT
#include <WinSock2.h>
#include <WS2tcpip.h>
#include "tcp_transport.hpp"
#include <algorithm>
#include <chrono>
namespace frame {
static void socket_error(const char *action) {
  throw failure(3, std::string(action) + " (Winsock " + std::to_string(WSAGetLastError()) + ")");
}
static bool ready(SOCKET socket, bool write, unsigned milliseconds) {
  fd_set set; FD_ZERO(&set); FD_SET(socket, &set);
  timeval timeout{static_cast<long>(milliseconds / 1000), static_cast<long>((milliseconds % 1000) * 1000)};
  int result = select(0, write ? nullptr : &set, write ? &set : nullptr, nullptr, &timeout);
  if (result == SOCKET_ERROR) socket_error("TCP select failed");
  return result != 0;
}
void tcp_transport::close() {
  if (opened()) { closesocket(static_cast<SOCKET>(socket_)); socket_ = ~std::uintptr_t(0); }
  if (started_) { WSACleanup(); started_ = false; }
}
void tcp_transport::open(const std::string &address, unsigned port, const std::function<void()> &guard) {
  if (port == 0 || port > 65535) throw failure(2, "TCP port outside 1..65535");
  close();
  WSADATA data{};
  if (WSAStartup(MAKEWORD(2,2), &data) != 0) throw failure(3, "Winsock initialization failed");
  started_ = true;
  try {
    sockaddr_storage storage{};
    auto &ipv4 = reinterpret_cast<sockaddr_in &>(storage);
    auto &ipv6 = reinterpret_cast<sockaddr_in6 &>(storage);
    int length = 0;
    if (InetPtonA(AF_INET, address.c_str(), &ipv4.sin_addr) == 1) {
      ipv4.sin_family = AF_INET; ipv4.sin_port = htons(static_cast<u_short>(port)); length = sizeof(ipv4);
    } else if (InetPtonA(AF_INET6, address.c_str(), &ipv6.sin6_addr) == 1) {
      ipv6.sin6_family = AF_INET6; ipv6.sin6_port = htons(static_cast<u_short>(port)); length = sizeof(ipv6);
    } else throw failure(2, "Enter a numeric IPv4 or IPv6 address");
    auto socket = ::socket(storage.ss_family, SOCK_STREAM, IPPROTO_TCP);
    if (socket == INVALID_SOCKET) socket_error("Cannot create TCP socket");
    socket_ = socket;
    u_long nonblocking = 1;
    if (ioctlsocket(socket, FIONBIO, &nonblocking) != 0) socket_error("Cannot enable nonblocking TCP");
    int no_delay = 1;
    if (setsockopt(socket, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char *>(&no_delay), sizeof(no_delay)) != 0) socket_error("Cannot set TCP_NODELAY");
    if (guard) guard();
    if (::connect(socket, reinterpret_cast<sockaddr *>(&storage), length) == SOCKET_ERROR) {
      if (WSAGetLastError() != WSAEWOULDBLOCK) socket_error("TCP connection failed");
      auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
      while (true) {
        if (guard) guard();
        if (std::chrono::steady_clock::now() >= deadline) throw failure(4, "TCP connection timed out");
        fd_set writable, errors; FD_ZERO(&writable); FD_ZERO(&errors); FD_SET(socket,&writable); FD_SET(socket,&errors);
        timeval timeout{0,20000};
        int selected = select(0,nullptr,&writable,&errors,&timeout);
        if (selected == SOCKET_ERROR) socket_error("TCP connect wait failed");
        if (selected) {
          int error=0, size=sizeof(error);
          if (getsockopt(socket,SOL_SOCKET,SO_ERROR,reinterpret_cast<char *>(&error),&size) != 0) socket_error("Cannot query TCP status");
          if (error) throw failure(3,"TCP connection failed (Winsock " + std::to_string(error) + ")");
          break;
        }
      }
    }
  } catch (...) { close(); throw; }
}
void tcp_transport::write(const bytes &data) {
  auto socket = static_cast<SOCKET>(socket_);
  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(1);
  std::size_t offset=0;
  while (offset < data.size()) {
    if (std::chrono::steady_clock::now() >= deadline) throw failure(4,"TCP write timed out; remote outcome unknown");
    if (!ready(socket,true,20)) continue;
    int sent=send(socket,reinterpret_cast<const char *>(data.data()+offset),static_cast<int>(std::min<std::size_t>(data.size()-offset,65536)),0);
    if (sent == SOCKET_ERROR && WSAGetLastError() == WSAEWOULDBLOCK) continue;
    if (sent <= 0) socket_error("TCP send failed");
    offset += sent;
  }
}
bytes tcp_transport::read(unsigned timeout_ms) {
  auto socket = static_cast<SOCKET>(socket_);
  if (!ready(socket,false,timeout_ms)) return {};
  bytes data(16384);
  int received=recv(socket,reinterpret_cast<char *>(data.data()),static_cast<int>(data.size()),0);
  if (received == SOCKET_ERROR && WSAGetLastError() == WSAEWOULDBLOCK) return {};
  if (received == SOCKET_ERROR) socket_error("TCP receive failed");
  if (received == 0) throw failure(3,"Remote TCP endpoint closed the connection");
  data.resize(received); return data;
}
}
