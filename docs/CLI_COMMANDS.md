# FRAME 终端命令

## 启动方式

源码工作区内：

```bat
frame
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
frame-cli.exe
frame.bat
```

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
```

默认连接命令等价于：

```text
connect COM8 921600 1.5
```

`connect jlink` 会自动选择描述中包含 `JLink` 或 `J-Link` 的 CDC 串口。

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
perf reset
```

对应 GUI Perf 页的拉取全部、Task、Interrupt、Code、更新字典、Reset Peak。

## Trace

```text
trace start [seconds]
trace stop
```

`trace start 1` 会启动上报并监听 1 秒 trace 记录。

## J-Link

```text
jlink connect <device> [speed_khz]
jlink read <elf> [map|-] [device] [filter] [limit]
```

`JLink.exe` 会自动从 PATH 和 SEGGER 默认安装目录中查找，不需要手动选择 exe。
如果 ELF 带 DWARF 调试信息，结构体和小数组会自动展开，例如：

```text
s_usart_dbg_shell_ctx.shell_buffer[0]
s_usart_dbg_shell_ctx.shell_index
```

大型数组会保留为整体项，避免一次刷新生成过多行。

示例：

```text
jlink connect GD32G553RCT6
jlink read D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.elf D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.map GD32G553RCT6 s_task 50
```
