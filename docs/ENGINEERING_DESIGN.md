# 工程设计文档

## 1. 文档说明

### 1.1 文档目的

本文档用于说明本工程的总体设计思路、通信协议设计、分页功能设计、操作方法与维护扩展方式，作为开发、联调、测试和后续迭代的统一参考。

### 1.2 适用范围

本文档适用于：

- 当前上位机桌面软件工程
- 与之配套的串口通信协议
- 当前已实现的分页功能
- 后续在现有架构下新增的小功能和新分页

### 1.3 文档边界

本文档重点关注以下内容：

- 协议设计与数据结构
- 分页的设计目标与实现方式
- 页面与协议之间的对应关系
- 用户操作说明
- 后续扩展与维护建议

本文档不以源码目录讲解为主体，也不替代代码注释或逐文件 API 文档。

### 1.4 版本信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | 工程设计文档 |
| 文档版本 | v1.0 |
| 软件版本 | v1.7.1 |
| Lite 版本 | v2.3.0 |
| 最后更新日期 | 2026-05-01 |
| 维护方式 | 按协议章节与分页章节持续增量维护 |

### 1.5 名词定义

| 名词 | 说明 |
| --- | --- |
| `cmd_set` | 命令集，用于对通信能力做大类划分 |
| `cmd_word` | 命令字，用于表示某个命令集下的具体功能 |
| `ACK` | 应答帧，`is_ack = 1` |
| `Target Address` | 目标地址，即通信报文中的 `dst` |
| `Dynamic Address` | 动态地址，即通信报文中的 `d_dst` |
| `broadcast` | 广播地址，通常用于发送全局控制命令 |
| `Scope` | 软件录波功能，面向下位机 RAM 中保存的一次录波数据 |
| `capture_tag` | 录波标号，用于识别一次抓取过程中设备侧录波包是否发生变化 |
| `data_ready` | 数据就绪标志，用于表示本次录波是否可供常规拉取 |
| `normal pull` | 常规拉取，仅允许在录波停止且数据就绪时进行 |
| `force pull` | 强制拉取，允许在设备运行过程中读取当前录波缓冲区 |

### 1.6 阅读建议

- 需要了解协议时，从第 2 章开始阅读。
- 需要了解某个页面时，从第 3 章对应分页开始阅读。
- 需要联调时，建议先阅读协议章节，再阅读对应分页的操作说明与注意事项。
- 需要扩展功能时，优先阅读第 8 章扩展与维护规则。

## 2. 通信协议详细说明

### 2.1 协议设计目标

本工程的串口协议设计目标为：

- 为上位机与设备之间建立统一、稳定、可扩展的串口通信机制
- 在有限带宽与有限资源条件下，兼顾状态查询、数据交互、数据采集与维护操作
- 通过统一帧结构承载多类功能协议，并支持后续增量扩展
- 使协议层与分页界面层解耦，便于新增页面和新增小功能

#### 2.1.1 设计原则

- 统一帧格式
- 功能按命令集与命令字分层
- 请求 / 应答机制清晰
- 数据结构尽量定长或易解析
- 页面逻辑与协议能力对应，但不过度绑定
- 支持后续兼容扩展

### 2.2 总帧格式

#### 2.2.1 帧结构体定义

`通信.pdf` 定义了一个以 `0xE8` 为起始符、以 `0x0A0D` 为结束符的轻量级通信帧，等价结构如下：

```c
#pragma pack(1)
typedef struct
{
    uint8_t sop;
    uint8_t version;
    uint8_t src;
    uint8_t d_src;
    uint8_t dst;
    uint8_t d_dst;
    uint8_t cmd_set;
    uint8_t cmd_word;
    uint8_t is_ack;
    uint16_t len;
    uint8_t *p_data;
    uint16_t crc;
    uint16_t eop;
} section_packform_t;
```

#### 2.2.2 字段说明

| 字段 | 长度 | 含义 | 备注 |
| --- | --- | --- | --- |
| `sop` | 1B | 起始符 | 固定为 `0xE8` |
| `version` | 1B | 协议版本号 | 当前使用 `0x01` |
| `src` | 1B | 源地址 | 上位机或设备地址 |
| `d_src` | 1B | 动态源地址 | 用于地址扩展 |
| `dst` | 1B | 目的地址 | 目标模块地址 |
| `d_dst` | 1B | 动态目的地址 | 用于地址扩展 |
| `cmd_set` | 1B | 命令集 | 按功能大类划分 |
| `cmd_word` | 1B | 命令字 | 命令集下的具体功能 |
| `is_ack` | 1B | 应答标记 | `0` 为请求，`1` 为应答 |
| `len` | 2B | `payload` 长度 | 小端 |
| `p_data` | 变长 | 数据载荷 | 长度由 `len` 决定 |
| `crc` | 2B | CRC16 校验值 | 覆盖 `sop..payload` |
| `eop` | 2B | 结束符 | 固定为 `0x0D 0x0A` |

#### 2.2.3 帧收发规则

- 接收端按 `sop -> 固定头 -> payload -> crc -> eop` 顺序解析。
- `len` 只表示 `payload` 的字节数，不包含头、CRC 和尾部。
- CRC 校验失败时，当前帧无效。
- 上位机侧 `protocol.py` 中的 `FrameParser` 负责按上述规则拆帧与验帧。

### 2.3 数据编码约定

#### 2.3.1 字节序

- 所有多字节整型字段均按小端编码传输。

#### 2.3.2 基本类型

- `uint8_t / uint16_t / uint32_t`：按无符号整型传输
- `int8_t`：按有符号整型传输
- `float`：按 IEEE754 单精度浮点原始位模式传输
- 字符串：一般为紧随结构体头后的变长字节序列

#### 2.3.3 通用数据承载约定

- 参数与黑匣子中的很多数值采用 `uint32_t` 作为统一承载类型。
- 当实际类型长度短于 4 字节时，高位补零。
- 当实际类型为浮点数时，直接拷贝其原始位，例如：

```c
uint32_t data = 0;
float fp32 = 0.01f;
memcpy(&data, &fp32, 4);
```

### 2.4 CRC 与校验规则

- 通信帧校验采用 `CRC-16-CCITT`
- 多项式为 `0x1021`
- 初始值为 `0xFFFF`
- 计算范围为从 `sop` 开始到 payload 最后一个字节结束，不包含 `crc` 和 `eop`

### 2.5 地址机制说明

- `src / d_src` 表示源地址与动态源地址
- `dst / d_dst` 表示目标地址与动态目标地址
- 上位机页面中填写的 `Target Address` 和 `Dynamic Address` 最终映射到 `dst / d_dst`
- 广播命令通常使用 `dst = 0x00, d_dst = 0x00`

### 2.6 请求 / 应答机制

- `is_ack = 0` 表示请求帧
- `is_ack = 1` 表示应答帧
- `ACK` 只用于同一个 `cmd_set / cmd_word` 的直接响应：上位机发送某指令，下位机用相同指令回包时才设置 `is_ack = 1`
- 若某个请求触发下位机后续逻辑，但下位机通过其他 `cmd_word` 主动上报数据，则这些不同指令的回包不属于 ACK，应设置 `is_ack = 0`
- 示例：上位机发送 `0x01 / 0x18` 查询录波列表，下位机通过 `0x01 / 0x18` 逐条返回列表项时使用 `is_ack = 1`；若该请求触发了其他指令的数据上报，其他指令不设置 ACK
- 某些功能采用无 ACK 上报，例如主页广播与波形上报
- 查询类与控制类命令通常要求收到 ACK 后再更新上位机状态

### 2.7 超时 / 重试 / 状态码规则

- 普通查询类命令由上位机主线程异步等待响应
- 软件录波 Scope 拉取使用独立拉取状态机，支持超时和有限次数重试
- 设备返回状态码后，上位机会转换成可读文本并更新对应分页提示信息

### 2.8 状态码与错误码总表

当前工程中不同协议使用各自的状态码集合，本章仅统一说明管理方式：

- 参数页：通过结构体中的 `status` 字段区分自动上报、重要参数等属性
- 升级页：使用升级 ACK 字段与错误码字段描述阶段状态和失败原因
- Scope 页：使用 `scope_tool_status_e`
- 黑匣子页：使用 `accepted`、`has_more` 等字段表达查询状态
- 工厂模式页：按命令 ACK 是否成功和结构体内容判断结果

### 2.9 指令集详细说明

#### 2.9.1 `cmd_set = 0x01`

`cmd_set = 0x01` 承载当前大部分辅助工具与上位机交互协议，包括参数读写、参数波形、固件升级、Black Box、Scope、工厂模式时间与校准等能力。

##### 参数列表总数读取 `0x01 / 0x01`

```c
// request payload: NULL
typedef struct
{
    uint32_t data_num;
} cmd_0101_ack_t;
```

- 请求 payload 为空
- ACK 返回参数总数 `data_num`

##### 单参数读取 `0x01 / 0x02`

```c
typedef struct
{
    uint8_t name_len;
    char name[];
} cmd_0102_req_t;

typedef struct
{
    uint8_t name_len;
    uint8_t type;
    uint32_t data;
    char name[];
} cmd_0102_ack_t;
```

##### 单参数写入或执行 `0x01 / 0x03`

```c
typedef struct
{
    uint8_t name_len;
    uint32_t data;
    uint32_t data_max;
    uint32_t data_min;
    char name[];
} cmd_0103_req_t;

typedef struct
{
    uint8_t name_len;
    uint8_t type;
    uint32_t data;
    uint32_t data_max;
    uint32_t data_min;
    char name[];
} cmd_0103_ack_t;
```

##### 参数列表项下发 `0x01 / 0x04`

```c
typedef struct
{
    uint8_t name_len;
    uint8_t type;
    uint32_t data;
    uint32_t data_max;
    uint32_t data_min;
    uint8_t status;
    char name[];
} cmd_0104_item_t;
```

- 每个参数占一帧
- `status.bit0` 当前映射为自动上报
- `status.bit1` 当前映射为重要参数

##### 参数波形勾选 `0x01 / 0x05`

```c
typedef struct
{
    uint8_t name_len;
    uint8_t auto_report;
    char name[];
} cmd_0105_req_t;

typedef struct
{
    uint8_t ok;
} cmd_0105_ack_t;
```

##### 参数波形周期设置 `0x01 / 0x06`

```c
typedef struct
{
    uint32_t reprot_period;
} cmd_0106_req_t;
```

- 请求与 ACK 使用相同结构
- 单位为毫秒

##### 参数波形上报 `0x01 / 0x07`

```c
typedef struct
{
    uint8_t name_len;
    uint8_t type;
    uint32_t data;
    char name[];
} cmd_0107_report_t;
```

- `name_len = 0, type = 0, data = 0x55555555` 表示批次开始
- `name_len = 0, type = 0, data = 0xAAAAAAAA` 表示批次结束

##### 固件升级 `0x01 / 0x08 ~ 0x0D`

```c
typedef struct
{
    uint8_t module_id;
    uint32_t version;
    uint32_t file_size;
    uint8_t update_type;
} cmd_0108_req_t;

typedef struct
{
    uint8_t allow_update;
    uint16_t reject_reason;
} cmd_0108_ack_t;

typedef struct
{
    uint8_t ready;
} cmd_0109_ack_t;

typedef struct
{
    uint32_t offset;
    uint8_t module_id;
    uint16_t data_length;
    uint8_t packet_data[256];
    uint16_t packet_crc;
} cmd_010A_req_t;

typedef struct
{
    uint8_t data_is_ok;
} cmd_010A_ack_t;

typedef struct
{
    uint16_t fw_crc;
} cmd_010B_req_t;

typedef struct
{
    uint8_t success_flg;
} cmd_010B_ack_t;

typedef struct
{
    uint8_t source_module_id;
    uint8_t target_module_id;
    uint8_t stage;
    uint8_t result;
    uint32_t forwarded_bytes;
    uint32_t total_bytes;
    uint32_t packet_offset;
    uint16_t packet_length;
    uint16_t progress_permille;
    uint16_t error_code;
} llc_pfc_upgrade_progress_ack_t;
```

##### Black Box 范围查询 `0x01 / 0x0E ~ 0x11`

`0x0E ~ 0x11` 属于 Black Box 页面能力，不是 Scope 页面依赖命令。仅联调 Scope 的下位机工程可以不实现本组命令。

```c
typedef struct
{
    uint32_t start_offset;
    uint32_t read_length;
} black_box_range_query_req_t;

typedef struct
{
    uint8_t accepted;
    uint32_t start_offset;
    uint32_t read_length;
} black_box_range_query_ack_t;

typedef struct
{
    char header_text[];
} black_box_header_report_t;

typedef struct
{
    uint32_t record_offset;
    char row_text[];
} black_box_row_report_t;

typedef struct
{
    uint32_t start_offset;
    uint32_t end_offset;
    uint32_t scanned_bytes;
    uint16_t row_count;
    uint8_t has_more;
} black_box_range_complete_report_t;
```

##### 工厂模式时间协议 `0x01 / 0x12 ~ 0x13`

`0x12 ~ 0x13` 属于 Factory Mode 页面能力，不是 Scope 页面依赖命令。仅联调 Scope 的下位机工程可以不实现本组命令。

```c
typedef struct
{
    uint32_t unix_time_utc;
    int8_t timezone_half_hour;
} factory_time_payload_t;
```

##### 工厂模式校准协议 `0x01 / 0x14 ~ 0x16`

`0x14 ~ 0x16` 属于 Factory Mode 页面能力，不是 Scope 页面依赖命令。仅联调 Scope 的下位机工程可以不实现本组命令。

```c
typedef struct
{
    uint8_t id;
} cali_query_t;

typedef struct
{
    uint8_t id;
    float gain;
    float bias;
} cali_info_t;
```

##### 固件版本查询 `0x01 / 0x17`

`0x17` 属于固件版本查询能力，不是 Scope 页面依赖命令。仅联调 Scope 的下位机工程可以不实现该命令。

```c
typedef struct
{
    uint32_t version;
} firmware_version_ack_t;
```

##### 软件录波 Scope 协议 `0x01 / 0x18 ~ 0x1F`

当前工程新增独立的软件录波页签，用于和下位机 `scope / scope_service` 模块联调。由于 `0x01 / 0x17` 已被固件版本查询占用，Scope 命令字从 `0x18` 开始分配。

| `cmd_word` | 方向 | 用途 | 说明 |
| --- | --- | --- | --- |
| `0x18` | PC -> 设备 / 设备 -> PC | 查询录波对象列表 | 下位机逐条返回 `scope_id + name` |
| `0x19` | PC -> 设备 / ACK | 查询录波对象状态信息 | 返回采样点数、变量数量、触发索引、采样周期、录波标号等 |
| `0x1A` | PC -> 设备 / ACK | 查询某个变量名 | 变量名按索引逐个返回 |
| `0x1B` | PC -> 设备 / ACK | 开始录波 | 空闲态允许开始，成功后 `capture_tag` 自增 |
| `0x1C` | PC -> 设备 / ACK | 触发录波 | 仅运行态允许触发 |
| `0x1D` | PC -> 设备 / ACK | 停止录波 | 停止后可把本次数据标记为 `data_ready` |
| `0x1E` | PC -> 设备 / ACK | 复位录波 | 清状态并清除 `data_ready` |
| `0x1F` | PC -> 设备 / ACK | 按采样索引读取单个采样点 | 上位机采用颗粒化轮询拉取 |

```c
typedef enum
{
    SCOPE_READ_MODE_NORMAL = 0,
    SCOPE_READ_MODE_FORCE = 1,
} scope_read_mode_e;

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

typedef struct
{
    uint8_t scope_id;
    uint8_t is_last;
    uint8_t name_len;
    uint8_t reserved;
} scope_list_item_t;

typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t state;
    uint8_t data_ready;
    uint8_t var_count;
    uint8_t reserved[3];
    uint32_t sample_count;
    uint32_t write_index;
    uint32_t trigger_index;
    uint32_t trigger_post_cnt;
    uint32_t trigger_display_index;
    uint32_t sample_period_us;
    uint32_t capture_tag;
} scope_info_ack_t;

typedef struct
{
    uint8_t scope_id;
    uint8_t var_index;
    uint8_t reserved[2];
} scope_var_query_t;

typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t var_index;
    uint8_t is_last;
    uint8_t name_len;
    uint8_t reserved[3];
} scope_var_ack_t;

typedef struct
{
    uint8_t scope_id;
    uint8_t status;
    uint8_t state;
    uint8_t data_ready;
    uint32_t capture_tag;
} scope_ctrl_ack_t;

typedef struct
{
    uint8_t scope_id;
    uint8_t read_mode;
    uint8_t reserved[2];
    uint32_t sample_index;
    uint32_t expected_capture_tag;
} scope_sample_query_t;

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
} scope_sample_ack_t;
```

当前 Scope 协议约束如下：

- `0x18` 列表查询由上位机发送请求，下位机使用同一个 `0x18` 指令逐条回包，因此列表项应设置 `is_ack = 1`
- 上位机发送 `0x18` 后会等待首条列表项，首帧超时时间为 1500ms；收到任意一条 `0x18` 列表项后即取消首帧超时
- 上位机支持 `0x18` 分步上报；建议下位机收到查询后立即发送第一条，后续可按 1ms 间隔逐条发送，避免连续 DMA 发送覆盖
- 上位机只有收到 `is_last = 1` 后才把完整 Scope 列表刷新到 UI
- 若下位机没有任何 Scope 对象，也应在 1500ms 内返回一个结束项，例如 `name_len = 0` 且 `is_last = 1`
- 当前 `scope_list_item_t` 的 `name` 前有 4 字节头：`scope_id / is_last / name_len / reserved`；`reserved` 字段上位机会忽略，但当前协议中仍需占位，否则名称会错位
- 录波对象通过 `scope_id` 编址，不在协议中直接传完整对象名
- 变量名采用逐项读取，避免一次性下发长表头
- 采样值采用“单个采样点请求、单个采样点应答”的颗粒化拉取方式
- 常规拉取仅允许在 `IDLE + data_ready = 1` 时进行；非 IDLE 时返回 `SCOPE_TOOL_STATUS_RUNNING_DENIED = 4`，未 ready 时返回 `SCOPE_TOOL_STATUS_DATA_NOT_READY = 5`
- 强制拉取允许在运行过程中读取当前缓冲区
- `0x1B` 开始录波成功后 `capture_tag` 自增，并清除 `data_ready = 0`
- `0x1C` 触发录波仅运行态允许；非运行态应返回 `SCOPE_TOOL_STATUS_RUNNING_DENIED = 4`，不返回 OK
- `0x1D` 停止录波成功后设置 `data_ready = 1`，并保持当前 buffer 可供 normal pull
- 上位机在 `0x1B / 0x1C / 0x1D / 0x1E` 控制 ACK 状态为 OK 后，会自动重新发送 `0x19` 读取 Scope 信息

##### 任务时间 Perf 协议 `0x01 / 0x20 ~ 0x2B`

Perf 页用于读取下位机任务、中断和代码片段的耗时统计。当前只保留优化后的字典 + sample 二进制协议，不再兼容旧的 `0x22 / 0x23 / 0x24` Perf 列表协议，也不再使用 shell 文本命令。

| `cmd_word` | 方向 | 用途 | 说明 |
| --- | --- | --- | --- |
| `0x20` | PC -> 设备 / ACK | 查询 Perf 基本信息 | 返回协议版本、记录数、时间单位、统计窗口等 |
| `0x21` | PC -> 设备 / ACK | 查询 TASK/INT 总占用率 | 返回任务总占用、任务峰值、中断总占用、中断峰值 |
| `0x25` | PC -> 设备 / ACK | 重置峰值 | 清除任务、中断和记录峰值 |
| `0x26` | PC -> 设备 / ACK | 查询 Perf 字典 | 字典包含 `record_id / type / index / name` |
| `0x27` | 设备 -> PC | 字典项上报 | 逐项上报字典记录 |
| `0x28` | 设备 -> PC | 字典结束 | 标识本轮字典传输完成 |
| `0x29` | PC -> 设备 / ACK | 查询 Perf sample | 按 ALL/TASK/INTERRUPT/CODE 拉取当前数值 |
| `0x2A` | 设备 -> PC | sample 批量上报 | 一帧携带多条 sample item |
| `0x2B` | 设备 -> PC | sample 结束 | 标识本轮 sample 传输完成 |
| `0x2E` | PC -> 设备 / 可选 ACK | Perf 上报控制 | 当前用于打开串口、关闭串口和退出程序时广播停止 Perf |

Perf 字典查询：

```c
typedef struct
{
    uint8_t type_filter;          // 0=ALL, 1=TASK, 2=INTERRUPT, 3=CODE
    uint8_t reserved[3];
    uint32_t known_dict_version;
} perf_dict_query_t;

typedef struct
{
    uint8_t accepted;
    uint8_t type_filter;
    uint16_t record_count;
    uint32_t sequence;
    uint32_t dict_version;
    uint8_t reject_reason;
    uint8_t reserved[3];
} perf_dict_ack_t;

typedef struct
{
    uint32_t sequence;
    uint16_t index;
    uint16_t record_count;
    uint16_t record_id;
    uint8_t record_type;          // 1=TASK, 2=INTERRUPT, 3=CODE
    uint8_t name_len;
    uint8_t name[name_len];
} perf_dict_item_t;

typedef struct
{
    uint32_t sequence;
    uint16_t record_count;
    uint8_t status;
    uint8_t reserved;
    uint32_t dict_version;
} perf_dict_end_t;
```

Perf sample 查询：

```c
typedef struct
{
    uint8_t type_filter;          // 0=ALL, 1=TASK, 2=INTERRUPT, 3=CODE
    uint8_t flags;
    uint16_t reserved;
    uint32_t dict_version;
} perf_sample_query_t;

typedef struct
{
    uint8_t accepted;
    uint8_t type_filter;
    uint16_t record_count;
    uint32_t sequence;
    uint32_t dict_version;
    uint8_t reject_reason;
    uint8_t reserved[3];
} perf_sample_ack_t;

typedef struct
{
    uint32_t sequence;
    uint16_t record_count;
    uint16_t item_count;
} perf_sample_batch_header_t;

typedef struct
{
    uint16_t record_id;
    uint32_t time_us;
    uint32_t max_time_us;
    uint32_t period_us;
    float load_percent;
    float peak_percent;
} perf_sample_task_item_t;

typedef struct
{
    uint16_t record_id;
    uint32_t time_us;
    uint32_t max_time_us;
    float load_percent;
    float peak_percent;
} perf_sample_interrupt_item_t;

typedef struct
{
    uint16_t record_id;
    uint32_t time_us;
    uint32_t max_time_us;
} perf_sample_code_item_t;

typedef struct
{
    uint32_t sequence;
    uint16_t record_count;
    uint8_t status;
    uint8_t reserved;
} perf_sample_end_t;
```

Perf 上报控制：

```c
typedef struct
{
    uint8_t enable;      // 0=停止 Perf 上报，1=开始 Perf 上报
} perf_control_t;

typedef struct
{
    uint8_t success;     // 0=失败，1=成功
} perf_control_ack_t;
```

当前 Perf 协议约束如下：

- `record_id` 在同一个 `dict_version` 内必须稳定。
- 记录数量、顺序、类型或名称变化时，下位机需要更新 `dict_version`。
- 上位机没有字典时会先拉取 ALL 字典，再拉取当前筛选类型的 sample。
- 周期查询固定 1s，每轮发送 `0x21` 和 `0x29`。
- `load_percent` 和 `peak_percent` 保持 `float32`，不做整数缩放。
- CODE 没有占用率概念，不携带 `load_percent / peak_percent / period_us`。
- INTERRUPT 不携带 `period_us`。
- 上位机每次手动拉取或周期拉取记录时都会自动发送 `0x21` 更新总占用率，页面不提供单独的 Summary 按钮。
- 上位机在打开串口、关闭串口和退出程序时会以广播地址 `dst = 0x00, d_dst = 0x00` 发送 `0x2E enable=0` 停止设备侧 Perf 上报
- `0x2E` 广播停止命令可以不回 ACK，避免多个设备同时 ACK 撞包
- 若未来下位机收到非广播 `0x2E` 并决定回 ACK，上位机期望 ACK payload 至少包含 `success:uint8`，`1` 表示成功

##### Trace 代码执行跟踪协议 `0x01 / 0x2C ~ 0x2D`

Trace 用于接收下位机逐条上报的代码执行时间点和代码行号，适合观察某段代码路径的运行顺序和时间间隔。

| `cmd_word` | 方向 | 用途 | 说明 |
| --- | --- | --- | --- |
| `0x2C` | PC -> 设备 / ACK | Trace 上报启停控制 | 上位机发送 enable，下位机 ACK 返回运行状态和时间单位 |
| `0x2D` | 设备 -> PC | Trace 单条记录上报 | 一帧只携带一条 `{time, line}` 记录 |

启停控制请求：

```c
typedef struct
{
    uint8_t enable;      // 0=停止上报，1=开始上报
} trace_control_t;
```

启停控制 ACK：

```c
typedef struct
{
    uint8_t success;     // 0=失败，1=成功
    uint8_t running;     // 0=已停止，1=上报中
    uint16_t time_unit_us;
} trace_control_ack_t;
```

单条记录上报：

```c
typedef struct
{
    uint32_t time;
    uint16_t line;
} trace_record_report_t;
```

字段说明：

- `time_unit_us` 由下位机在 `0x2C` ACK 中返回，`100` 表示 `time` 单位为 100us，`1000` 表示 `time` 单位为 1ms
- 上位机换算真实时间时使用 `time_us = time * time_unit_us`
- 下位机只逐条上报 `0x2D`，不做批量上报
- 该协议结构体不设置保留位；后续扩展只允许在结构体尾部追加字段
- 数据兼容依赖协议 `data_len` 与本地结构体实际大小取小解析，不依赖固定版本号

#### 2.9.2 `cmd_set = 0x02`

当前主要用于主页广播数据。主页页签中的交流侧、电池、MPPT、状态、故障和告警区域均依赖该广播更新。

```c
typedef struct
{
    float mppt_vin;
    float mppt_iin;
    float mppt_pwr;
    float ac_v_grid;
    float ac_i_grid;
    float ac_freq_grid;
    float ac_pwr_grid;
    float ac_v_inv;
    float ac_i_inv;
    float ac_pwr_inv;
    float ac_freq_inv;
    float pfc_temp;
    float llc_temp1;
    float llc_temp2;
    uint8_t fan_sta;
    uint32_t protect;
    uint32_t fault;
    uint32_t warning;
    float bat_volt;
    float bat_curr;
    float bat_pwr;
    float bat_temp;
    float soc;
} pcs_info_t;
```

#### 2.9.3 `cmd_set = 0x03`

当前主要用于主页设置区中的逆变输出配置。

```c
typedef struct
{
    uint8_t ac_out_enable_trig;
    uint8_t ac_out_disable_trig;
    uint8_t ac_out_rms;
    uint8_t ac_out_freq;
} inv_cfg_t;
```

## 3. 分页功能说明

以下各分页均按统一模板描述：

- 设计内容和意图
- 功能范围
- 设计方法
- 通信协议
- 操作使用说明
- 注意事项

### 3.1 主页

#### 3.1.1 设计内容和意图

主页用于集中展示设备运行状态，并提供少量高频配置入口，使用户在打开软件后无需进入其他页面即可快速了解当前设备运行情况。

#### 3.1.2 功能范围

- 负责展示电网、输出、电池、MPPT、温度、状态、故障和告警信息
- 负责展示和下发 AC 输出配置
- 不负责参数级读写
- 不负责历史数据查看

#### 3.1.3 设计方法

- 采用广播驱动刷新方式更新大部分数值
- 将实时状态展示与主动配置操作分区设计
- 故障与告警文本区域使用滚动文本框，兼顾信息量与可读性

#### 3.1.4 通信协议

- 使用 `cmd_set = 0x02` 广播状态数据
- 使用 `cmd_set = 0x03` 读写逆变输出配置

#### 3.1.5 操作使用说明

1. 打开串口后等待设备广播状态
2. 观察主页各区域数值与状态点
3. 如需修改 AC 输出设置，在设置区选择输出配置并发送
4. 如需打开或关闭 AC 输出，点击对应按钮

#### 3.1.6 注意事项

- 主页数据主要依赖广播更新，广播停止时页面会保持最后一次有效值
- 故障和告警文案依赖设备上报与上位机映射表

### 3.2 串口调试页

#### 3.2.1 设计内容和意图

串口调试页用于提供原始串口收发能力，便于做协议验证、故障抓包和临时联调。

#### 3.2.2 功能范围

- 负责文本与 HEX 发送
- 负责文本与 HEX 接收显示
- 负责定时发送、快捷发送和接收持续保存
- 不负责业务协议逻辑解释

#### 3.2.3 设计方法

- 将原始接收区和发送区分离
- 左侧提供调试设置，右侧提供收发文本区
- 快捷发送使用本地配置文件持久化

#### 3.2.4 通信协议

- 本页不绑定某个固定业务协议
- 主要服务于原始串口字节流发送与接收

#### 3.2.5 操作使用说明

1. 选择串口参数并打开串口
2. 在发送框输入文本或 HEX
3. 点击发送或启用定时发送
4. 如需保存接收流，打开“接收保存到文件”

#### 3.2.6 注意事项

- 在原始调试时发送业务命令可能影响其他分页的协议状态
- HEX 模式下需保证输入格式正确

### 3.3 参数读写页

#### 3.3.1 设计内容和意图

参数读写页用于展示设备可读写参数，并支持单参数读取、写入和命令型参数执行。

#### 3.3.2 功能范围

- 负责参数列表读取
- 负责单参数读取与写入
- 负责波形勾选状态设置
- 不负责参数趋势图绘制

#### 3.3.3 设计方法

- 参数以表格方式展示
- 支持搜索、当前行操作和脏数据标记
- 写入前检查范围，减少非法值下发

#### 3.3.4 通信协议

- `0x01 / 0x01` 参数总数读取
- `0x01 / 0x02` 单参数读取
- `0x01 / 0x03` 单参数写入 / 执行
- `0x01 / 0x04` 参数列表项
- `0x01 / 0x05` 波形勾选

#### 3.3.5 操作使用说明

1. 先读取参数列表
2. 在参数表中搜索目标参数
3. 选择读取、写入或执行
4. 如需参与参数波形上报，可勾选波形显示

#### 3.3.6 注意事项

- 读取参数列表前会先发送停止发波命令
- 命令型参数与普通参数共用同一写入协议，但界面含义不同

### 3.4 参数波形页

#### 3.4.1 设计内容和意图

参数波形页用于展示设备实时上报的参数趋势，适合观察连续变化过程和现场波形状态。

#### 3.4.2 功能范围

- 负责参数实时波形显示
- 负责波形导入导出
- 负责标记、参考线、缩放和悬浮读数
- 不负责录波对象化抓取

#### 3.4.3 设计方法

- 使用本地缓存保存实时上报点
- 支持窗口时间切换与历史查看
- 将实时查看与交互分析放在同一页面内

#### 3.4.4 通信协议

- `0x01 / 0x05` 波形勾选
- `0x01 / 0x06` 上报周期设置
- `0x01 / 0x07` 波形数据上报
- `0x01 / 0x0C` 发波开始 / 停止

#### 3.4.5 操作使用说明

1. 在参数页勾选需要显示的参数
2. 进入参数波形页开始发波
3. 调整时间窗口或暂停显示
4. 使用参考线、缩放和导出功能分析数据

#### 3.4.6 注意事项

- 本页是实时波形，不等同于 Scope 本地录波
- 发波过程中读取参数列表会导致实时波形停止

### 3.5 软件录波 Scope 页

#### 3.5.1 设计内容和意图

软件录波页用于与下位机本地 RAM 录波功能联调，适合观察一次完整触发过程中的离散采样结果。

#### 3.5.2 功能范围

- 负责枚举录波对象
- 负责读取录波对象状态与变量名
- 负责开始、触发、停止、复位录波
- 负责常规拉取与强制拉取
- 负责本地录波缓存、预览与 CSV 导出
- 不负责实时流式趋势显示

#### 3.5.3 设计方法

- 录波对象以 `scope_id` 编址
- 变量名逐项读取，避免长表头一次性传输
- 采样值按单点轮询方式读取，降低串口长期占用
- 抓取完成后缓存为本地录波包，支持多包叠加分析

#### 3.5.4 通信协议

- `0x01 / 0x18` 查询录波对象列表
- `0x01 / 0x19` 查询对象状态信息
- `0x01 / 0x1A` 查询变量名
- `0x01 / 0x1B` 开始录波
- `0x01 / 0x1C` 触发录波
- `0x01 / 0x1D` 停止录波
- `0x01 / 0x1E` 复位录波
- `0x01 / 0x1F` 单采样点拉取

#### 3.5.5 操作使用说明

1. 刷新录波对象
2. 选择录波对象并刷新状态
3. 读取变量名
4. 开始录波并在合适时机触发
5. 录波完成后执行普通拉取；如需运行中查看则执行强制拉取
6. 在本地录波列表中选择显示 / 隐藏、导出 CSV 或删除

#### 3.5.6 注意事项

- 普通拉取要求对象处于空闲且 `data_ready = 1`
- 强制拉取允许运行过程中查看，但数据可能是中间态
- 拉取过程中若 `capture_tag` 变化，说明设备侧录波包已切换

### 3.6 固件升级页

#### 3.6.1 设计内容和意图

固件升级页用于加载本地固件、查看文件版本与设备版本，并执行在线升级。

#### 3.6.2 功能范围

- 负责固件文件加载与解析
- 负责设备版本查询
- 负责升级过程控制与日志显示
- 不负责运行时参数调试

#### 3.6.3 设计方法

- 采用阶段式升级状态机
- 将文件信息、设备信息、进度与日志分区展示
- 对 PFC 升级增加 LLC -> PFC 转发进度追踪

#### 3.6.4 通信协议

- `0x01 / 0x08 ~ 0x0B` 升级主流程
- `0x01 / 0x0D` LLC -> PFC 转发进度查询
- `0x01 / 0x17` 固件版本查询

#### 3.6.5 操作使用说明

1. 加载固件文件
2. 查看文件版本和设备版本
3. 设置目标地址与升级类型
4. 开始升级并观察日志与进度

#### 3.6.6 注意事项

- 升级中不可断串口或断电
- 目标模块为 PFC 时，升级完成判定晚于 `0x0B ACK`

### 3.7 Black Box 页

#### 3.7.1 设计内容和意图

Black Box 页用于按逻辑偏移范围读取历史记录，并以表格方式查看和导出。

#### 3.7.2 功能范围

- 负责范围查询
- 负责表头与行数据解析
- 负责 CSV 导出
- 不负责实时广播或实时录波

#### 3.7.3 设计方法

- 采用 `start_offset + read_length` 方式查询
- 表头和行数据采用颗粒化上传
- 完成帧用于标识本次查询结束及是否存在更多数据

#### 3.7.4 通信协议

- `0x01 / 0x0E` 范围查询
- `0x01 / 0x0F` 表头上传
- `0x01 / 0x10` 行数据上传
- `0x01 / 0x11` 查询完成通知

#### 3.7.5 操作使用说明

1. 输入起始偏移与读取长度
2. 点击开始查询
3. 等待表头、数据行和完成通知
4. 如需保存，导出为 CSV

#### 3.7.6 注意事项

- 查询范围越大，等待时间越长
- 记录可跨 sector 解析，不以 Flash sector 为记录边界

### 3.8 Factory Mode 页

#### 3.8.1 设计内容和意图

Factory Mode 页用于执行设备出厂维护相关操作，包括时间设置与校准管理。

#### 3.8.2 功能范围

- 负责设备时间读取与写入
- 负责时区配置
- 负责校准项读取、写入和保存
- 不负责一般运行参数管理

#### 3.8.3 设计方法

- 时间区与校准区分离
- 校准项以自然语言名称呈现，避免直接暴露枚举值
- 使用独立输入地址支持不同模块校准

#### 3.8.4 通信协议

- `0x01 / 0x12 ~ 0x13` 工厂模式时间协议
- `0x01 / 0x14 ~ 0x16` 工厂模式校准协议

#### 3.8.5 操作使用说明

1. 读取设备时间
2. 如有需要，设置当前 PC 的 UTC 时间
3. 选择校准项并读取当前增益与偏置
4. 修改后写入并保存到 Flash

#### 3.8.6 注意事项

- 时间写入使用 UTC 原始时间，不是本地时区时间
- 保存校准到 Flash 前应确认目标地址和参数无误

### 3.9 Perf 任务时间页

#### 3.9.1 设计内容和意图

Perf 任务时间页用于查看下位机任务、中断和代码片段的运行耗时，定位 CPU 占用、峰值耗时和任务周期异常。

#### 3.9.2 功能范围

- 负责展示 TASK、INTERRUPT、CODE 三类记录
- 负责展示 TASK/INTERRUPT 当前占用率和峰值占用率
- 负责展示 TASK 运行周期 `period_us`
- 负责展示 CODE 当前运行时间和最大运行时间
- 支持 ALL/TASK/INTERRUPT/CODE 筛选
- 支持 1s 周期查询、搜索和 CSV 导出

#### 3.9.3 设计方法

- 使用类似任务管理器的深色表格界面
- 使用字典 + sample 的二进制协议降低周期查询数据量
- 字典缓存名称、类型和记录 ID，sample 只刷新高频变化数值
- 打开串口后进入 Perf 页会自动同步字典，用户第一次拉取时不需要手动做准备动作
- Records 表格采用增量更新，避免周期刷新时闪烁
- 选中项详情区使用重叠占用率条展示当前值和峰值

#### 3.9.4 通信协议

- `0x01 / 0x20` Perf 信息查询
- `0x01 / 0x21` TASK/INTERRUPT 总占用率查询
- `0x01 / 0x25` 重置峰值
- `0x01 / 0x26 ~ 0x28` Perf 字典查询和上报
- `0x01 / 0x29 ~ 0x2B` Perf sample 查询和批量上报
- `0x01 / 0x2E` Perf 上报控制，当前用于广播停止

旧的 `0x01 / 0x22 ~ 0x24` Perf 列表协议已删除，不再兼容。

#### 3.9.5 操作使用说明

1. 打开串口并进入 Perf 页
2. 上位机会自动同步 Perf 信息和字典
3. 选择 ALL/TASK/INTERRUPT/CODE
4. 点击拉取按钮手动刷新
5. 如需连续观察，点击自动刷新 1s
6. 周期查询中可继续切换 ALL/TASK/INTERRUPT/CODE
7. 选中 Records 中任意一行查看详情
8. 如需保存结果，导出 CSV

#### 3.9.6 注意事项

- 首次拉取会先拉取字典，因此首包数据量会大于后续周期 sample
- 若下位机返回的 `dict_version` 变化，或 sample ACK 返回 `reject_reason = 5`，上位机会自动重新拉取字典
- 上位机 Records 表格内部以 `record_id` 作为稳定键，避免同名记录、筛选切换和周期刷新时误删误更新
- CODE 没有占用率概念，Load 和 Peak 显示为 `-`
- 周期查询不会停止参数波形

### 3.10 Trace 代码执行跟踪页

#### 3.10.1 设计内容和意图

Trace 代码执行跟踪页用于接收下位机运行过程中主动上报的代码行号和时间点，帮助定位代码路径、执行顺序和相邻事件间隔。

#### 3.10.2 功能范围

- 负责 Trace 上报开始 / 停止控制
- 负责展示逐条 Trace 记录
- 负责按行号搜索并高亮 Records 中已有记录
- 负责展示事件总数、最后时间、最后行号、接收速率和时间单位
- 负责左侧控制与统计、右侧 Records 表格的左右分栏布局

#### 3.10.3 设计方法

- 左侧面板集中放置 Target、Dyn、开始 / 停止、行号搜索、状态和统计卡片
- 右侧面板专门展示 Trace Records
- 页面保持一个主控制按钮，按钮状态在开始上报和停止上报之间切换
- 下位机 ACK 返回 `time_unit_us` 后，上位机按该单位换算记录时间
- Records 表格显示序号、换算时间和行号，不显示原始 `time_tick` 和 Delta
- 用户输入十进制或 `0x` 十六进行号时高亮匹配行
- Trace 页不展示时间线和选中项详情，避免挤占 Records 表格空间

#### 3.10.4 通信协议

- `0x01 / 0x2C` Trace 上报启停控制
- `0x01 / 0x2D` Trace 单条记录上报

#### 3.10.5 操作使用说明

1. 打开串口并进入 Trace 页
2. 设置 Target 和 Dyn 地址
3. 点击开始上报
4. 下位机运行过程中逐条上报 Trace 记录
5. 输入行号搜索并高亮匹配记录
6. 点击停止上报结束 Trace

#### 3.10.6 注意事项

- Trace 不做批量上报，一帧只携带一条记录
- 若未收到 `0x2C` 成功 ACK，上位机不进入运行状态
- 上位机仅在 Trace 运行状态下写入 Records，避免停止后残留上报污染当前观察窗口

## 4. 页面与协议映射

### 4.1 页面与指令映射表

| 页面 | 协议用途 | 指令范围 |
| --- | --- | --- |
| 主页 | 状态广播、逆变配置 | `cmd_set = 0x02`，`cmd_set = 0x03` |
| 串口调试页 | 原始串口透传 | 不绑定单一业务协议 |
| 参数读写页 | 参数列表、读写、波形勾选 | `0x01 / 0x01 ~ 0x05` |
| 参数波形页 | 波形勾选、周期设置、实时上报、启停 | `0x01 / 0x05 ~ 0x07, 0x0C` |
| Scope 页 | 软件录波对象控制与抓取 | `0x01 / 0x18 ~ 0x1F` |
| 固件升级页 | 升级、版本查询、转发进度 | `0x01 / 0x08 ~ 0x0D, 0x17` |
| Black Box 页 | 范围查询、表头、行数据、完成通知 | `0x01 / 0x0E ~ 0x11` |
| Factory Mode 页 | 时间、校准 | `0x01 / 0x12 ~ 0x16` |
| Perf 任务时间页 | 任务、中断、代码片段耗时统计 | `0x01 / 0x20 ~ 0x2B, 0x2E` |
| Trace 代码执行跟踪页 | 代码行号执行跟踪上报 | `0x01 / 0x2C ~ 0x2D` |

### 4.2 页面与代码模块映射表

| 页面 | UI 文件 | 控制逻辑 | 协议文件 |
| --- | --- | --- | --- |
| 主页 | `ui/home_tab.py` | `ui/app.py` | `protocol.py` |
| 串口调试页 | `ui/monitor_tab.py` | `ui/app.py` | `protocol.py` |
| 参数读写页 | `ui/parameter_tab.py` | `ui/app.py` | `protocol.py` |
| 参数波形页 | `ui/wave_tab.py` | `ui/app.py` | `protocol.py` |
| Scope 页 | `ui/scope_tab.py` | `ui/app.py` | `scope_protocol.py` |
| 固件升级页 | `ui/upgrade_tab.py` | `ui/app.py` | `firmware_update.py` |
| Black Box 页 | `ui/black_box_tab.py` | `ui/app.py` | `black_box_protocol.py` |
| Factory Mode 页 | `ui/factory_mode_tab.py` | `ui/app.py` | `factory_mode.py` |
| Perf 任务时间页 | `ui/perf_tab.py` | `ui/app.py` | `perf_protocol.py` |
| Trace 代码执行跟踪页 | `ui/trace_tab.py` | `ui/app.py` | `trace_protocol.py` |

## 5. 数据结构汇总

### 5.1 总帧结构

- `section_packform_t`

### 5.2 参数相关结构

- `cmd_0101_ack_t`
- `cmd_0102_req_t`
- `cmd_0102_ack_t`
- `cmd_0103_req_t`
- `cmd_0103_ack_t`
- `cmd_0104_item_t`
- `cmd_0105_req_t`
- `cmd_0105_ack_t`
- `cmd_0106_req_t`
- `cmd_0107_report_t`

### 5.3 波形相关结构

- `cmd_0106_req_t`
- `cmd_0107_report_t`

### 5.4 Scope 相关结构

- `scope_list_item_t`
- `scope_info_ack_t`
- `scope_var_query_t`
- `scope_var_ack_t`
- `scope_ctrl_ack_t`
- `scope_sample_query_t`
- `scope_sample_ack_t`

### 5.5 升级相关结构

- `cmd_0108_req_t`
- `cmd_0108_ack_t`
- `cmd_0109_ack_t`
- `cmd_010A_req_t`
- `cmd_010A_ack_t`
- `cmd_010B_req_t`
- `cmd_010B_ack_t`
- `llc_pfc_upgrade_progress_ack_t`
- `firmware_version_ack_t`
- `footer_t`

### 5.6 Black Box 相关结构

- `black_box_range_query_req_t`
- `black_box_range_query_ack_t`
- `black_box_header_report_t`
- `black_box_row_report_t`
- `black_box_range_complete_report_t`

### 5.7 Factory Mode 相关结构

- `factory_time_payload_t`
- `cali_query_t`
- `cali_info_t`

### 5.8 Perf 相关结构

- `perf_info_ack_t`
- `perf_summary_ack_t`
- `perf_dict_query_t`
- `perf_dict_ack_t`
- `perf_dict_item_t`
- `perf_dict_end_t`
- `perf_sample_query_t`
- `perf_sample_ack_t`
- `perf_sample_batch_header_t`
- `perf_sample_task_item_t`
- `perf_sample_interrupt_item_t`
- `perf_sample_code_item_t`
- `perf_sample_end_t`

### 5.9 Trace 相关结构

- `trace_control_t`
- `trace_control_ack_t`
- `trace_record_report_t`

## 6. 状态机与时序说明

### 6.1 参数列表读取流程

1. 上位机先发送停止波形上传命令
2. 请求参数总数
3. 连续接收参数列表项
4. 更新参数表格

### 6.2 参数波形启停流程

1. 上位机设置周期
2. 上位机发送开始发波
3. 设备连续上报波形批次
4. 上位机缓存并绘制
5. 上位机发送停止发波

### 6.3 Scope 录波流程

1. 枚举录波对象
2. 读取对象状态与变量名
3. 上位机下发开始录波
4. 在合适时机下发触发
5. 录波完成后执行普通拉取或运行中执行强制拉取
6. 上位机按 `sample_index` 逐点拉取样本
7. 本地生成录波包并显示

### 6.4 Black Box 查询流程

1. 上位机发送范围查询
2. 设备返回 ACK
3. 设备逐项上传表头
4. 设备逐行上传记录
5. 设备发送完成通知

### 6.5 固件升级流程

1. 加载固件
2. 下发升级信息
3. 轮询 ready
4. 按包发送数据
5. 下发结束命令
6. 如目标为 PFC，则继续查询 LLC -> PFC 进度

### 6.6 工厂模式流程

- 时间读取 / 写入采用单次请求-应答模式
- 校准读取 / 写入 / 保存采用分步操作

### 6.7 Perf 任务时间流程

首次拉取流程：

1. 用户选择 ALL/TASK/INTERRUPT/CODE
2. 上位机发送 `0x21` 更新 TASK/INTERRUPT 总占用率
3. 上位机发送 `0x20` 查询 Perf 信息
4. 若本地没有字典，上位机发送 `0x26` 查询 ALL 字典
5. 下位机通过 `0x27` 逐项上报字典
6. 下位机通过 `0x28` 通知字典结束
7. 上位机发送 `0x29` 查询当前筛选类型 sample
8. 下位机通过 `0x2A` 批量上报 sample
9. 下位机通过 `0x2B` 通知 sample 结束

周期查询流程：

1. 周期固定 1s
2. 上位机发送 `0x21` 更新 TASK/INTERRUPT 总占用率
3. 上位机发送 `0x29` 查询当前筛选类型 sample
4. 下位机通过 `0x2A` 和 `0x2B` 完成本轮 sample 上报
5. 若 sample ACK 的 `dict_version` 与上位机缓存不同，则重新执行字典拉取流程

### 6.8 Trace 代码执行跟踪流程

启动流程：

1. 用户点击开始上报
2. 上位机发送 `0x01 / 0x2C`，payload 中 `enable = 1`
3. 下位机 ACK 返回 `success / running / time_unit_us`
4. 上位机清空当前 Trace Records，并保存 `time_unit_us`
5. 下位机运行过程中逐条发送 `0x01 / 0x2D`
6. 上位机按接收顺序追加记录，并刷新表格和搜索高亮

停止流程：

1. 用户点击停止上报
2. 上位机发送 `0x01 / 0x2C`，payload 中 `enable = 0`
3. 下位机 ACK 返回停止状态
4. 上位机退出 Trace 运行状态，停止向 Records 写入后续 Trace 上报

## 7. 操作说明汇总

### 7.1 首次连接设备

1. 选择串口
2. 配置串口参数
3. 打开串口
4. 检查底部状态栏和主页状态是否更新

### 7.2 参数读取

1. 进入参数读写页
2. 读取参数列表
3. 搜索目标参数
4. 读取或写入

### 7.3 参数波形使用

1. 在参数页勾选波形参数
2. 进入参数波形页
3. 启动发波
4. 查看曲线，必要时导出

### 7.4 Scope 使用

1. 进入 Scope 页
2. 刷新对象
3. 读取对象状态和变量名
4. 开始录波、触发录波
5. 普通拉取或强制拉取
6. 本地查看和导出 CSV

### 7.5 Black Box 使用

1. 输入起始偏移和读取长度
2. 开始查询
3. 等待完成
4. 导出 CSV

### 7.6 固件升级使用

1. 加载固件文件
2. 检查版本信息
3. 设置目标地址和升级类型
4. 开始升级并等待完成

### 7.7 工厂模式使用

1. 读取设备时间
2. 如有需要，下发当前 PC UTC 时间
3. 选择校准项并读取
4. 写入增益 / 偏置后保存

### 7.8 Perf 任务时间使用

1. 打开串口并进入 Perf 页
2. 选择 ALL/TASK/INTERRUPT/CODE
3. 点击对应拉取按钮刷新记录
4. 点击自动刷新 1s 可周期查询
5. 周期查询中可以继续切换筛选类型
6. 选中记录查看详情
7. 必要时导出 CSV

### 7.9 Trace 代码执行跟踪使用

1. 打开串口并进入 Trace 页
2. 设置 Target 和 Dyn 地址
3. 点击开始上报
4. 观察 Records 表格
5. 在搜索框输入行号，高亮已有匹配记录
6. 点击停止上报结束本轮 Trace

## 8. 注意事项与维护规则

### 8.1 串口相关

- 打开串口后，多个分页共享同一底层串口服务
- 原始串口调试页发送数据可能影响业务分页状态

### 8.2 参数相关

- 读取参数列表前建议停止实时波形上传
- 写入值应满足上下限约束

### 8.3 波形相关

- 参数波形适合连续趋势观察
- Scope 适合一次完整触发后的离散录波分析

### 8.4 Scope 相关

- 普通拉取要求数据就绪
- 强制拉取可能读到运行中缓冲区
- 录波拉取采用单点轮询，不追求高速连续传输

### 8.5 升级相关

- 升级期间不可断电、断串口
- PFC 升级完成判定依赖 LLC -> PFC 转发结果

### 8.6 Black Box 相关

- 查询范围越大耗时越长
- 记录解析边界由记录头决定，不由 sector 边界决定

### 8.7 Factory Mode 相关

- 时间写入采用 UTC 原始值
- 保存校准到 Flash 前需确认目标模块与参数无误

### 8.8 Perf 相关

- 首次拉取会拉 ALL 字典，后续周期查询只拉 sample
- 下位机应在字典变化时更新 `dict_version`
- CODE 不具备占用率语义，不应显示 Load / Peak
- Perf 周期查询不应停止参数波形

### 8.9 Trace 相关

- Trace 上报是一帧一条记录，不做批量传输
- Trace 时间单位由 `0x2C` ACK 的 `time_unit_us` 决定，上位机不写死时间单位
- Trace 协议结构体不设置保留位，后续字段只能追加到结构体尾部
- 协议数据兼容按 `copy_len = min(data_len, sizeof(local_struct))` 取小解析
- Trace 二进制协议只负责上位机页面接收和显示，不改变下位机既有 shell 调试机制

### 8.10 小功能增加时如何补文档

- 若新增协议，先补第 2 章
- 若新增某页小功能，补第 3 章对应分页小节
- 若影响用户操作，再补第 7 章
- 若新增限制或坑点，再补第 8 章

### 8.11 新分页增加时如何补文档

- 在第 3 章新增分页章节
- 在第 4 章补映射表
- 在第 2 章补对应协议
- 在第 7 章补操作说明

### 8.12 协议修改时如何补文档

- 改结构体必须同步更新结构体定义和字段含义
- 改状态码必须同步更新相关章节和注意事项
- 改时序必须同步更新第 6 章

### 8.13 变更记录

| 日期 | 模块 | 类型 | 说明 |
| --- | --- | --- | --- |
| 2026-05-01 | Trace 代码执行跟踪 | 新增 | 新增 Trace 页设计和 `0x2C / 0x2D` 二进制上报协议说明 |
| 2026-04-30 | Perf 任务时间 | 更新 | 新增 Perf 页设计、字典 + sample 协议说明，并移除旧 Perf 列表协议兼容描述 |
| 2026-04-21 | 文档结构 | 重构 | 将旧版目录说明式文档重构为协议章节 + 分页章节结构 |
