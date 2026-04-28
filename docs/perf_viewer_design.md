# 任务时间查看器页面设计方案

## 1. 目标

新增一个类似 Windows 任务管理器的页面，用于从下位机拉取 `perf.c` 中的任务、中断和代码片段耗时信息。

页面目标：

- 查看任务与中断的当前占用率、最大占用率、当前运行时间和最大运行时间。
- 查看代码片段的当前运行时间和最大运行时间。
- 支持通过 shell 命令拉取当前性能记录。
- 支持搜索、筛选、排序、自动刷新和 CSV 导出。

## 2. 下位机依据

参考文件：

- `D:\OneDrive\LWX\GD32\base\code\dbg\perf.c`
- `D:\OneDrive\LWX\GD32\base\code\dbg\perf.h`

当前下位机已注册 shell 命令：

```c
REG_SHELL_CMD(perf_print_record, print_perf_record_start)
REG_SHELL_CMD(perf_print_task, print_perf_task_record)
REG_SHELL_CMD(perf_print_interrupt, print_perf_interrupt_record)
REG_SHELL_CMD(perf_print_code, print_perf_code_record)
REG_SHELL_CMD(CPU_Utilization, CPU_Utilization)
```

`perf_print_record` 输出表格字段：

```text
Type    Perf Name    Time(us)    Max(us)    Load(%)    Peak(%)
```

## 3. 占用率规则

### 3.1 TASK 和 INT

任务和中断有占用率概念。

依据：

- `perf_cpu_load_calculate()` 中只对 `SECTION_PERF_RECORD_TASK` 和 `SECTION_PERF_RECORD_INTERRUPT` 更新 `p->load` 与 `p->load_max`。
- TASK 总占用率由 `s_perf_task_metric` 记录。
- TASK 最大总占用率由 `s_perf_task_metric_max` 记录。
- INT 总占用率由 `s_perf_interrupt_metric` 记录。
- INT 最大总占用率由 `s_perf_interrupt_metric_max` 记录。
- `CPU_Utilization` 命令会分别输出 TASK 与 INT 的总占用率和峰值占用率。

页面上 TASK/INT 行展示：

- 当前运行时间 `Time(us)`
- 最大运行时间 `Max(us)`
- 当前占用率 `Load(%)`
- 最大占用率 `Peak(%)`

### 3.2 CODE

代码片段没有占用率概念。

依据：

- `SECTION_PERF_RECORD_CODE` 不在 `perf_cpu_load_calculate()` 中更新 `load/load_max`。
- 虽然当前文本输出中仍包含 `Load(%)` 与 `Peak(%)` 字段，但 CODE 行的这两个字段不作为业务含义展示。

页面上 CODE 行只展示：

- 当前运行时间 `Time(us)`
- 最大运行时间 `Max(us)`

CODE 行不展示占用率条，也不参与任务/中断总占用率统计。

## 4. 页面结构

页面名称建议：

```text
任务时间
```

或：

```text
Perf Viewer
```

### 4.1 顶部工具栏

内容：

- 页面标题：`任务时间`
- 当前连接：串口号、波特率、在线状态
- 搜索框：搜索任务、函数或中断名称
- 拉取按钮：
  - `拉取全部`
  - `只拉任务`
  - `只拉中断`
  - `只拉代码`
  - `CPU占用`
- 自动刷新：
  - 关闭
  - 1s
  - 2s
  - 5s
- 导出 CSV

### 4.2 顶部统计区

使用四个紧凑统计卡片：

- TASK 当前总占用率
- TASK 峰值总占用率
- INT 当前总占用率
- INT 峰值总占用率

这些数据来自 `CPU_Utilization` 输出。

### 4.3 主表格区

表格列建议：

```text
类型 | 名称 | 当前时间(us) | 最大时间(us) | 当前占用率 | 最大占用率 | 趋势 | 状态
```

展示规则：

- TASK 行显示时间、最大时间、当前占用率、最大占用率。
- INT 行显示时间、最大时间、当前占用率、最大占用率。
- CODE 行只显示时间和最大时间，占用率列显示 `-` 或空白。
- 表格支持按任意列排序。
- 表格支持按类型筛选：全部 / 任务 / 中断 / 代码片段。

## 5. 占用率条设计

TASK 和 INT 的占用率显示采用三层重叠条。

同一条轨道里叠加三层：

```text
100% 总长度背景条
最大占用率条
当前占用率条
```

含义：

- 第一层：完整背景轨道，代表 100%。
- 第二层：最大占用率，宽度为 `Peak(%)`。
- 第三层：当前占用率，宽度为 `Load(%)`，叠在最大占用率之上。

建议颜色：

- TASK 背景轨道：深灰
- TASK 最大占用率：蓝紫色
- TASK 当前占用率：青色
- INT 背景轨道：深灰
- INT 最大占用率：橙色
- INT 当前占用率：黄色

CODE 行不使用占用率条。

## 6. 右侧详情区

选中 TASK 或 INT 时显示：

- 类型
- 名称
- 当前运行时间
- 最大运行时间
- 当前占用率
- 最大占用率
- 三层重叠占用率条
- 最近更新时间
- 60 秒占用率趋势

选中 CODE 时显示：

- 类型
- 名称
- 当前运行时间
- 最大运行时间
- 最近更新时间
- 60 秒运行时间趋势

CODE 详情区不显示占用率条。

## 7. 通信方式

第一版建议复用 shell 文本命令，不新增二进制协议。

上位机发送：

```text
perf_print_record\r\n
```

或按类型发送：

```text
perf_print_task\r\n
perf_print_interrupt\r\n
perf_print_code\r\n
CPU_Utilization\r\n
```

上位机接收 shell 输出后按行解析。

## 8. 解析规则

### 8.1 perf 记录行

跳过：

- 空行
- 表头行
- 非 `TASK / INT / CODE / UNKNOWN` 开头的行

解析方式：

- 第一列：类型
- 最后四列：`Time(us)`、`Max(us)`、`Load(%)`、`Peak(%)`
- 中间内容：名称

注意：

- 下位机会根据最长名称动态补 tab，上位机解析时不应强依赖固定 tab 数量。
- 建议用空白分割后，从右侧取 4 个数值字段。

### 8.2 CPU_Utilization

解析以下两类行：

```text
TASK CPU Load:%f%%,TASK CPU Peak:%f%%
INT CPU Load:%f%%,INT CPU Peak:%f%%
```

分别更新顶部 TASK/INT 总占用率卡片。

## 9. 拉取完成判定

当前 `perf_print_record` 没有输出结束标记。

第一版上位机可以用静默超时判断：

- 发送拉取命令后进入 collecting 状态。
- 收到表头或有效行后刷新最后接收时间。
- 超过 500ms 未收到新的有效 perf 行，认为本轮拉取完成。

建议下位机后续增强：

```text
PERF_END
```

当 `print_perf_record_step()` 打印完所有记录后输出结束标记，上位机可据此精确结束本轮拉取。

## 10. 上位机模块建议

后续实现时建议新增：

```text
serial_debug_assistant/perf_shell.py
serial_debug_assistant/ui/perf_tab.py
```

`perf_shell.py` 负责：

- `PerfRecord`
- `PerfSummary`
- perf 文本行解析
- CPU_Utilization 文本解析
- 拉取会话状态

`perf_tab.py` 负责：

- 页面布局
- 表格展示
- 占用率条绘制
- 详情区
- 自动刷新与导出

`ui/app.py` 负责：

- 创建任务时间页签
- 发送 shell 命令
- 将串口 shell 行分发给任务时间页

## 11. 与现有通信架构的关系

当前上位机已有 `CommunicationManager`：

- 协议帧继续走 `ProtocolParser` 与 `ProtocolRouter`。
- shell 文本建议走 raw bytes 的行解析器。

建议在通信层增加 shell 行监听能力：

```text
串口 raw bytes
  -> 协议 parser 继续解析 0xE8 帧
  -> shell line collector 按 \r\n 切行
  -> Perf 页面消费 shell 行
```

这样可以让同一个串口同时支持：

- 主页、参数、波形、升级等二进制协议
- perf 任务时间查看器 shell 文本输出

## 12. 第一版实现范围

第一版只做：

- 任务时间页签
- shell 命令拉取
- perf 表格解析
- TASK/INT 占用率条
- CODE 时间显示
- CPU_Utilization 顶部统计
- 搜索、类型筛选、手动刷新

自动刷新、CSV 导出、趋势图可以作为第二阶段补充。
