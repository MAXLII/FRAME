// SPDX-License-Identifier: MIT
#include "frame/api.hpp"
#include "runtime.hpp"
#include <cstring>
static int copy_text(const std::string &s, char *buffer, std::uint32_t cap,
                     std::uint32_t *needed) {
  if (!needed)
    return -1;
  *needed = static_cast<std::uint32_t>(s.size());
  if (cap < s.size())
    return 2;
  if (!s.empty() && !buffer)
    return -1;
  if (!s.empty())
    std::memcpy(buffer, s.data(), s.size());
  return 0;
}
extern "C" {
std::uint32_t __cdecl frame_abi_version() noexcept { return 0x00010000; }
void *__cdecl frame_create() noexcept {
  try {
    return new frame::runtime();
  } catch (...) {
    return nullptr;
  }
}
void __cdecl frame_destroy(void *h) noexcept {
  try {
    delete static_cast<frame::runtime *>(h);
  } catch (...) {
  }
}
std::int32_t __cdecl frame_submit(void *h, const char *text, std::uint32_t n,
                                  std::uint64_t *id) noexcept {
  try {
    if (!h || !text || !id || n > 1024 * 1024)
      return -1;
    *id = static_cast<frame::runtime *>(h)->submit(
        frame::json::parse(text, text + n));
    return 0;
  } catch (const frame::failure &e) {
    return -e.code;
  } catch (...) {
    return -2;
  }
}
std::int32_t __cdecl frame_result(void *h, std::uint64_t id, char *b,
                                  std::uint32_t c, std::uint32_t *n) noexcept {
  try {
    if (!h)
      return -1;
    std::string s;
    int status = static_cast<frame::runtime *>(h)->result(id, s);
    return status ? status : copy_text(s, b, c, n);
  } catch (...) {
    return -1;
  }
}
std::int32_t __cdecl frame_cancel(void *h, std::uint64_t id) noexcept {
  try {
    return h ? static_cast<frame::runtime *>(h)->cancel(id) : -1;
  } catch (...) {
    return -1;
  }
}
std::int32_t __cdecl frame_release(void *h, std::uint64_t id) noexcept {
  try {
    return h ? static_cast<frame::runtime *>(h)->release(id) : -1;
  } catch (...) {
    return -1;
  }
}
std::int32_t __cdecl frame_snapshot(void *h, char *b, std::uint32_t c,
                                    std::uint32_t *n) noexcept {
  try {
    return h ? copy_text(static_cast<frame::runtime *>(h)->snapshot(), b, c, n)
             : -1;
  } catch (...) {
    return -1;
  }
}
std::int32_t __cdecl frame_events(void *h, std::uint64_t after,
                                  std::uint32_t limit, char *b, std::uint32_t c,
                                  std::uint32_t *n) noexcept {
  try {
    return h ? copy_text(static_cast<frame::runtime *>(h)->events(after, limit),
                         b, c, n)
             : -1;
  } catch (...) {
    return -1;
  }
}
}
