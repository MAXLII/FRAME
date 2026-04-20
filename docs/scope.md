# Scope Protocol Draft

## Goal

This document defines a draft protocol for the software scope feature.

Design targets:

- Keep the core scope sampling logic in [code/dbg/scope.c](D:/OneDrive/LWX/FRAME/code/dbg/scope.c) unchanged.
- Use `cmd_set = 0x01` because `0x02` is reserved by the LLC side.
- Store only one scope capture in device RAM.
- Minimize serial bandwidth usage.
- Read one sample time point per transfer by default.
- Support both safe read and force read.
- Allow the desktop app to keep multiple pulled captures locally and separate them visually.

## Existing Scope Notes

Based on [code/dbg/scope.h](D:/OneDrive/LWX/FRAME/code/dbg/scope.h) and [code/dbg/scope.c](D:/OneDrive/LWX/FRAME/code/dbg/scope.c):

- Scope data is stored as `float`.
- Buffer layout is var-major:
  - `buffer[var_index * buffer_size + sample_index]`
- Triggered capture already exists in RAM.
- `trigger_index`, `buffer_size`, `trigger_post_cnt`, `var_count`, and `var_names` are already available.
- The current control sampling period should come from `CTRL_TS` in [code/section/my_math.h](D:/OneDrive/LWX/FRAME/code/section/my_math.h).

Recommended exported sampling period:

```c
sample_period_us = (uint32_t)(CTRL_TS * 1000000.0f + 0.5f);
```

For the current codebase:

- `CTRL_FREQ = 30 kHz`
- `CTRL_TS = 1 / 30000`
- `sample_period_us` is about `33`

If higher precision is needed later, the protocol can add `sample_period_ns` or a rational pair `{num, den}`. First version should keep `uint32_t sample_period_us`.

## Command Set And Command Words

Use `cmd_set = 0x01`.

Current command words already used:

- `0x0E ~ 0x11`: Black Box
- `0x12 ~ 0x13`: Factory Time
- `0x14 ~ 0x16`: Calibration

Recommended `scope` command range:

- `0x18 ~ 0x1F`

Note:

- `0x17` is already used by firmware version query in the current project, so Scope must start from `0x18`

## Protocol Principles

1. All payloads use little-endian.
2. Scope metadata and sample data are separated.
3. Variable names are uploaded one item at a time.
4. Sample data is pulled one sample index at a time in the first version.
5. Desktop app uses logical sample order, not raw ring-buffer order.
6. Normal read must reject running captures.
7. Force read may read while running, but consistency is not guaranteed.
8. Device keeps only one RAM capture. The desktop app may keep multiple local captures.

## Logical Sample Order

Desktop should not care about the ring-buffer physical layout.

The device should convert `sample_index` in protocol space into the actual RAM index internally.

Recommended logical order:

- `sample_index = 0` means the leftmost point of the capture window.
- `sample_index = trigger_display_index` means the trigger point.
- `sample_index = sample_count - 1` means the rightmost point.

Recommended exported trigger display index:

```c
trigger_display_index = buffer_size - trigger_post_cnt - 1;
```

This is the index the desktop app should use to draw the trigger vertical line.

## Scope State

```c
typedef enum
{
    SCOPE_TOOL_STATE_IDLE = 0,
    SCOPE_TOOL_STATE_RUNNING = 1,
    SCOPE_TOOL_STATE_TRIGGERED = 2,
} scope_tool_state_e;
```

This maps directly to the current scope runtime state.

## Sample Read Mode

```c
typedef enum
{
    SCOPE_READ_MODE_NORMAL = 0,
    SCOPE_READ_MODE_FORCE = 1,
} scope_read_mode_e;
```

- `NORMAL`: reject read if scope is still running
- `FORCE`: allow read even when running

## Response Status

```c
typedef enum
{
    SCOPE_TOOL_STATUS_OK = 0,
    SCOPE_TOOL_STATUS_SCOPE_ID_INVALID = 1,
    SCOPE_TOOL_STATUS_VAR_INDEX_INVALID = 2,
    SCOPE_TOOL_STATUS_SAMPLE_INDEX_INVALID = 3,
    SCOPE_TOOL_STATUS_RUNNING_DENIED = 4,
    SCOPE_TOOL_STATUS_DATA_NOT_READY = 5,
    SCOPE_TOOL_STATUS_BUSY = 6,
    SCOPE_TOOL_STATUS_CAPTURE_CHANGED = 7,
} scope_tool_status_e;
```

Notes:

- `RUNNING_DENIED`: returned on normal read when scope is still running
- `DATA_NOT_READY`: no completed capture exists yet
- `CAPTURE_CHANGED`: force read started on one capture tag, but the capture changed before the current response was prepared

## Capture Tag

Because only one RAM copy exists, the protocol should expose a lightweight tag to tell the desktop app whether the capture changed.

Recommended field:

```c
uint32_t capture_tag;
```

Recommended behavior:

- Increment on every new `START`
- Optionally increment again when a triggered capture finishes
- Return it in `INFO_ACK` and `SAMPLE_ACK`

Desktop app usage:

- Cache `capture_tag` when pulling starts
- If later responses contain a different tag, mark the capture as changed

## Data Type

The current scope buffer stores only `float`. First version should send raw `float` values directly.

No type field is needed in the first version.

## Structure Draft

All transport structures below are payload structures only.

### 1. Scope List Query

Desktop app asks which scope objects are available.

Command:

- `cmd_set = 0x01`
- `cmd_word = 0x18`

Query payload:

```c
typedef struct
{
    uint8_t reserved;
} scope_list_query_t;
```

Response item payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t is_last;
    uint8_t name_len;
    uint8_t reserved;
    /* followed by: char name[name_len] */
} scope_list_item_t;
```

Notes:

- One scope per response frame
- Last frame sets `is_last = 1`

### 2. Scope Info Query

Desktop app asks for state and metadata of one scope.

Command:

- `cmd_set = 0x01`
- `cmd_word = 0x19`

Query payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t reserved[3];
} scope_info_query_t;
```

Response payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t state;
    uint8_t data_ready;
    uint8_t var_count;
    uint8_t reserved0[3];
    uint32_t sample_count;
    uint32_t write_index;
    uint32_t trigger_index;
    uint32_t trigger_post_cnt;
    uint32_t trigger_display_index;
    uint32_t sample_period_us;
    uint32_t capture_tag;
} scope_info_ack_t;
```

Field meanings:

- `sample_count`: normally equals `buffer_size`
- `write_index`: current physical ring write index
- `trigger_index`: physical trigger index in ring buffer
- `trigger_display_index`: logical trigger position for plotting
- `sample_period_us`: exported from `CTRL_TS`
- `data_ready`: whether a completed capture is available for normal read

### 3. Scope Variable Name Query

Desktop app reads variable names one by one.

Command:

- `cmd_set = 0x01`
- `cmd_word = 0x1A`

Query payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t var_index;
    uint8_t reserved[2];
} scope_var_query_t;
```

Response payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t var_index;
    uint8_t is_last;
    uint8_t name_len;
    uint8_t reserved[3];
    /* followed by: char name[name_len] */
} scope_var_ack_t;
```

### 4. Scope Start

Command:

- `cmd_set = 0x01`
- `cmd_word = 0x1B`

Query payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t reserved[3];
} scope_start_cmd_t;
```

Response payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t state;
    uint8_t data_ready;
    uint32_t capture_tag;
} scope_start_ack_t;
```

Recommended behavior:

- Call `scope_start()`
- Mark previous completed capture as replaced
- Increase `capture_tag`
- `data_ready = 0`

### 5. Scope Trigger

Command:

- `cmd_set = 0x01`
- `cmd_word = 0x1C`

Query payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t reserved[3];
} scope_trigger_cmd_t;
```

Response payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t state;
    uint8_t reserved;
    uint32_t capture_tag;
} scope_trigger_ack_t;
```

Recommended behavior:

- Call `scope_trigger()`

### 6. Scope Stop

Command:

- `cmd_set = 0x01`
- `cmd_word = 0x1D`

Query payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t reserved[3];
} scope_stop_cmd_t;
```

Response payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t state;
    uint8_t data_ready;
    uint32_t capture_tag;
} scope_stop_ack_t;
```

Recommended behavior:

- Call `scope_stop()`
- If user wants, the stopped RAM content may still be readable

### 7. Scope Reset

Command:

- `cmd_set = 0x01`
- `cmd_word = 0x1E`

Query payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t reserved[3];
} scope_reset_cmd_t;
```

Response payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t state;
    uint8_t data_ready;
    uint32_t capture_tag;
} scope_reset_ack_t;
```

Recommended behavior:

- Call `scope_reset()`
- Clear `data_ready`
- Keep RAM contents undefined from protocol point of view

### 8. Scope Sample Query

This is the main data transfer command.

One request reads one logical sample point, containing all variables at that point.

Command:

- `cmd_set = 0x01`
- `cmd_word = 0x1F`

Query payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t read_mode;
    uint8_t reserved[2];
    uint32_t sample_index;
    uint32_t expected_capture_tag;
} scope_sample_query_t;
```

Response header payload:

```c
typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t read_mode;
    uint8_t var_count;
    uint32_t sample_index;
    uint32_t capture_tag;
    uint8_t is_last_sample;
    uint8_t reserved[3];
    /* followed by: float values[var_count] */
} scope_sample_ack_t;
```

Rules:

- If `read_mode == NORMAL` and scope is running:
  - return `RUNNING_DENIED`
- If `read_mode == NORMAL` and no completed capture exists:
  - return `DATA_NOT_READY`
- If `sample_index >= sample_count`:
  - return `SAMPLE_INDEX_INVALID`
- If `expected_capture_tag != 0` and current tag changed:
  - may return `CAPTURE_CHANGED`
- On success:
  - append `float[var_count]`

### 9. Optional Scope Status Poll

If later needed, one more lightweight status polling command can be added.

Reserved recommendation:

- `cmd_set = 0x01`
- reserve the next free command word after `0x1F`

This is optional in first version because `INFO_QUERY` already covers status.

## Internal Index Conversion

The device should convert the incoming logical `sample_index` into the actual ring buffer index.

Recommended helper idea:

```c
static uint32_t scope_logical_to_physical_index(scope_t *scope, uint32_t logical_index)
{
    uint32_t start_index = (scope->trigger_index + scope->trigger_post_cnt + 1u) % scope->buffer_size;
    return (start_index + logical_index) % scope->buffer_size;
}
```

This matches the current staged print logic in `scope_printf_data_start()`.

## Desktop App Behavior

Recommended desktop workflow:

1. Query scope list
2. Select one scope
3. Query info
4. Query all variable names
5. User clicks:
   - Start
   - Trigger
   - Stop
   - Reset
   - Pull capture
6. For pull capture:
   - Query info first
   - Cache `capture_tag`
   - Pull `sample_index = 0 ... sample_count - 1`
   - Pull one sample per scheduler turn, not in a tight blocking loop
7. Plot locally after enough samples are collected

Recommended plotting behavior:

- Each pulled capture becomes one local capture object
- The desktop app may keep multiple local captures even though the device only holds one RAM capture
- Draw a gap between local captures
- Draw a vertical trigger line at `trigger_display_index`

## Safe Read And Force Read

### Normal Read

Use when user wants a stable completed capture.

Expected behavior:

- Running scope cannot be read
- Response returns `RUNNING_DENIED`

### Force Read

Use when user wants to inspect the RAM buffer even while scope is still active.

Expected behavior:

- Read is allowed
- Data may be inconsistent across different samples
- Desktop app should mark the capture as force-read
- Desktop app should watch `capture_tag` for changes

## Bandwidth Scheduling Recommendation

Because serial bandwidth is limited, the desktop app should not monopolize the link.

Recommended strategy:

- Pull one sample request at a time
- Wait for ACK before sending the next one
- Use a paced scheduler
- Allow other parameter and control traffic to interleave

Example scheduler policy:

- At most one scope sample request per UI polling cycle
- Or one request every `10 ~ 20 ms`

This keeps the scope upload bandwidth low and predictable.

## First Version Implementation Scope

Recommended first version:

- Scope list query
- Scope info query
- Variable name query
- Start
- Trigger
- Stop
- Reset
- Single-sample query

Not required in first version:

- Multi-sample chunk read
- Trigger condition configuration over protocol
- Flash persistence
- Per-sample timestamp
- Mixed data types

## Notes For Future Expansion

If bandwidth later allows, a chunk mode can be added without breaking the first version.

Possible future command:

- `SCOPE_SAMPLE_BLOCK_QUERY`

That command could return several logical samples in one frame, while reusing the same metadata rules defined here.
