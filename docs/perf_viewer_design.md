# 任务时间查看器页面设计方案

## 1. 目标

新增一个类似 Windows 任务管理器的页面，用于从下位机拉取 `perf.c` 中的任务、中断和代码片段耗时信息。

页面目标：

- 查看任务与中断的当前占用率、最大占用率、当前运行时间和最大运行时间。
- 查看任务多久运行一次的周期时间。
- 查看代码片段的当前运行时间和最大运行时间。
- 支持按全部、任务、中断、代码片段筛选拉取。
- 支持搜索、自动刷新、CSV 导出和选中项详情展示。
- 使用二进制协议拉取数据，不再使用 shell 文本命令。

## 2. 下位机依据

参考文件：

- `D:\OneDrive\LWX\GD32\base\code\dbg\perf.c`
- `D:\OneDrive\LWX\GD32\base\code\dbg\perf.h`

Perf 记录分为三类：

```text
TASK       任务
INTERRUPT  中断
CODE       代码片段
```

占用率规则：

- TASK 和 INTERRUPT 有占用率概念。
- CODE 没有占用率概念，只展示运行时间和最大运行时间。
- TASK 额外展示 `period_us`，表示任务多久运行一次。

## 3. 页面结构

页面名称：

```text
任务时间
```

### 3.1 顶部工具区

顶部工具区包含：

- 页面标题：`FRAME 任务时间查看器`
- Target Address
- Dynamic Address
- 搜索框
- `拉取全部`
- `Task`
- `Interrupt`
- `Code`
- `自动刷新 1s / 停止刷新`
- `Reset Peak`
- `导出 CSV`

筛选按钮语义：

```text
ALL       拉取全部记录
TASK      只拉任务记录
INTERRUPT 只拉中断记录
CODE      只拉代码片段记录
```

周期查询规则：

- 周期固定为 1s。
- 用户先选择 ALL/TASK/INTERRUPT/CODE，再开启周期查询。
- 周期查询运行中允许继续切换 ALL/TASK/INTERRUPT/CODE。
- 切换后下一轮周期查询使用新的筛选类型。

### 3.2 顶部统计区

顶部统计区显示四个指标：

- 任务总占用
- 任务峰值
- 中断总占用
- 中断峰值

这些数据来自 `0x21 PERF_SUMMARY_QUERY`。
上位机每次手动拉取或周期拉取记录时都会自动发送 `0x21`，页面不提供单独的 Summary 按钮。

### 3.3 Records 表格

表格列：

```text
Type | Name | Run Time (us) | Max Time (us) | Load | Peak
```

显示规则：

- TASK 显示运行时间、最大运行时间、当前占用率、峰值占用率。
- INTERRUPT 显示运行时间、最大运行时间、当前占用率、峰值占用率。
- CODE 显示运行时间、最大运行时间，Load 和 Peak 显示 `-`。
- 表格内容居中显示。
- 周期刷新时不清空整表，使用增量更新：
  - 已存在记录只更新时间。
  - 新增记录插入。
  - 本轮拉取中缺失的记录删除。

### 3.4 选中项详情区

选中 TASK 时显示：

- 类型
- 名称
- 当前运行时间
- 最大运行时间
- 任务周期 `period_us`
- 当前占用率
- 峰值占用率
- 占用率对比条

选中 INTERRUPT 时显示：

- 类型
- 名称
- 当前运行时间
- 最大运行时间
- 当前占用率
- 峰值占用率
- 占用率对比条

选中 CODE 时显示：

- 类型
- 名称
- 当前运行时间
- 最大运行时间

CODE 不显示占用率条。

## 4. 占用率条设计

TASK 和 INTERRUPT 的占用率显示采用三层重叠条。

同一轨道内叠加：

```text
100% 总长度背景条
最大占用率条
当前占用率条
```

含义：

- 第一层：完整背景轨道，代表 100%。
- 第二层：最大占用率，宽度为 `peak_percent`。
- 第三层：当前占用率，宽度为 `load_percent`。

CODE 不使用占用率条。

## 5. 通信协议

Perf 使用现有 `0xE8` 二进制协议帧：

```text
SOP          u8   0xE8
version      u8   0x01
src          u8
d_src        u8
dst          u8
d_dst        u8
cmd_set      u8   0x01
cmd_word     u8
is_ack       u8
payload_len  u16  little-endian
payload      bytes
crc16        u16  little-endian
EOP          0D 0A
```

Perf 命令字：

```text
0x20 PERF_INFO_QUERY
0x21 PERF_SUMMARY_QUERY
0x25 PERF_RESET_PEAK
0x26 PERF_DICT_QUERY
0x27 PERF_DICT_ITEM_REPORT
0x28 PERF_DICT_END
0x29 PERF_SAMPLE_QUERY
0x2A PERF_SAMPLE_BATCH_REPORT
0x2B PERF_SAMPLE_END
```

旧的 `0x22 / 0x23 / 0x24` Perf 列表协议已删除，上位机不再兼容。

### 5.1 地址规则

上位机发送时使用 Perf 页面填写的：

```text
Target Address  -> dst
Dynamic Address -> d_dst
```

上位机接收时接受以下目标地址：

```text
dst = 0x00, d_dst = 0x00  广播帧
dst = 0x01, d_dst = 0x00  发给 PC，动态地址广播
dst = 0x01, d_dst = 0x01  发给 PC 明确动态地址
```

## 6. Info / Summary / Reset

### 6.1 `0x20 PERF_INFO_QUERY`

上位机发送：

```text
cmd_word = 0x20
is_ack   = 0
payload  = empty
```

下位机回复：

```c
struct perf_info_ack {
    uint16_t protocol_version;
    uint16_t record_count;
    float    unit_us;
    uint32_t cnt_per_sys_tick;
    uint32_t cpu_window_ms;
    uint8_t  flags;
    uint8_t  reserved[3];
};
```

### 6.2 `0x21 PERF_SUMMARY_QUERY`

上位机发送：

```text
cmd_word = 0x21
is_ack   = 0
payload  = empty
```

下位机回复：

```c
struct perf_summary_ack {
    float task_load_percent;
    float task_peak_percent;
    float interrupt_load_percent;
    float interrupt_peak_percent;
};
```

### 6.3 `0x25 PERF_RESET_PEAK`

上位机发送：

```text
cmd_word = 0x25
is_ack   = 0
payload  = empty
```

下位机回复：

```c
struct perf_reset_peak_ack {
    uint8_t success;
};
```

## 7. 字典协议

字典用于发送低频变化的信息，包括记录 ID、类型、顺序和名称。周期刷新不重复发送名称。

### 7.1 `0x26 PERF_DICT_QUERY`

上位机发送：

```c
struct perf_dict_query {
    uint8_t  type_filter;        // 0=ALL, 1=TASK, 2=INTERRUPT, 3=CODE
    uint8_t  reserved[3];
    uint32_t known_dict_version;
};
```

下位机 ACK：

```c
struct perf_dict_ack {
    uint8_t  accepted;
    uint8_t  type_filter;
    uint16_t record_count;
    uint32_t sequence;
    uint32_t dict_version;
    uint8_t  reject_reason;      // 0=OK, 1=Busy, 2=Invalid filter, 3=No buffer, 4=Unsupported
    uint8_t  reserved[3];
};
```

### 7.2 `0x27 PERF_DICT_ITEM_REPORT`

下位机逐条上报字典项：

```c
struct perf_dict_item_header {
    uint32_t sequence;
    uint16_t index;
    uint16_t record_count;
    uint16_t record_id;
    uint8_t  record_type;        // 1=TASK, 2=INTERRUPT, 3=CODE
    uint8_t  name_len;
    uint8_t  name[name_len];     // UTF-8/ASCII, no trailing '\0'
};
```

`record_id` 要求在同一个 `dict_version` 内稳定。

### 7.3 `0x28 PERF_DICT_END`

字典结束帧：

```c
struct perf_dict_end {
    uint32_t sequence;
    uint16_t record_count;
    uint8_t  status;             // 0=OK, 1=Cancelled, 2=Overflow, 3=Internal error
    uint8_t  reserved;
    uint32_t dict_version;
};
```

上位机收到 `status = 0` 后，如果之前已有待执行 sample 查询，会继续发送 `0x29`。

## 8. Sample 协议

Sample 用于周期刷新高频变化的数据。

### 8.1 `0x29 PERF_SAMPLE_QUERY`

上位机发送：

```c
struct perf_sample_query {
    uint8_t  type_filter;        // 0=ALL, 1=TASK, 2=INTERRUPT, 3=CODE
    uint8_t  flags;              // 当前填 0
    uint16_t reserved;
    uint32_t dict_version;
};
```

下位机 ACK：

```c
struct perf_sample_ack {
    uint8_t  accepted;
    uint8_t  type_filter;
    uint16_t record_count;
    uint32_t sequence;
    uint32_t dict_version;
    uint8_t  reject_reason;
    uint8_t  reserved[3];
};
```

如果 ACK 中的 `dict_version` 与上位机缓存不一致，上位机会清空字典并重新拉取 `0x26`。

### 8.2 `0x2A PERF_SAMPLE_BATCH_REPORT`

下位机将多条 sample 合并到一个或多个 batch 帧。

batch 头：

```c
struct perf_sample_batch_header {
    uint32_t sequence;
    uint16_t record_count;       // 本轮总记录数
    uint16_t item_count;         // 本帧包含的 item 数
};
```

item 的格式由字典中 `record_type` 决定。

TASK item：

```c
struct perf_sample_task_item {
    uint16_t record_id;
    uint32_t time_us;
    uint32_t max_time_us;
    uint32_t period_us;
    float    load_percent;
    float    peak_percent;
};
```

INTERRUPT item：

```c
struct perf_sample_interrupt_item {
    uint16_t record_id;
    uint32_t time_us;
    uint32_t max_time_us;
    float    load_percent;
    float    peak_percent;
};
```

CODE item：

```c
struct perf_sample_code_item {
    uint16_t record_id;
    uint32_t time_us;
    uint32_t max_time_us;
};
```

说明：

- `load_percent` 和 `peak_percent` 仍为 `float32`。
- CODE 不发送占用率。
- INTERRUPT 不发送 `period_us`。
- TASK 发送 `period_us`。
- 若 payload 接近上位机最大 payload 限制，需拆分为多个 `0x2A`。

### 8.3 `0x2B PERF_SAMPLE_END`

sample 结束帧：

```c
struct perf_sample_end {
    uint32_t sequence;
    uint16_t record_count;
    uint8_t  status;             // 0=OK, 1=Cancelled, 2=Overflow, 3=Internal error
    uint8_t  reserved;
};
```

## 9. 上位机拉取流程

### 9.1 进入页面与首次拉取

打开串口后进入 Perf 页，上位机会自动准备一次字典：

```text
进入 Perf 页
  -> 发送 0x20 PERF_INFO_QUERY
  -> 若本地没有字典，发送 0x26 PERF_DICT_QUERY，type_filter = ALL
  -> 接收 0x27 字典项
  -> 接收 0x28 字典结束
```

首次点击 ALL/TASK/INTERRUPT/CODE 拉取时：

```text
用户点击 ALL/TASK/INTERRUPT/CODE
  -> 发送 0x21 PERF_SUMMARY_QUERY
  -> 若本地没有字典，发送 0x20 + 0x26 自动补齐字典
  -> 接收 0x27 字典项
  -> 接收 0x28 字典结束
  -> 发送 0x29 PERF_SAMPLE_QUERY，type_filter = 用户选择
  -> 接收 0x2A sample batch
  -> 接收 0x2B sample end
```

字典总是优先拉 ALL，保证后续切换筛选类型时无需重复拉名称。

### 9.2 周期查询

```text
每 1s：
  -> 发送 0x21 PERF_SUMMARY_QUERY
  -> 发送 0x29 PERF_SAMPLE_QUERY，type_filter = 当前选中的筛选类型
  -> 接收 0x2A sample batch
  -> 接收 0x2B sample end
```

周期查询不走旧协议，不使用 shell 文本解析，也不使用静默超时判定完成。

### 9.3 字典版本变化

如果 `0x29` ACK 中的 `dict_version` 与上位机缓存不同，或设备返回 `reject_reason = 5`：

```text
清空本地字典
重新发送 0x26 PERF_DICT_QUERY
字典完成后重新发送 0x29 PERF_SAMPLE_QUERY
```

上位机 Records 表格内部以 `record_id` 作为稳定键，避免同名记录、筛选切换和周期刷新时误删误更新。

## 10. 上位机模块

当前实现模块：

```text
serial_debug_assistant/perf_protocol.py
serial_debug_assistant/ui/perf_tab.py
serial_debug_assistant/ui/app.py
```

`perf_protocol.py` 负责：

- Perf 命令字定义
- Info/Summary/Dict/Sample payload 构造与解析
- 记录类型、筛选类型、状态码说明

`ui/perf_tab.py` 负责：

- 页面布局
- 表格展示
- 占用率条绘制
- 选中项详情
- 自动刷新与导出

`ui/app.py` 负责：

- 创建任务时间页签
- 发送 Perf 二进制协议帧
- 维护 Perf 字典缓存和字典版本
- 将 sample batch 转成页面记录更新

## 11. 当前实现范围

当前已实现：

- 任务时间页签
- Info/Summary/Reset Peak
- Dict/Sample 新协议拉取
- 1s 周期查询
- ALL/TASK/INTERRUPT/CODE 筛选
- 增量更新 Records 表格
- 进入 Perf 页自动准备字典
- 字典版本变化自动重同步
- TASK/INT 占用率条
- CODE 时间显示
- TASK period_us 详情显示
- CSV 导出

当前不再支持：

- shell 文本命令拉取 Perf
- `0x22 / 0x23 / 0x24` 旧 Perf 列表协议
- 静默超时判断拉取完成
