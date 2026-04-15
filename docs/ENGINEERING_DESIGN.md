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
│     ├─ debug_tab.py
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

### `cmd_set = 0x01` 指令集

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

### 服务层

- `services/serial_service.py` 负责串口枚举、串口打开关闭、接收线程管理、接收队列投递和发送写入。
- `services/serial_service.py` 负责在后台线程中持续读取串口数据，并通过线程安全队列把接收块交给界面主线程处理。
- `services/__init__.py` 作为服务子包入口文件。

### 界面层总控

- `ui/app.py` 负责创建主窗口、顶部串口连接栏、底部状态栏和五个主功能页签，并组织串口连接、协议处理、参数管理、波形显示和固件升级流程。
- `ui/app.py` 负责创建主页页签、串口调试页签、参数读写页签、参数波形页签和固件升级页签，并管理这些页面之间的状态同步。
- `ui/app.py` 负责为串口调试页签补充左侧调试设置区，包括接收时间戳、HEX 接收、自动分帧换行、接收持续保存、HEX 发送、定时发送和发送回显控制。
- `ui/app.py` 负责将串口接收数据分发到监视区、协议解析器、主页页签、参数页、波形页和升级页，并在主线程中执行批量 UI 刷新。
- `ui/app.py` 负责运行状态显示、参数提示栏、收发字节计数、接收保存和发送控制。
- `ui/app.py` 负责统一收发显示字符串的格式化，发送回显与接收数据显示共享公共显示函数，并在 HEX 模式下处理 `0D 0A` 换行显示。
- `ui/app.py` 负责在连接建立后向广播地址发送停止发波命令，避免旧设备状态影响参数读取与波形显示。

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
- `ui/wave_tab.py` 负责波形导入导出、停止发波自动保存、标记线、参考线和鼠标交互。
- `ui/wave_tab.py` 支持显示全部、时间窗口查看、矩形缩放、横向/纵向缩放与平移、悬停读数和快捷键操作。

### 固件升级页

- `ui/upgrade_tab.py` 定义固件升级页布局。
- `ui/upgrade_tab.py` 负责固件路径显示、升级地址输入、升级类型选择、进度显示和升级日志显示。
- `ui/upgrade_tab.py` 负责呈现固件版本、编译时间、模块和校验结果。
- `ui/upgrade_tab.py` 负责根据串口连接状态切换可操作控件，并展示升级阶段、错误码与详细结果。

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
- 固件文件解析与升级载荷构造由 `firmware_update.py` 提供，升级界面和升级状态流转由 `ui/app.py` 与 `UpgradeTab` 共同组织。
- `debug_logger.py` 负责把运行日志写入 `logs/app_debug.log`，同时把日志分发给订阅组件使用。
- `app_paths.py` 负责统一数据目录定位和旧数据迁移，使安装版覆盖升级后保留配置、导出文件和日志。
- 构建发布层负责将应用包转换为目录版可执行程序和 Windows 安装包。
