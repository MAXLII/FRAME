# 工程设计

## 工程目录

```text
FRAME/
├─ bl_llc/
├─ docs/
│  ├─ AI_WORK_RULES.md
│  ├─ ENGINEERING_DESIGN.md
│  └─ homepage_ui_redesign_brief_for_codex.md
├─ installer/
│  └─ frame_installer.iss
├─ llc/
├─ serial_debug_assistant/
│  ├─ app_paths.py
│  ├─ constants.py
│  ├─ debug_logger.py
│  ├─ firmware_update.py
│  ├─ models.py
│  ├─ protocol.py
│  ├─ __init__.py
│  ├─ __main__.py
│  ├─ services/
│  │  ├─ __init__.py
│  │  └─ serial_service.py
│  └─ ui/
│     ├─ __init__.py
│     ├─ app.py
│     ├─ black_box_tab.py
│     ├─ debug_tab.py
│     ├─ factory_mode_tab.py
│     ├─ home_tab.py
│     ├─ monitor_tab.py
│     ├─ parameter_tab.py
│     ├─ upgrade_tab.py
│     └─ wave_tab.py
├─ build_frame_exe.bat
├─ build_frame_installer.bat
├─ clean_build_artifacts.bat
├─ main.py
├─ README.md
├─ requirements.txt
└─ run_serial_debug_assistant.bat
```

## 工程分层

### 启动入口层

- `main.py` 作为桌面程序启动入口，负责调用 `serial_debug_assistant.ui.app.launch_app`。
- `serial_debug_assistant/__main__.py` 提供包级启动入口，入口行为与 `main.py` 保持一致。
- `run_serial_debug_assistant.bat` 负责创建虚拟环境、安装依赖并启动桌面程序。

### 构建发布层

- `build_frame_exe.bat` 负责准备虚拟环境、安装 `PyInstaller`、清理构建输出目录并生成 `dist/frame/frame.exe`。
- `build_frame_installer.bat` 负责串联目录版构建和安装包编译流程。
- `build_dr_ssip_monitor_installer.bat` 负责复用 `FRAME` 目录版产物并生成 `DR_SSIP_Monitor` 命名安装包。
- `installer/frame_installer.iss` 定义 Windows 安装包的安装目录、快捷方式、卸载入口和覆盖升级行为。
- `clean_build_artifacts.bat` 负责清理构建目录、缓存目录和 Python 编译产物。

### 应用包层

- `serial_debug_assistant/` 承载串口调试助手的运行时路径、协议处理、固件升级、串口服务和界面组件。

## 顶层文件与目录职责

### 文档目录

- `docs/AI_WORK_RULES.md` 定义本仓库的 AI 执行规则、Git 提交规则和工程设计文档编写规则。
- `docs/ENGINEERING_DESIGN.md` 说明本工程当前目录和模块设计。
- `docs/homepage_ui_redesign_brief_for_codex.md` 记录主页 UI 重设计的目标、输入来源和界面原则。

### 参考资料

- `README.md` 说明工程用途、运行方式和打包方式。
- 仓库根目录中的 PDF 文件作为协议和界面设计参考资料。

## `serial_debug_assistant` 包设计

### 路径与运行环境

- `app_paths.py` 统一计算源码运行和安装运行两种模式下的安装目录与数据目录。
- `app_paths.py` 负责创建 `config/`、`exports/`、`logs/` 运行数据目录，并处理旧版快捷发送配置、导出文件与调试日志的迁移。
- 源码运行模式默认使用仓库根目录作为数据根目录，安装运行模式默认使用 `%LOCALAPPDATA%\FRAME\` 作为数据根目录。
- `constants.py` 定义应用版本、窗口尺寸、接收轮询周期、串口默认参数和串口参数选项。

### 公共数据模型

- `models.py` 定义串口接收块、协议帧、参数项、固件尾部、固件镜像和升级会话的数据结构。

### 协议与业务计算

- `protocol.py` 定义帧结构常量、CRC16 计算、协议帧打包、协议帧解析和参数数值类型转换。
- `firmware_update.py` 定义固件尾部解析、CRC32 校验、版本格式化、模块名称映射和升级报文载荷构造。
- `debug_logger.py` 定义应用日志写入器，并提供日志订阅回调分发能力。

### PDF 参考协议补充

仓库根目录中的 `通信.pdf` 与 `上位机.pdf` 目前仍是理解本工程协议来源的重要参考资料。当前代码实现与工程设计文档应以源码为准，但下面这些协议结构体和字段定义仍然值得保留，便于后续联调、扩展和与下位机文档核对。

#### 总帧格式（来自 `通信.pdf`）

`通信.pdf` 定义了一个以 `0xE8` 为起始符、以 `0x0A0D` 为结束符的轻量级通信帧，等价结构如下：

```c
#pragma pack(1)
typedef struct
{
    uint8_t sop;      // 固定 0xE8
    uint8_t version;  // 协议版本
    uint8_t src;      // 源地址
    uint8_t d_src;    // 动态源地址
    uint8_t dst;      // 目的地址
    uint8_t d_dst;    // 动态目的地址
    uint8_t cmd_set;  // 命令集
    uint8_t cmd_word; // 命令字
    uint8_t is_ack;   // 是否为响应帧
    uint16_t len;     // payload 长度
    uint8_t *p_data;  // payload 起始地址
    uint16_t crc;     // 从 sop 到 p_data 的 CRC16
    uint16_t eop;     // 固定 0x0A0D
} section_packform_t;
```

字段约定如下：

| 字段 | 长度 | 含义 | 备注 |
| --- | --- | --- | --- |
| `sop` | 1B | 起始符 | 固定为 `0xE8` |
| `version` | 1B | 协议版本号 | 当前 PDF 示例为 `0x01` |
| `src` | 1B | 源设备地址 | 例如上位机地址 |
| `d_src` | 1B | 动态源地址 | 用于地址扩展 |
| `dst` | 1B | 目的设备地址 | 例如下位机模块地址 |
| `d_dst` | 1B | 动态目的地址 | 用于地址扩展 |
| `cmd_set` | 1B | 命令集分类 | `0x01/0x02/0x03` 等 |
| `cmd_word` | 1B | 具体命令字 | 同一命令集下的子命令 |
| `is_ack` | 1B | 请求/响应标记 | `0` 为请求，`1` 为响应 |
| `len` | 2B | 数据长度 | 仅表示 payload 字节数 |
| `p_data` | 变长 | 数据载荷 | 必须按 1 字节对齐理解 |
| `crc` | 2B | 帧内 CRC16 | 覆盖范围为 `sop..payload` |
| `eop` | 2B | 结束符 | 固定为 `0x0A0D` |

PDF 中给出的示例帧如下：

```text
E8 01 10 00 20 00 01 02 04 00 01 02 03 04 A3 C4 0D 0A
```

#### CRC 约定（来自 `通信.pdf`）

- 通信帧校验采用 `CRC-16-CCITT`。
- 多项式为 `0x1021`。
- 初始值为 `0xFFFF`。
- 计算范围为从 `sop` 开始到 payload 最后一个字节结束，不包含帧尾 `crc` 和 `eop`。
- 当前代码中的 `protocol.py` 已按同类思路实现 CRC16 计算与验帧流程。

## `cmd_set = 0x01` 指令集

当前工程中，`cmd_set = 0x01` 主要承载参数读写、波形配置与波形上报相关协议，收发逻辑集中在 `serial_debug_assistant/ui/app.py`。

| `cmd_word` | 方向 | 用途 | 载荷结构 |
| --- | --- | --- | --- |
| `0x01` | PC -> 设备 | 请求参数列表总数 | 空载荷 |
| `0x01` | 设备 -> PC，`is_ack = 1` | 返回参数总数 | `uint32 total_count` |
| `0x02` | PC -> 设备 | 按参数名读取单个参数 | `name_len(1B) + name(UTF-8)` |
| `0x02` | 设备 -> PC，`is_ack = 1` | 返回单个参数当前值 | `name_len(1B) + type_id(1B) + data_raw(4B) + name` |
| `0x03` | PC -> 设备 | 写入参数或执行命令型参数 | `name_len(1B) + data_raw(4B) + max_raw(4B) + min_raw(4B) + name` |
| `0x03` | 设备 -> PC，`is_ack = 1` | 返回写入后的参数值与范围 | `name_len(1B) + type_id(1B) + data_raw(4B) + max_raw(4B) + min_raw(4B) + name` |
| `0x04` | 设备 -> PC，通常非 ACK 流 | 逐条下发参数列表项 | `name_len(1B) + type_id(1B) + data_raw(4B) + max_raw(4B) + min_raw(4B) + status(1B) + name` |
| `0x05` | PC -> 设备 | 设置某个参数是否参与波形自动上报 | `name_len(1B) + enabled(1B) + name` |
| `0x05` | 设备 -> PC，`is_ack = 1` | 确认波形勾选状态更新 | 当前工程未消费具体 payload，按 ACK 成功处理 |
| `0x06` | PC -> 设备 | 设置波形上报周期 | `period_ms(4B, little-endian)` |
| `0x06` | 设备 -> PC，`is_ack = 1` | 返回生效的波形上报周期 | `period_ms(4B, little-endian)` |
| `0x07` | 设备 -> PC | 上报单个波形点或波形批次分隔符 | `name_len(1B) + type_id(1B) + data_raw(4B) + name`；批次开始/结束使用特殊哨兵 |
| `0x0C` | PC -> 设备 | 启动或停止波形上报 | `running(1B)`，`0x00` 为停止，`0x01` 为启动 |
| `0x0C` | 设备 -> PC，`is_ack = 1` | 确认波形运行状态切换 | 当前工程未消费具体 payload，按 ACK 成功处理 |

#### 参数列表与单参数模型

- 参数项解析结果落到 `ParameterEntry`，包含 `name`、`type_id`、`data_raw`、`min_raw`、`max_raw` 与 `status`。
- `type_id == 7` 表示命令型参数，界面侧会走“执行命令”而不是“写普通值”流程。
- `status` 的 bit0 当前映射为 `auto_report`，bit1 当前映射为 `important`。

#### 波形上报 `0x07` 的特殊约定

- 普通波形点格式为 `name_len + type_id + data_raw + name`。
- 当 `name_len == 0`、`type_id == 0` 且 `data_raw == 0x55555555` 时，表示一个波形批次开始。
- 当 `name_len == 0`、`type_id == 0` 且 `data_raw == 0xAAAAAAAA` 时，表示一个波形批次结束。
- 在批次模式下，主程序会先把多个参数点暂存到 `pending_wave_batch`，批次结束后再统一送入 `WaveformTab.append_batch`。

#### 当前界面使用关系

- 参数页读取参数列表时，会先发送 `0x0C` 停止发波，再发送 `0x01` 请求参数总数，随后接收多帧 `0x04` 参数项。
- 参数页读取单参数使用 `0x02`，写参数或执行命令使用 `0x03`。
- 参数页勾选波形显示使用 `0x05`。
- 波形页应用上报周期使用 `0x06`。
- 串口连接成功、读取参数列表前、以及波形页开始/停止运行时，都会用到 `0x0C` 控制设备侧波形上传。

#### `cmd_set = 0x01` 结构体级载荷定义（来自 `上位机.pdf`）

`上位机.pdf` 对 `cmd_set = 0x01` 的 payload 结构定义比当前代码注释更完整，整理如下。

##### 通用数据类型

```c
typedef enum
{
    SHELL_INT8,
    SHELL_UINT8,
    SHELL_INT16,
    SHELL_UINT16,
    SHELL_INT32,
    SHELL_UINT32,
    SHELL_FP32,
    SHELL_CMD,
} SHELL_TYPE_E;
```

- PDF 明确说明：参数数据统一按固定 4 字节 `uint32_t` 传输。
- 当参数类型是 `FP32` 时，`data` 字段传输的是浮点数的原始位模式，例如 `0.01f` 对应 `0x3C23D70A`。

##### `0x01 / 0x01` 读取参数列表总数

```c
// request payload: NULL
typedef struct
{
    uint32_t data_num;
} cmd_0101_ack_t;
```

- 上位机发送空载荷请求。
- 下位机返回参数总数 `data_num`。

##### `0x01 / 0x04` 参数列表项

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

- 每个参数占一帧。
- `status.bit0` 表示自动上报/周期打印波形标志。
- `status.bit1` 表示重要参数标志。

##### `0x01 / 0x02` 读取单参数

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

- 请求中只携带参数名。
- 响应中返回参数类型、参数值和参数名。

##### `0x01 / 0x03` 写入单参数

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

- 请求中携带参数名、当前待写值及上下限。
- 对命令型参数，界面表现为“执行”，但协议层仍复用该结构。
- 响应返回下位机侧最终生效的值和范围。

##### `0x01 / 0x05` 波形勾选

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

- `auto_report = 1` 表示开启该参数自动上报。
- `auto_report = 0` 表示关闭该参数自动上报。

##### `0x01 / 0x06` 波形上报周期

```c
typedef struct
{
    uint32_t reprot_period;
} cmd_0106_req_t;
```

- 请求与响应结构相同，字段单位均为毫秒。
- PDF 原文字段名为 `reprot_period`，当前文档保留该拼写以便与原资料核对。

##### `0x01 / 0x07` 自动上报波形点

```c
typedef struct
{
    uint8_t name_len;
    uint8_t type;
    uint32_t data;
    char name[];
} cmd_0107_report_t;
```

- 正常数据帧表示一个参数的当前值。
- 当 `name_len = 0x00`、`type = 0x00`、`data = 0x55555555` 时，表示一组波形数据开始。
- 当 `name_len = 0x00`、`type = 0x00`、`data = 0xAAAAAAAA` 时，表示一组波形数据结束。
- 当前代码已按该哨兵约定将一整组波形点收敛为单批次处理。

##### `0x01 / 0x0C` 周期打印使能

```c
typedef struct
{
    uint8_t start_report;
} cmd_010C_req_t;
```

- `start_report = 1` 表示开始自动上报。
- `start_report = 0` 表示停止自动上报。
- ACK 按 PDF 定义为空载荷。

##### `0x01 / 0x08 ~ 0x0B` 在线升级协议

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

// 0x01 / 0x09 request payload: NULL
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
```

- `0x08` 用于发送升级意图和固件概要，`update_type` 中 `1` 为正常升级，`2` 为强制升级。
- `0x09` 用于轮询 bootloader 是否已准备完成。
- `0x0A` 用于按 256 字节小包发送固件，其中 `packet_crc` 是单包 CRC16。
- `0x0B` 用于发送整包结束帧，`fw_crc` 表示包含 footer 的整包固件 CRC16。

##### `0x01 / 0x0D` LLC -> PFC 转发升级进度查询

当上位机升级 `PFC` 固件时，实际链路为“上位机 -> LLC -> PFC”。因此在 `0x0B ACK` 之后，上位机还需要继续查询 LLC 当前向 PFC 转发固件的进度。当前设计新增 `0x01 / 0x0D` 查询-应答协议，上位机周期轮询，LLC 返回当前转发状态快照。

```c
// 0x01 / 0x0D request payload: NULL
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

- `source_module_id` 与 `target_module_id` 分别标识当前转发链路的起点与终点模块。
- `stage` 用于表示 `queued / enter_boot / erasing / forwarding / verifying / done / failed` 等阶段。
- `result` 用于表示 `in_progress / success / failed`。
- `forwarded_bytes` 与 `total_bytes` 是上位机进度条的主数据源。
- `packet_offset` 与 `packet_length` 用于显示最近一次处理分包的位置信息。
- `progress_permille` 用于在特殊阶段维持连续进度显示。
- `error_code` 用于回传 LLC 侧判定的失败原因。

当前桌面程序中，若目标固件模块为 `PFC`，在收到 `0x0B ACK` 后不会直接判为升级完成，而是切换到该指令的轮询阶段；只有收到 LLC 返回的 `success / done` 才结束升级流程。

##### `0x01 / 0x17` 固件版本查询协议

为了在固件升级页中直接读取设备当前运行版本，当前设计新增 `0x01 / 0x17` 查询-应答协议。该协议同时在 `llc/update.c` 与 `pfc/update.c` 中实现，因此上位机只需要切换升级页中的目标地址，就可以分别读取 LLC 或 PFC 当前版本。

```c
// 0x01 / 0x17 request payload: NULL
typedef struct
{
    uint32_t version;
} firmware_version_ack_t;
```

- 请求 payload 为空，表示查询目标模块当前固件版本。
- 应答 payload 只返回一个 `uint32_t version`。
- 版本值来源于设备侧宏 `COMPOSE_VERSION(HARD_VER, DEVICE_VENDOR, RELEASE_VER, DEBUG_VER)`。
- 上位机会把该 `uint32_t` 按 `major.minor.patch.build` 形式格式化显示，例如 `1.2.0.13`。
- 该查询结果用于显示“设备当前版本”，不覆盖本地已加载固件文件 footer 中解析出的“文件版本”。

##### `0x01 / 0x0E ~ 0x11` 黑匣子范围查询协议

黑匣子数据量可能达到数 MB，因此当前设计采用“按逻辑偏移范围查询”，而不是按记录页码分页。这样上位机可以只拉取指定 Flash 区间的数据，减少等待时间，并支持跨 sector 的完整记录读取。

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

- `0x0E`：范围查询请求与 ACK。
- `0x0F`：表头字符串上传。
- `0x10`：数据行字符串上传。
- `0x11`：本次范围查询完成通知。

实现约束如下：

- 查询单位为 `start_offset + read_length`，不是“第几页记录”。
- 只要一条记录头落在查询区间内，就允许把整条记录完整上传，即使记录尾部超过查询区间末尾。
- 如果下一条记录头已经超出查询区间末尾，则停止扫描并发送完成帧。
- Flash sector 仅作为底层存储边界，不作为解析边界；跨 sector 记录由连续缓存读取完成。

##### `0x01 / 0x12 ~ 0x13` 工厂模式时间协议

为支持出厂时间配置，当前在 `time.c` 中新增工厂模式时间协议。通信内容仅包含 `UTC Unix time` 与半小时单位的时区值。

```c
// 0x01 / 0x12 request payload: NULL
typedef struct
{
    uint32_t unix_time_utc;
    int8_t timezone_half_hour;
} factory_time_payload_t;
```

- `0x12`：读取设备当前 `UTC Unix time` 与 `timezone_half_hour`。
- `0x13`：下发新的 `UTC Unix time` 与 `timezone_half_hour`，设备写入后返回当前生效值。
- `timezone_half_hour` 以半小时为单位编码，例如 `UTC+8 = 16`，`UTC+5:30 = 11`。

下位机实现中，`unix_time_utc` 直接写入 RTC，不叠加时区偏移；本地时区时间由 `unix_time_utc + timezone_half_hour * 1800` 推导。

##### `0x01 / 0x14 ~ 0x16` 工厂模式校准协议

为支持工厂模式下的增益与偏置校准，当前在 `cali.c / cali.h` 基础上新增一组独立于旧 `0x10 / 0x11` 的校准查询与保存协议，避免与现有上位机指令冲突。该协议同时适用于 LLC 与 PFC，因此工厂模式页需要单独填写校准目的地址。

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

- `0x14`：读取指定 `CALI_ID_E` 项当前的 `gain` 与 `bias`。
- `0x15`：下发指定 `CALI_ID_E` 项新的 `gain` 与 `bias`，设备应用后返回当前生效值。
- `0x16`：请求设备把当前校准值保存到 Flash，ACK payload 为空。

当前工厂模式页中，校准项不再直接输入数字 ID，而是通过下拉框从 `CALI_ID_E` 枚举含义中选择自然语言名称，当前对应关系如下：

- `CALI_ID_V_G_RMS` -> `Grid Voltage`
- `CALI_ID_V_AC_OUT_RMS` -> `Inverter Voltage`
- `CALI_ID_I_AC_OUT_RMS` -> `Inverter Current`
- `CALI_ID_V_BAT` -> `Battery Voltage`
- `CALI_ID_I_BAT` -> `Battery Current`
- `CALI_ID_V_PV` -> `PV Voltage`
- `CALI_ID_I_PV` -> `PV Current`

设备侧仍然按枚举值处理，主机侧只负责把下拉框选择转换成对应的数值 ID。

##### 固件尾信息 footer（来自 `上位机.pdf`）

```c
typedef struct
{
    uint32_t unix_time;
    uint8_t fw_type;
    uint32_t version;
    uint32_t file_size;
    uint8_t commit_id[16];
    uint8_t module_id;
    uint32_t crc32;
} footer_t;
```

- PDF 说明 footer 位于固件最后 `34` 字节。
- `fw_type` 中 `0` 表示 `ISP`，`1` 表示 `IAP`，只有 `IAP` 固件允许在线升级。
- `version` 采用打包整型表达，例如 `1.2.0.13 = (1<<24) | (2<<16) | (0<<8) | 13`。
- `commit_id[16]` 以 ASCII 方式显示。
- footer 的 CRC32 使用多项式 `0xEDB88320`，计算时不包含 `crc32` 字段本身。

## 主页与配置协议

`上位机.pdf` 除了参数页与升级页协议，还定义了主页广播数据和逆变配置数据。当前代码中的主页页签与设置区就是围绕这些结构展开的。

### `cmd_set = 0x02`，`cmd_word = 0x02` 主页广播

PDF 定义下位机周期广播 `pcs_info_t`，主界面据此刷新电网、逆变、电池、MPPT、温度、风扇、继电器、故障、保护与告警区域。

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
    union
    {
        uint8_t raw;
        struct
        {
            unsigned char grid_rly : 1;
            unsigned char inv_rly : 1;
            unsigned char prechg_mos : 1;
            unsigned char chg_mos : 1;
            unsigned char pv_mos : 1;
            unsigned char reserved : 3;
        };
    } rly_sta;
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

### `cmd_set = 0x03`，`cmd_word = 0x01` 逆变配置

主页设置区中的 AC 输出使能、关闭以及电压频率组合设置，对应 PDF 中的 `inv_cfg_t`：

```c
typedef struct
{
    uint8_t ac_out_enable_trig;
    uint8_t ac_out_disable_trig;
    uint8_t ac_out_rms;
    uint8_t ac_out_freq;
} inv_cfg_t;
```

- 上位机发送和下位机响应复用同一结构。
- `ac_out_enable_trig = 1` 表示触发打开 AC 输出。
- `ac_out_disable_trig = 1` 表示触发关闭 AC 输出。
- `ac_out_rms` 有效值为 `220/230/240`。
- `ac_out_freq` 有效值为 `50/60`。

## PDF 需求与当前实现的对应关系

- `上位机.pdf` 中的参数读写、参数波形、主页广播和在线升级，当前工程都已有对应页面与协议处理逻辑。
- `上位机.pdf` 中提到的“通信抓包管理”“历史数据”“固件库管理”“软件示波器”等能力，当前仓库中仍以基础串口监视、波形导入导出和升级页的形式部分覆盖，尚未形成独立完整子系统。
- `CMD_SET = 0x01 / CMD_WORD = 0x10` 校准信息下发与 `0x11` 保存命令在 PDF 中已有协议定义；当前实现为了避免与已有桌面程序指令冲突，改为在工厂模式页中使用 `0x14 / 0x15 / 0x16` 完成校准读写与保存。
- 后续若扩展新页面，建议优先沿用本文档中整理出的结构体定义，并在源码实现与 PDF 定义出现偏差时及时在此文档中标注差异。

### 服务层

- `services/serial_service.py` 负责串口枚举、串口打开关闭、接收线程管理、接收队列投递和发送写入。
- `services/serial_service.py` 负责在后台线程中持续读取串口数据，并通过线程安全队列把接收块交给界面主线程处理。
- `services/__init__.py` 作为服务子包入口文件。

### 界面层总控

- `ui/app.py` 负责创建主窗口、顶部串口连接栏、底部状态栏和五个主功能页签，并组织串口连接、协议处理、参数管理、波形显示和固件升级流程。
- `ui/app.py` 负责创建主页页签、串口调试页签、参数读写页签、参数波形页签、固件升级页签、黑匣子页签和工厂模式页签，并管理这些页面之间的状态同步。
- `ui/app.py` 负责为串口调试页签补充左侧调试设置区，包括接收时间戳、HEX 接收、自动分帧换行、接收持续保存、HEX 发送、定时发送和发送回显控制。
- `ui/app.py` 负责将串口接收数据分发到监视区、协议解析器、主页页签、参数页、波形页、升级页、黑匣子页和工厂模式页，并在主线程中执行批量 UI 刷新。
- `ui/app.py` 负责运行状态显示、参数提示栏、收发字节计数、接收保存和发送控制。
- `ui/app.py` 负责统一收发显示字符串的格式化，发送回显与接收数据显示共享公共显示函数，并在 HEX 模式下处理 `0D 0A` 换行显示。
- `ui/app.py` 负责在连接建立后向广播地址发送停止发波命令，避免旧设备状态影响参数读取与波形显示。
- `ui/app.py` 负责主页刷新容错与限频，包括错包异常隔离、主页数据暂存和合并刷新，避免坏包导致首页卡死。

## `serial_debug_assistant.ui` 组件设计

### 主页页

- `ui/home_tab.py` 定义主页页签布局，展示电网、逆变器、电池、MPPT、温度、风扇与继电器状态、故障信息和告警信息。
- `ui/home_tab.py` 负责逆变输出配置的读取、写入、使能和关闭操作入口，并维护主页状态文本与故障/告警日志显示。
- `ui/home_tab.py` 负责展示主页协议帧解析后的实时功率、电压、电流、频率、温度和电池荷电状态。

### 串口收发页

- `ui/monitor_tab.py` 定义串口监视页布局。
- `ui/monitor_tab.py` 负责发送日志区、接收显示区、手动发送区、快捷发送区和快捷发送配置持久化。
- `ui/monitor_tab.py` 负责发送日志区与接收显示区共用的文本框样式配置，接收区使用黑色文本标签，发送区使用绿色文本标签。
- `ui/monitor_tab.py` 负责批量追加接收/发送文本，并在文本长度过大时自动裁剪历史内容，避免长时间运行后文本框持续膨胀。
- `ui/monitor_tab.py` 负责快捷发送配置文件 `quick_send.cfg` 的加载、修复与保存。
- `ui/monitor_tab.py` 负责主分栏位置记录和界面布局信息回传。

### 参数读写页

- `ui/parameter_tab.py` 定义参数列表页布局。
- `ui/parameter_tab.py` 负责模块地址输入、参数搜索、参数表格显示、单参数读取、参数写入和波形勾选控制。
- `ui/parameter_tab.py` 负责参数条目的忙碌态、非法态、脏数据态和波形选中态展示。
- `ui/parameter_tab.py` 负责在读取参数列表、读取单参数和写参数过程中向主窗口状态栏反馈参数提示信息。

### 波形页

- `ui/wave_tab.py` 定义波形页布局。
- `ui/wave_tab.py` 负责已选参数列表、最新值列表、实时曲线绘制、窗口时间切换、暂停查看和回到实时视图。
- `ui/wave_tab.py` 负责波形导入导出、停止发波自动保存、软件关闭自动保存、标记线、参考线和鼠标交互。
- `ui/wave_tab.py` 支持显示全部、时间窗口查看、矩形缩放、横向/纵向缩放与平移、悬停读数和快捷键操作。

### 固件升级页

- `ui/upgrade_tab.py` 定义固件升级页布局。
- `ui/upgrade_tab.py` 负责固件路径显示、升级地址输入、升级类型选择、进度显示和升级日志显示。
- `ui/upgrade_tab.py` 负责呈现文件版本、设备版本、编译时间、模块和校验结果。
- `ui/upgrade_tab.py` 负责根据串口连接状态切换可操作控件，并展示升级阶段、错误码与详细结果。
- `ui/upgrade_tab.py` 额外提供 `Read Device Version` 操作，用于向当前目标地址发送 `0x01 / 0x17` 查询。
- `ui/upgrade_tab.py` 负责显示 `LLC -> PFC Forward Progress` 面板，用于展示 `0x01 / 0x0D` 返回的二级转发进度。

### 黑匣子页

- `ui/black_box_tab.py` 定义黑匣子页布局。
- `ui/black_box_tab.py` 负责 `start_offset` 与 `read_length` 的范围输入、查询发送和完成状态显示。
- `ui/black_box_tab.py` 负责把表头字符串和数据行字符串解析成接近 Excel 的表格展示。
- `ui/black_box_tab.py` 固定显示 `No.` 与 `Time` 列，并根据设备上传的表头动态扩展其余参数列。
- `ui/black_box_tab.py` 会把记录首列中的 Unix 时间自动转换为 UTC 时间字符串，并以居中方式显示表格中的数值列。
- `ui/black_box_tab.py` 支持将当前表格结果导出为 `.csv`。

### 工厂模式页

- `ui/factory_mode_tab.py` 定义工厂模式页布局。
- `ui/factory_mode_tab.py` 负责设备地址输入、设备时间读取、当前 PC UTC 时间下发和时区输入。
- `ui/factory_mode_tab.py` 负责将设备返回的 `UTC Unix time + timezone_half_hour` 自动转换为带时区的字符串显示，例如 `YYYY-MM-DD HH:MM:SS UTC+8`。
- `ui/factory_mode_tab.py` 额外提供校准区，支持单独输入校准目的地址、读取当前 `gain / bias`、下发新校准值以及请求保存到 Flash。
- `ui/factory_mode_tab.py` 使用自然语言下拉框展示校准项，而不是让用户直接输入 `CALI_ID_E` 数字。

### 日志页组件

- `ui/debug_tab.py` 定义可复用的日志文本显示组件。
- `ui/debug_tab.py` 负责日志路径展示、日志内容追加和显示内容清理。
- `ui/debug_tab.py` 当前未作为独立主页签挂载，但保留为后续调试界面扩展组件。

### 界面包入口

- `ui/__init__.py` 作为界面子包入口文件。

## 模块协作关系

- 启动入口层负责启动 `ui/app.py` 中的主窗口。
- 主窗口负责调用 `SerialService` 完成串口收发，并通过 `FrameParser` 解析协议帧。
- 串口调试页负责展示发送日志、接收显示、手动发送和快捷发送配置，左侧调试设置区负责控制显示模式、定时发送与数据保存。
- 主页页负责汇总协议解析后的设备状态、告警与故障信息，并提供逆变配置操作入口。
- 参数页负责发起参数列表读取、单参数读取、参数写入和波形勾选；参数结果进入 `ParameterEntry` 映射和参数表格。
- 参数页输出的波形勾选结果进入 `WaveformTab`，波形页负责绘制和管理参数曲线，并支持保存、导入和交互分析。
- 固件文件解析、版本格式化与升级/版本查询载荷构造由 `firmware_update.py` 提供，升级界面和升级状态流转由 `ui/app.py` 与 `UpgradeTab` 共同组织；当目标为 `PFC` 固件时，升级流程还会切换到 LLC 二级转发进度轮询。
- 黑匣子协议打包与解析由 `black_box_protocol.py` 提供，黑匣子页查询、表格展示与 CSV 导出由 `ui/app.py` 与 `BlackBoxTab` 共同组织。
- 工厂模式时间协议与校准协议打包、解析与枚举名称映射由 `factory_mode.py` 提供，工厂模式页中的时间读取、UTC 时间下发、时区化显示以及校准读写保存由 `ui/app.py` 与 `FactoryModeTab` 共同组织。
- `debug_logger.py` 负责把运行日志写入 `logs/app_debug.log`，同时把日志分发给订阅组件使用。
- `app_paths.py` 负责统一数据目录定位和旧数据迁移，使安装版覆盖升级后保留配置、导出文件和日志。
- 构建发布层负责将应用包转换为目录版可执行程序和 Windows 安装包。
