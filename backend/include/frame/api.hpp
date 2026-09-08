// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>
#ifdef FRAME_EXPORTS
#define FRAME_API __declspec(dllexport)
#else
#define FRAME_API __declspec(dllimport)
#endif
// ABI 1: explicit UTF-8 lengths, opaque ownership, asynchronous command
// envelopes. JSON is the application command/result format, never the device
// wire format. All copies are non-destructive. Caller releases operations after
// consuming results.
extern "C" {
FRAME_API std::uint32_t __cdecl frame_abi_version() noexcept;
FRAME_API void *__cdecl frame_create() noexcept;
FRAME_API void __cdecl frame_destroy(void *handle) noexcept;
FRAME_API std::int32_t __cdecl frame_submit(void *handle, const char *utf8,
                                            std::uint32_t length,
                                            std::uint64_t *id) noexcept;
FRAME_API std::int32_t __cdecl frame_result(void *handle, std::uint64_t id,
                                            char *buffer,
                                            std::uint32_t capacity,
                                            std::uint32_t *required) noexcept;
FRAME_API std::int32_t __cdecl frame_cancel(void *handle,
                                            std::uint64_t id) noexcept;
FRAME_API std::int32_t __cdecl frame_release(void *handle,
                                             std::uint64_t id) noexcept;
FRAME_API std::int32_t __cdecl frame_snapshot(void *handle, char *buffer,
                                              std::uint32_t capacity,
                                              std::uint32_t *required) noexcept;
// Non-destructive cursor-based batch; the response reports ring-buffer loss.
FRAME_API std::int32_t __cdecl frame_events(void *handle, std::uint64_t after,
                                            std::uint32_t limit, char *buffer,
                                            std::uint32_t capacity,
                                            std::uint32_t *required) noexcept;
}
