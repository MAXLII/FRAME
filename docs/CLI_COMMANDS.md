# FRAME 终端命令

## 启动方式

源码工作区内：

```bat
.\frame
```

进入交互终端后，串口会保持连接，后续命令复用同一个连接。

```text
frame> ports
frame> connect COM8 921600
frame> param list
frame> param read DEMO_SHELL_COUNTER
frame> perf info
frame> disconnect
frame> exit
```

PowerShell 在当前目录运行时，也可以使用：

```powershell
.\frame
```

安装包安装后：

```bat
frame
```

安装程序会把安装目录加入当前用户的 `PATH`。安装完成后需要新开一个终端，新的环境变量才会生效。

开始菜单中提供两个入口：

- `FRAME`：界面版
- `FRAME Terminal`：终端版

## 串口与原始收发

```text
ports
connect [COMx|jlink] [baud] [timeout]
disconnect
status
raw text <text>
raw hex <AA 55 ...>
raw read [seconds]
raw query <text> [seconds]
raw query-hex <AA 55 ...> [seconds]
```

默认连接命令等价于：

```text
connect COM8 921600 1.5
```

`connect jlink` 会自动选择描述中包含 `JLink` 或 `J-Link` 的 CDC 串口。

交互式终端的 `raw text` 支持常用转义字符。发送带回车换行的文本：

```text
raw text "list\r\n"
```

发送后接收 1 秒：

```text
raw query "list\r\n" 1
```

发送 HEX 后接收 1 秒：

```text
raw query-hex AA 55 01 02 1
```

一次性 PowerShell 命令中也可以直接写 `\r\n`：

```powershell
frame serial raw --port COM8 --baud 921600 --send-text "list\r\n" --read-seconds 1
```

## 主页按钮

```text
home enable
home disable
home read
home set <rms> <freq>
```

对应 GUI 主页的打开输出、关闭输出、读取当前设置、发送设置。

## 参数读写与波形勾选

```text
param list
param read <name>
param write <name> <type_id> <value> [min] [max]
param wave <name> on|off
```

`type_id`：

- `0`: INT8
- `1`: UINT8
- `2`: INT16
- `3`: UINT16
- `4`: INT32
- `5`: UINT32
- `6`: FP32
- `7`: CMD

## 参数波形

```text
wave period <ms>
wave start [period_ms]
wave stop
wave read [seconds]
```

对应 GUI 波形页的应用周期、开始、停止。`wave read` 用于临时读取上报帧。

## 固件升级页

```text
upgrade load <firmware.bin>
upgrade info
upgrade start normal
upgrade start force
upgrade start normal [dst] [d_dst]
upgrade progress
upgrade stop
upgrade version [dst] [d_dst]
```

对应 GUI 固件升级页的加载固件、查看固件信息、普通升级、强制升级、查看进度、停止升级、读取设备版本。

典型流程：

```text
connect COM8 921600
upgrade load D:\firmware\app.bin
upgrade info
upgrade version 2 0
upgrade start normal 2 0
upgrade progress
```

`upgrade start` 会在后台执行升级，升级期间其它串口命令会被暂时拦住，避免打断固件分包。需要中止时执行：

```text
upgrade stop
```

## Black Box

```text
blackbox read <start_offset> <length>
```

对应 GUI Black Box 页的 Push 查询按钮。

## 工厂模式

```text
factory time read
factory time set-now [timezone]
factory cali read <id>
factory cali write <id> <gain> <bias>
factory cali save
```

`timezone` 支持 `+8`、`UTC+8`、`+5:30` 这类格式。

## Scope

```text
scope list
scope info <id>
scope vars <id> [count]
scope start <id>
scope trigger <id>
scope stop <id>
scope reset <id>
scope sample <id> <index> [tag] [force]
```

对应 GUI Scope 页的刷新对象、刷新信息、读取变量、启动、触发、停止、复位、拉取采样。

## SFRA

```text
sfra list
sfra info <id>
sfra config <id> <start_hz> <stop_hz> <amplitude>
sfra start <id>
sfra stop <id>
sfra reset <id>
sfra point <id> <index> [tag]
```

对应 GUI SFRA 页的刷新对象、读取配置、应用配置、启动、停止、复位、读取扫频点。

## Perf

```text
perf info
perf summary
perf dict [all|task|interrupt|code]
perf sample [all|task|interrupt|code]
perf pull [all|task|interrupt|code]
perf reset
```

`perf dict` 只拉取字典，`perf sample` 会拉取字典后再拉采样值，`perf pull` 会先打印字典再打印采样值。`perf summary` 优先读取设备 summary，设备未响应时会按 `sample all` 的 Task 和 Interrupt 记录计算汇总。对应 GUI Perf 页的拉取全部、Task、Interrupt、Code、更新字典、Reset Peak。

## Trace

```text
trace start [seconds]
trace stop
```

`trace start 1` 会启动上报并监听 1 秒 trace 记录。

## J-Link

```text
frame jlink [--elf <elf>] [--map <map>] [--device <device>] [--speed 4000] [--filter keyword] [--limit count]
```

`JLink.exe` 会自动从 PATH 和 SEGGER 默认安装目录中查找，不需要手动选择 exe。未填写 `--elf`、`--map`、`--device`、`--interface` 或 `--speed` 时，会优先复用 GUI 中保存的 J-Link 配置。如果只需要解析变量列表，不读取目标板内存，可以加 `--no-read`。

交互式终端中的 J-Link 命令按 GUI 的交互方式拆分：

```text
jlink elf <elf-or-axf>
jlink map <map|->
jlink device <target> [speed_khz]
jlink load
jlink list [filter] [limit]
jlink search <keyword> [limit]
jlink funcs [filter] [limit]
jlink read <expression> [depth]
jlink write <expression> <value>
jlink source <expression|symbol|address> [context_lines]
jlink connect <target> [speed_khz]
```

`jlink elf`、`jlink map` 和 `jlink device` 会写入本地 JSON 配置。`jlink list` 只加载未展开的顶层变量列表，不读取目标板内存。`jlink search` 只搜索未展开的顶层变量名，不搜索结构体内部成员。`jlink funcs` 从 ELF 函数符号表展示函数列表。`jlink read` 按表达式读取变量，如果变量可以展开，会按结构体、数组或指针类型继续展开。结构体和指针字段使用 `.` 分隔，例如 `p_init_first.p_next.priority`。`jlink source` 根据 ELF 的 DWARF 调试信息把指定函数名、函数地址或函数指针字段定位到源码文件和行号；不带 `context_lines` 时显示完整函数，带数字时显示命中行附近源码。

交互式终端会记住最近一次显式执行的命令前缀。带子命令的命令会记住前两个词，例如 `jlink source`、`jlink funcs`、`perf dict`；普通带参数命令会记住第一个词，例如 `connect`。后续直接输入参数时，会自动补上最近记住的前缀。

示例：
```text
frame jlink --elf D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.elf --map D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.map --device GD32G553RCT6 --filter s_task --limit 50
jlink elf D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.elf
jlink map D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.map
jlink device GD32G553RET6 10000
jlink list p_init 20
jlink search p_init 20
jlink funcs main
jlink funcs task 20
jlink read p_init_first.p_next 1
jlink write p_init_first.p_next.priority 0
jlink source p_init_first.p_next.p_func 6
jlink source bsp_gpio_init 6
jlink source 0x08001B09 6
```

GUI、交互式终端和一次性 CLI 的完整使用方法见 [JLINK_USAGE.md](JLINK_USAGE.md)。
