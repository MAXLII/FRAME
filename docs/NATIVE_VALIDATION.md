# FRAME 原生重写验证记录

以下为开发阶段的分批验证记录，日期和版本按原始证据保留。后续安装包与发布流程见 [INSTALLER_RELEASE.md](INSTALLER_RELEASE.md)，发布范围与已知缺项见 `docs/releases/`。

日期：2026-09-08。验证入口优先 CLI/Shell，最后检查 WPF。新程序在 `build/app`，版本保持 1.13.0，未提交或推送 Git，未制作安装包。

## 交付与环境

| 项目 | 实际实现 |
|---|---|
| 后端 | C++20，Windows x64，frame_backend.dll，C ABI 1 |
| 公共客户端 | Frame.Interop / SafeHandle；Frame.Client 异步操作与关闭 |
| CLI / Shell | C# .NET 10，System.CommandLine 2.0.11，共用命令处理器 |
| UI | C# / WPF / XAML，九个页面，ScottPlot.WPF 5.1.59 |
| 本机工具链 | VS 2026 Community 18.9.1，MSVC 19.51，.NET SDK 10.0.400，CMake 4.4.3 |
| 符号解析 | LLVM 20.1.8 Object / DebugInfoDWARF；GNU MAP 地址索引 |

后端、CLI、WPF 和测试项目构建通过；C# 构建 0 警告、0 错误。独立协议样本位于 `tests/fixtures`，测试不执行旧 Python。LLVM 首次获取并编译耗时较长；其第三方构建系统可能探测 Python，但 FRAME 新源码、构建入口和运行时不加载旧 Python 应用。依赖记录见 `DEPENDENCIES.md`。

## 自动化验证

| 检查 | 结果与边界 |
|---|---|
| 原生协议测试 | 黄金帧/语义字段、CRC、逐位置拆包、粘包、损坏后重同步、截断、整数/浮点边界通过 |
| 原生运行时测试 | ABI 缓冲区、操作释放、事件读取、128 操作配额、持续会话、数据分页、取消、截止时间、停止 ACK、超时隔离通过 |
| 完整性与失败路径 | 时间回绕、重复/缺失索引；Scope 拉取超时保留 tag/部分点；SFRA 未完成拒绝整表拉取；Trace 取消保留记录通过 |
| 探针隔离 | 缓冲 stdout 的模拟 Commander 复用；挂起探针超时清理；探针等待不阻塞串口采集通过 |
| CLI / Shell | 帮助/版本 JSON、参数错误、JSON/NDJSON、流式条数、串口枚举、持续 Shell、非交互失败即退出通过 |
| 实际 Ctrl+C 信号 | 独立隐藏控制台向 CLI 投递 CTRL_C_EVENT：JSON/NDJSON 均退出 130，停止确认通过；NDJSON 尾部条数与数据集一致；不是模拟调用 Cancel API |
| WPF 组件与渲染 | 九页实例化、导航、实机数据加载、表格与图表渲染通过，图像位于 `build/ui-verification` |
| WPF 集成生命周期 | 真实 Frame.Client/后端回放采集在切页后继续；窗口关闭取消活动任务、确认停止、冲刷部分导出，见 build/ui-close-wave.json；通过组件调用验证，未模拟鼠标输入 |

可复现命令：

```powershell
./scripts/build.ps1
ctest --test-dir build/native -C Release --output-on-failure
./tests/cli-smoke.ps1
dotnet build tests/ui/Frame.UiTests.csproj -c Release -o build/ui-tests
Copy-Item build/app/frame_backend.dll build/ui-tests/frame_backend.dll
./build/ui-tests/Frame.UiTests.exe $PWD.Path
```

这些测试不代表所有九项业务的每一种异常组合均已覆盖。交互式 Shell 的真实按键历史/补全、WPF 的实际鼠标操作仍属于待完成的桌面验收。

## E507 实机

串口经枚举核对为 COM6 / CH340，115200、8N1、设备地址 2；COM4 为 J-Link CDC，本次不作 FRAME 通道。探针序列号 69409716，J-Link V9.36，目标 GD32E507ZE。原理图 USART0 PA9/PA10、SWD 接口及实际目标已核对。测试只使用 demo 诊断对象，未启用功率输出。

最终九项功能测试通过，原始命令与结构化结果在 `build/e507-nine-feature.ndjson`，汇总在 `build/e507-nine-feature-report.json`：

| 功能 | 实机证据 |
|---|---|
| 串口调试 | 端口枚举；记录真实只读查询，再通过 raw 发出并收到原始字节，导出 e507-serial.json |
| 参数 | 35 项目录；DEMO_SHELL_COUNTER 写 17、读取确认、恢复原值 0 |
| 参数波形 | 1 秒 28 条诊断参数记录；停止 ACK；上报标志恢复初始关闭 |
| Scope | 对象/通道、预采样、触发、拉取 100 点、2 通道 sin/cos，tag 一致 |
| SFRA | 500～1000 Hz 的 300 点完整扫描；等待 done；恢复原 10～5000 Hz / amplitude=1 配置 |
| Perf | 31 项字典与样本完整，序号和记录数一致 |
| Trace | 1 秒 75 条记录、停止确认、JSON 导出 |
| 链表顺序 | 10 个目录逐项核对节点数，包含 0 节点目录；保留实际顺序和地址 |
| J-Link | 指定探针；ELF/DWARF 类型与地址、GNU MAP；RAM 标量写 23 并回读，恢复 0 |

```powershell
./tests/e507-smoke.ps1 -Port COM6 -Probe 69409716 `
  -Elf 'D:/OneDrive/LWX/GD32/base/platform/gd32e507/build/gd32e507_demo.elf'
./tests/e507-shell-integration.ps1 -Port COM6 -Seconds 1800
```

脚本中测试对象仅适用于已核对的 E507 demo 固件，不能直接用于其他功率工程。端口与 ELF 路径应使用实际枚举和当前固件构建结果。

### 持续实机联调及发现的问题

30 分钟持续 Shell 运行完成 1,709 次参数读取，穿插完整 Perf 采样与 J-Link RAM 读取，后台波形保留 49,046 条记录，停止确认成功。证据为 `build/e507-shell-integration.ndjson` 和 `build/e507-30min-wave.json`。

该次原始测试报告的 Passed=false 必须保留：原因是测试脚本在取消后执行 data read，正确收到“部分数据”退出码 6，却错误断言必须成功。修正脚本后，独立 91.2 秒、85 次读取的完整停止/导出/参数恢复/退出复测通过，见 `build/e507-final-shell-report.json`。不能把原始失败报告改成通过。旧格式波形没有逐点传输序号，因此 49,046 条记录不构成“链路绝对零缺样”的证明。

实机最初暴露 Perf 多帧响应丢失：CRC 无错误，但固件 TX 丢弃计数增加。获授权范围内仅修改 `base/platform/gd32e507/bsp/src/bsp_usart.c`：TX 环扩大到 4096，使用 TX empty 中断逐字节发送，保留任务注册，记录队列峰值，避免轮询发送长期占用任务。保留其他 Ethernet/lwIP 工作，未改目录外共享代码。

该诊断固件编译、下载校验通过，RAM 94520 B（72.11%）。持续联调后读回 TX drop=0，队列峰值 158 B，计数器变量=0；最终九项测试后 TX drop 仍为 0。日志：`build/e507-irq-build.log`、`build/e507-irq-download.log`、`build/e507-final-jlink.ndjson`。

下载前备份完整 512 KiB Flash，保留于 `build/e507-backup/original-flash.bin`，SHA256：

```text
3E7CE8B2710637411A2064BD91D6F66B50DC6298630BD1BF8CB0DB9CB3FC9C58
```

当前板上保留已验证的诊断固件，未自动恢复旧固件。需要恢复时，使用已核对目标与 `loadbin original-flash.bin,0x08000000`；同时保留备份 ELF/HEX/MAP 作为恢复依据。

## 持续回放

各次回放使用隔离的可执行文件副本，记录各自 DLL SHA256；较早副本的持续运行结论不能当作最终 DLL 的同版本验收。

| 运行 | 配置时长 | 记录量 / 平均速率 | 峰值工作集 | 结果文件 |
|---|---|---|---|---|
| 初始基线 | 7200 秒 | 11,520,000 / 1600 条/秒 | 140865536 B，约 134.3 MiB | build/soak-report.json；补充核对 build/soak-audit.json |
| 带递增设备时间的后续回归 | 900 秒 | 1,440,000 / 1600 条/秒 | 127451136 B，约 121.5 MiB | build/final-soak-report.json |
| 最终 DLL 回归 | 300 秒 | 480,000 / 1600 条/秒 | 125280256 B，约 119.5 MiB | build/release-soak-report.json |

三次均通过并确认停止，历史条数保持小于 100000；淘汰计数与保留条数之和等于总记录量。后两次缺失、重复及时间乱序计数为 0。初始基线监测时长 7207.5 秒；监测脚本每 10 秒轮询一次进程，报告墙钟时长包含最多约一次轮询等待，不代表采集时间被延长。

DLL 摘要：初始基线 `D9EB343361E1317DE5A09FB0FEBC5D359EC7EB81BF7DA2737DE8275F6957C04C`；900 秒回归 `9F7AF86EFA946263652A96B52AE34F6C095DDEAAB8AEA898F08C6D84C5080E11`；最终 DLL `6BBF18744E9A656462689046A11B7ED7C1F37F25D376AECF49C73F735909D771`，与最终 E507 九项测试摘要一致。

初始基线启动后，回放样本才增加设备时间递增能力，因此其时间字段为固定值。它验证吞吐、长时生命周期和历史容量；时间完整性由独立原生测试及后续带递增时间的回归验证。最终 DLL 尚未单独完成同版本两小时运行。

## 待完成的最终验收

### 以太网连接后续修改

增加串口/以太网 TCP 选择和 IP/端口输入，后端用 Winsock 非阻塞 TCP，CLI/Shell 共享同一通道。`tests/tcp/Frame.TcpTests.csproj` 使用本机回环服务器核对与串口黄金样本一致的 TX、碎片化 RX、持续 Shell 参数读取、主动断开、超时、取消、对端关闭、拒绝连接和非法地址。此为真实本机 TCP 测试，不代表 E507 以太网硬件已联通；本次未修改或下载以太网固件。

### 参数表与侧边栏后续修改

按 Git 中旧 FRAME 的参数页行为重建专用六列表格，增加模糊搜索、暂存编辑、上下限提交、只读/CMD、上报及状态颜色；FP32 显示解码浮点值。侧边栏可折叠且不销毁页面。新增组件回归验证类型/HEX、编辑不自动发送、单项更新保留列表、只读拦截和折叠恢复；原生回放验证 FP32 值及编辑后上下限的实际发送字节与读回，并拒绝逆序范围。后端、CLI 与 WPF 重新构建验证；本次界面修改未重新执行此前两小时或实机写入测试，前面的报告对应各自记录的版本。

桌面锁定阻止实际 UI 输入验证，已请求用户解锁。当前完成组件、实机数据渲染及回放驱动的切页/关闭生命周期检查，尚未将鼠标缩放、游标、历史视口等标记为人工交互验收通过。交互式 Shell 的历史/Tab 补全也待在可交互终端复核。

J-Link 不自动验证 ELF 与已下载固件的身份；位域、复杂 DWARF 位置表达式、未知 MAP 类型不进行猜测性写入。写入限 E507 RAM 内有明确类型的 1/2/4 字节标量。采集历史有界，完整长时输出请使用 NDJSON。

旧 Python 应用/测试/requirements/PyInstaller/启动构建入口已移除，未建立 legacy 目录；配置、日志、导出和 Git 历史保留。自动审批拒绝了对 `dist/frame_demo` 只读构建残留的强制清理，仅返回“blocked by policy”；已停止该清理。此残留不被新产品加载。旧发行档案和第三方环境缓存不构成新程序运行依赖。
