# Scope Desktop Design

## Goal

This document defines the desktop-side design for the software scope feature, based on [scope.md](D:/OneDrive/LWX/FRAME/scope.md).

Design targets:

- Add a dedicated `Scope` page to the full desktop application
- Do not include this feature in Lite mode
- Reuse the existing serial protocol framework in the desktop app
- Keep serial bandwidth usage low
- Support both normal pull and force pull
- Support multiple local captures in the desktop app
- Visually separate different captures with gaps and vertical lines

## Fit With Current Desktop Architecture

Current desktop app structure already has good extension points:

- Main UI and protocol dispatch are in [serial_debug_assistant/ui/app.py](D:/OneDrive/LWX/FRAME/serial_debug_assistant/ui/app.py)
- Shared protocol framing is in [serial_debug_assistant/protocol.py](D:/OneDrive/LWX/FRAME/serial_debug_assistant/protocol.py)
- Shared data models are in [serial_debug_assistant/models.py](D:/OneDrive/LWX/FRAME/serial_debug_assistant/models.py)
- Existing high-interaction plotting UI is in [serial_debug_assistant/ui/wave_tab.py](D:/OneDrive/LWX/FRAME/serial_debug_assistant/ui/wave_tab.py)

Recommended integration:

- Add a new protocol helper module:
  - `serial_debug_assistant/scope_protocol.py`
- Add new desktop data models:
  - extend `serial_debug_assistant/models.py`
- Add a new UI page:
  - `serial_debug_assistant/ui/scope_tab.py`
- Extend the main app:
  - add `ScopeTab` into `SerialDebugAssistant`
  - add a `_handle_scope_protocol_frame()` dispatcher
  - add a low-priority pull scheduler

## Why Not Reuse WaveTab Directly

`WaveTab` is built for live subscription streaming:

- selected parameters are dynamic
- x-axis is real-time timestamp based
- incoming samples append continuously

Scope capture is different:

- variables are fixed by the selected scope object
- one pull reads a finite capture buffer
- the desktop app may hold multiple captures locally
- capture boundaries and trigger lines matter

So the right approach is:

- reuse plotting ideas from `WaveTab`
- do not force the Scope feature into `WaveTab`

## Recommended New Files

### 1. `serial_debug_assistant/scope_protocol.py`

Purpose:

- define `cmd_set/cmd_word`
- build payloads for scope commands
- parse scope payloads
- decode `float[var_count]`

Recommended contents:

- command constants
- status constants
- small `build_*` helpers
- `parse_scope_list_item_payload`
- `parse_scope_info_ack_payload`
- `parse_scope_var_ack_payload`
- `parse_scope_sample_ack_payload`

### 2. `serial_debug_assistant/ui/scope_tab.py`

Purpose:

- all Scope page UI
- selected scope info
- pull progress
- capture list
- plotting
- export

### 3. `serial_debug_assistant/models.py`

Add new models for scope metadata and local captures.

## Recommended Desktop Data Models

### Scope object summary

```python
@dataclass(slots=True)
class ScopeListItem:
    scope_id: int
    name: str
```

### Runtime scope info

```python
@dataclass(slots=True)
class ScopeInfo:
    scope_id: int
    status: int
    state: int
    data_ready: bool
    var_count: int
    sample_count: int
    write_index: int
    trigger_index: int
    trigger_post_cnt: int
    trigger_display_index: int
    sample_period_us: int
    capture_tag: int
```

### Local pulled capture

```python
@dataclass(slots=True)
class ScopeCapture:
    scope_id: int
    scope_name: str
    capture_tag: int
    read_mode: int
    sample_period_us: int
    sample_count: int
    trigger_display_index: int
    var_names: list[str]
    samples: list[list[float]]
    capture_index: int
    capture_changed_during_pull: bool = False
```

### Pull session

```python
@dataclass(slots=True)
class ScopePullSession:
    scope_id: int
    scope_name: str
    read_mode: int
    expected_capture_tag: int
    sample_count: int
    next_sample_index: int = 0
    waiting_ack: bool = False
    completed: bool = False
    failed: bool = False
    fail_reason: str = ""
    samples: list[list[float]] | None = None
```

## Main App State Additions

Recommended new members inside `SerialDebugAssistant.__init__()`:

```python
self.scope_items: list[ScopeListItem] = []
self.scope_info_by_id: dict[int, ScopeInfo] = {}
self.scope_var_names_by_id: dict[int, list[str]] = {}
self.scope_captures: list[ScopeCapture] = []
self.scope_pull_session: ScopePullSession | None = None
self.scope_request_queue: list[bytes] = []
self.scope_next_capture_index = 1
self.scope_scheduler_job: str | None = None
```

## ScopeTab UI Layout

Recommended page layout:

### Top row: selection and status

- scope dropdown
- refresh scope list button
- refresh info button
- current status label
- current `capture_tag`

### Control row

- start
- trigger
- stop
- reset
- normal pull
- force pull
- clear local captures

### Info panel

Show:

- scope name
- variable count
- sample count
- sample period
- trigger display index
- device state
- data ready

### Plot area

Main chart area:

- multiple series lines
- multiple captures allowed
- capture gap between captures
- trigger vertical line in each capture
- capture boundary vertical line at each capture start

### Right panel

- variable visibility checkboxes
- local capture list
- pull progress
- warning box

### Bottom row

- export CSV
- export JSON if needed later
- clear current selection

## Display Model

The desktop app should keep pulled captures locally even though the device stores only one RAM capture.

Recommended plotting arrangement:

- Each capture is laid out on the same X axis with a gap
- Gap width can be fixed in sample points, for example `gap = 10`
- At the start of each capture, draw a light gray vertical boundary line
- At each capture's `trigger_display_index`, draw a red vertical trigger line

This directly addresses the user's request to separate different captures without forcing a clear.

## X Axis Strategy

Recommended internal x-axis for plotting:

- unit: milliseconds
- time origin per capture:
  - trigger point is `t = 0`
  - points before trigger are negative
  - points after trigger are positive

Formula:

```python
time_ms = (sample_index - trigger_display_index) * sample_period_us / 1000.0
```

When multiple captures are displayed together:

- do not merge them by absolute time
- instead place them sequentially with a fixed visual gap

This makes comparison easier and avoids fake real-time meaning.

## Capture Plot Preparation

When one pull session completes:

1. Create a `ScopeCapture`
2. Store it in `self.scope_captures`
3. Build plotting series:
   - one series per variable
4. Rebuild the chart

Recommended helper output:

```python
{
    "var_a": [(x0, y0), (x1, y1), ...],
    "var_b": [(x0, y0), (x1, y1), ...],
}
```

## Recommended Pull Scheduler

The desktop app must not monopolize the serial link.

So do not use a blocking `for sample in range(...)`.

Recommended scheduler behavior:

1. User clicks normal pull or force pull
2. App queries `INFO`
3. App validates scope state and metadata
4. App creates `ScopePullSession`
5. A low-priority scheduler sends exactly one `SAMPLE_QUERY`
6. It waits for one ACK
7. After ACK arrives, it schedules the next sample later

Recommended pace:

- one sample request every `10 ~ 20 ms`
- only one outstanding request at a time

This matches the user's requirement of time-sharing serial bandwidth.

## Scope Protocol Handling In App

Recommended new handler:

```python
def _handle_scope_protocol_frame(self, frame: ProtocolFrame) -> bool:
    ...
```

Call order in `handle_protocol_frame()` should remain clean:

1. firmware/update
2. home/factory/black box
3. scope
4. parameter/general

Scope handler responsibilities:

- route list responses
- route info responses
- route var-name responses
- route control ACKs
- route sample ACKs
- update `ScopeTab`
- advance pull session

## ScopeTab Public API Recommendation

Recommended methods:

```python
set_scope_list(items: list[ScopeListItem]) -> None
set_scope_info(info: ScopeInfo | None) -> None
set_scope_var_names(scope_id: int, var_names: list[str]) -> None
start_pull(scope_name: str, sample_count: int, mode_name: str) -> None
update_pull_progress(current: int, total: int) -> None
finish_pull(capture: ScopeCapture) -> None
fail_pull(message: str) -> None
set_status(message: str, detail: str = "") -> None
clear_captures() -> None
```

## Request Flow Recommendations

### Refresh scope list

1. send `SCOPE_LIST_QUERY`
2. collect incoming list items until `is_last`
3. populate dropdown

### Refresh scope info

1. send `SCOPE_INFO_QUERY(scope_id)`
2. update current info panel

### Refresh variable names

1. read `var_count` from current info
2. send `SCOPE_VAR_QUERY(scope_id, var_index)` one by one
3. collect names by index

### Start

1. send `SCOPE_START`
2. after ACK, refresh info

### Trigger

1. send `SCOPE_TRIGGER`
2. after ACK, refresh info

### Stop

1. send `SCOPE_STOP`
2. after ACK, refresh info

### Reset

1. send `SCOPE_RESET`
2. after ACK, refresh info
3. do not automatically clear local captures

### Normal pull

1. query info
2. if `state != idle`:
   - show running denied
3. if `data_ready == 0`:
   - show no ready capture
4. ensure var names are available
5. start low-priority sample pull session

### Force pull

1. query info
2. allow running state
3. ensure var names are available
4. start pull session with `read_mode = FORCE`

## Error Handling

### Running denied

Normal pull should show:

- status: device is still running
- detail: use force pull if you want to read current RAM data

### Capture changed

If ACK returns a different `capture_tag` than expected:

- mark the session warning
- allow continuing if policy is permissive
- set `capture_changed_during_pull = True`

Recommended UI wording:

- "Capture changed during pull. Data may be inconsistent."

### Timeout

If one sample ACK does not arrive in time:

- fail the pull session
- keep already collected local partial samples only if explicitly desired

First version recommendation:

- discard partial capture by default

## Export Recommendations

### CSV export

One export file per local capture.

Header example:

```text
time_ms,var_a,var_b,var_c
```

Rows:

```text
-3.300, ...
-3.267, ...
0.000, ...
```

### File naming

Recommended file name:

```text
scope_{scope_name}_tag_{capture_tag}.csv
```

## Lite Build Exclusion

This feature should not appear in Lite.

Recommended tab id:

- `scope`

Then Lite branding may hide it using the same hidden-tab mechanism already used by:

- monitor
- parameter
- wave

No extra Lite-specific code path should be added.

## i18n Recommendations

Add both Chinese and English text from the start.

Suggested labels:

- `软件录波` / `Scope`
- `刷新对象` / `Refresh Scopes`
- `刷新状态` / `Refresh Info`
- `普通拉取` / `Pull`
- `强制拉取` / `Force Pull`
- `清空本地波形` / `Clear Local Captures`
- `采样周期` / `Sample Period`
- `触发点` / `Trigger Point`
- `采集中，普通模式不可读取` / `Scope is running. Normal pull is not allowed.`
- `拉取过程中录波数据已变化` / `Capture changed during pull.`

## Implementation Order

Recommended coding order:

1. Add protocol helper module `scope_protocol.py`
2. Add scope models in `models.py`
3. Add basic `ScopeTab` layout without plotting
4. Add list/info/var-name request flow
5. Add control commands
6. Add low-priority pull scheduler
7. Add single capture plotting
8. Add multi-capture separation and trigger lines
9. Add CSV export

## First Deliverable Definition

First working desktop deliverable should support:

- list scopes
- read one scope info
- read all variable names
- send start/trigger/stop/reset
- normal pull one completed capture
- force pull current RAM capture
- show one plotted capture
- export one capture to CSV

Second deliverable can add:

- multiple local captures
- visual gaps
- capture list management
- richer plotting interactions
