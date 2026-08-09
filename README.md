# FRAME

FRAME 是面向 Windows 的嵌入式设备调试与数据观测工具，当前版本为 `v1.13.0`。工程使用 Python 开发，同时提供桌面 GUI、交互式终端和一次性 CLI，覆盖串口、CAN、Ethernet TCP、统一通信协议、在线参数、数据采集、固件升级和 J-Link 调试。

FRAME 可以独立作为通用串口工具使用，也可以与下位机 FRAME 协议配合，形成从命令交互、参数整定到波形分析和现场诊断的一套调试链路。

## 与 ATOMAN（base）配合使用

FRAME 是上位机工具，[ATOMAN（base）](https://github.com/MAXLII/ATOMAN) 提供下位机公共代码、硬件平台工程和 PLECS 仿真环境。base 中的通信与调试服务生成协议数据，FRAME 通过串口、CAN 或 Ethernet 完成参数读写、波形观测、Scope、SFRA、Perf、Trace、Section 链表查询和固件升级。

两个工程的 GitHub 地址：

- FRAME：<https://github.com/MAXLII/FRAME>
- ATOMAN（base）：<https://github.com/MAXLII/ATOMAN>

FRAME 侧不重复维护 base 的接入步骤。完整的工程选择、下位机配置、连接参数和 PLECS 联调流程统一见 [ATOMAN 与 FRAME 配合使用](https://github.com/MAXLII/ATOMAN/blob/master/docs/application/communication/frame_atoman_integration.md)。

## 主要能力

### 通信与协议

- 枚举并配置串口，支持文本与 HEX 收发、定时发送、时间戳、快捷发送和原始数据保存。
- 支持 CAN 与 Ethernet TCP 传输，并将不同传输接入统一的协议控制层。
- Ethernet 支持多网卡 UDP 广播设备发现，可显示设备身份、地址和版本并直接建立 TCP 连接。
- 支持自定义 `cmd_set / cmd_word` 协议帧发送、CRC 校验、地址配置和 ACK 匹配。
- 支持交互式终端与脚本化的一次性命令，便于联调和自动化验证。

### 参数与数据观测

- 参数列表读取、单参数读写、批量操作、重要参数与自动上报管理。
- 参数波形实时显示、历史查看和数据导出。
- Scope 软件录波：对象枚举、状态控制、手动触发、数据拉取和 CSV 导出。
- SFRA 在线扫频分析。
- Perf 任务执行时间与性能统计。
- Trace 代码执行路径跟踪。
- Black Box 数据范围查询、拉取和 CSV 导出。
- Section 注册链表目录与节点查看。

### 设备维护

- 固件文件解析、设备版本查询、分包传输和升级状态管理。
- Factory Mode 时间设置与校准。
- 基于 ELF/MAP/DWARF 的 J-Link 符号浏览、变量读取与 RAM 变量写入。
- GUI 演示模式，可在没有真实设备时查看主要页面和交互流程。

## 运行环境

- Windows 10 或 Windows 11
- Python 3.12（推荐）
- `tkinter`（Python 标准库 GUI）
- 运行依赖见 `requirements.txt`
- J-Link 功能需要 SEGGER J-Link 软件与调试器
- 安装包构建需要 Inno Setup 6

当前 Python 依赖包括 `pyserial`、`python-can`、`pywin32` 和 `pyelftools`。

## 快速开始

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\frame.ps1 gui
```

`frame.ps1` 和 `frame.bat` 会优先使用 `.venv\Scripts\python.exe`，虚拟环境不存在时回退到系统 Python。

也可以运行一键启动脚本，由脚本创建虚拟环境、安装依赖并启动应用：

```bat
run_serial_debug_assistant.bat
```

## 使用入口

### 桌面 GUI

```powershell
.\frame.ps1 gui
```

无设备演示：

```powershell
.\frame.ps1 gui --demo
```

### 交互式终端

```powershell
.\frame.ps1
```

或显式启动 Shell：

```powershell
.\frame.ps1 shell
```

常用交互命令：

```text
frame> ports
frame> connect COM8 921600
frame> param list
frame> perf info
frame> disconnect
frame> exit
```

### 一次性 CLI

```powershell
.\frame.ps1 --help
.\frame.ps1 serial ports
.\frame.ps1 serial raw --port COM8 --baud 921600 --send-text "list\r\n" --read-seconds 1
.\frame.ps1 param list --port COM8 --baud 921600
.\frame.ps1 param read DEMO_SHELL_COUNTER --port COM8 --baud 921600
.\frame.ps1 scope list --port COM8 --baud 921600
.\frame.ps1 perf summary --port COM8 --baud 921600
```

当前一级命令包括：

```text
shell  gui  jlink  serial  proto  param  scope  sfra  perf  trace  blackbox
```

完整参数和交互式命令见 [CLI 命令文档](docs/CLI_COMMANDS.md)。

## J-Link 调试

一次性读取符号示例：

```powershell
.\frame.ps1 jlink `
  --elf D:\path\app.elf `
  --map D:\path\app.map `
  --device GD32G553RCT6 `
  --filter symbol `
  --limit 50
```

HC32 工程连接、下载或读写内存时，Target / Device 使用 `Cortex-M4`。J-Link 的 GUI、终端和一次性 CLI 用法见 [J-Link 使用方法](docs/JLINK_USAGE.md)。

## 工程结构

```text
FRAME/
├─ serial_debug_assistant/
│  ├─ comm/                    通信协议与传输协作
│  ├─ controllers/             页面无关的功能控制器
│  ├─ services/                串口、CAN 和 Ethernet 服务
│  ├─ ui/                      tkinter 页面与界面组件
│  ├─ cli.py                   CLI 参数解析与命令入口
│  ├─ terminal_shell.py        交互式终端
│  ├─ protocol.py              FRAME 帧编解码与流式解析
│  ├─ *_protocol.py            各调试功能协议
│  └─ jlink_debug.py           ELF/MAP/DWARF 与 J-Link 调试
├─ tests/                      Python 自动化测试
├─ docs/                       设计、协议与操作文档
├─ installer/                  Inno Setup 安装工程
├─ integrations/               外部工程集成内容
├─ assets/                     图标与界面资源
├─ main.py                     统一启动入口
├─ main_gui.py                 GUI 启动入口
├─ main_demo.py                演示模式入口
├─ frame.ps1 / frame.bat       命令行包装脚本
└─ requirements.txt            Python 运行依赖
```

应用层通过控制器调用协议与服务，串口、CAN 和 Ethernet 负责字节流传输；各功能协议模块负责 payload 编解码，GUI 与 CLI 复用相同的核心能力。

## 运行数据

源码运行时，配置、导出和日志分别保存在仓库下的：

- `config/`
- `exports/`
- `logs/`

安装版默认使用：

```text
%LOCALAPPDATA%\FRAME\
```

这些目录属于运行数据，不作为工程源码维护。

## 测试

运行全部 Python 单元测试：

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

测试覆盖传输服务、固件升级、参数协议、Section 链表协议、J-Link 目标识别和界面设置持久化等核心行为。

## 构建与发布

```bat
build_frame_exe.bat
build_frame_demo_exe.bat
build_frame_installer.bat
```

- `build_frame_exe.bat`：构建 FRAME 可执行程序。
- `build_frame_demo_exe.bat`：构建演示版可执行程序。
- `build_frame_installer.bat`：构建 Windows 安装包。
- `build_dr_ssip_monitor_installer.bat`：构建 DR SSIP Monitor 命名版本。
- `build_dr_ssip_monitor_lite_installer.bat`：构建 Lite 命名版本。
- `clean_build_artifacts.bat`：清理构建产物和 Python 缓存。

## 文档

- [工程设计](docs/ENGINEERING_DESIGN.md)：通信协议、页面能力、数据结构和运行流程。
- [Ethernet 设备发现协议](docs/ETHERNET_DISCOVERY_PROTOCOL.md)：UDP 5000 广播搜索、响应字段和 GD32E507 对接规则。
- [CLI 命令](docs/CLI_COMMANDS.md)：一次性命令与交互式终端参考。
- [J-Link 使用方法](docs/JLINK_USAGE.md)：符号加载、目标连接、变量读取与写入。
- [可维护架构](docs/MAINTAINABLE_ARCHITECTURE.md)：模块边界与维护约定。
- [Scope 协议](docs/scope.md)：软件录波协议定义。
- [Section 链表视图](docs/SECTION_LIST_VIEW.md)：注册链表浏览功能。
