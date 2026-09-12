# FRAME CLI 与 Shell

新入口是 `build/app/frame.exe`，运行时为 x64 .NET 10 与 `frame_backend.dll`。所有业务共用 C++ 后端；命令无需打开 WPF。下列命令在仓库根目录执行。

```powershell
./scripts/build.ps1 -CliOnly
./frame.ps1 serial ports --json
./frame.ps1 param list --port COM6 --baud 115200 --dst 2 --json
./frame.ps1 shell
```

COM6 是本次 E507 验证枚举结果，其他电脑需先枚举，不能直接照搬。串口默认 115200、8N1、地址 2；连接时不启用 DTR/RTS。

## 公共约定

`backend catalog --json` 查询后端实际注册的服务、依赖、命令、协议、上报和采集处理器。Shell 使用同一命令。连接可传 `--protocol frame-v1`；默认保持 FRAME 协议，未知协议在打开设备前拒绝。新协议需要在后端模块中实现并注册，参数不会凭空启用其他协议。

- `--help`：根命令、命令组、子命令均提供帮助；与 `--json` 组合返回结构化帮助，`--version --json` 返回版本。
- `--port`、`--baud`、`--dst`、`--dynamic-dst`：一次性命令的设备连接参数。
- `--transport tcp --host IP --tcp-port 9000`：以太网 TCP 连接，host 为 IPv4/IPv6 数字地址；连接等待最多 3 秒，同时遵守操作截止时间及取消。省略 transport 时使用串口。
- `--timeout`：操作总超时，毫秒，默认 30000；`--response-timeout`：单响应超时，默认 1500，范围 10～60000。
- `--json`：stdout 仅输出 JSON，诊断与 Shell 任务摘要输出到 stderr。
- `--ndjson`：wave/trace capture 或 start 逐条输出 `kind=record`，历史淘汰时输出 `kind=gap`，最后输出完成结果。重定向可保留整个输出流。
- `--duration`：持续采集时长，秒；`--count`：wave/trace 按收到的记录数提前结束。默认 duration 为 10 秒。
- `--output`：串口接收、采集完成时导出 JSON 或 CSV。文件先写 `.partial` 再替换正式文件。
- `--record`：保存串口收发字节为 NDJSON，用于复现；`--replay`：加载独立 JSON 回放数据。
- `--background`：只在 Shell 中使用，返回任务 ID。
- Ctrl+C：请求取消，活动 wave/trace 发送停止并等待 ACK，结果携带 `stop_confirmed` 与部分数据集 ID。超时后关闭串口，防止迟到 ACK 被下一次连接误用。

JSON 结果为 `operation_id / ok / code / error / data`。解析阶段的错误没有 operation_id。Shell 的 status/jobs 直接返回状态快照。cancel 返回取消请求是否已接受。

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 参数、输入或命令格式错误 |
| 3 | 连接、DLL 加载、传输或 J-Link 进程失败 |
| 4 | 操作或设备响应超时，远端结果可能未知 |
| 5 | 协议格式、回放发送匹配或负载错误 |
| 6 | 部分完成、缺失记录或数据完整性错误 |
| 7 | 设备拒绝、未就绪、读回不一致、访问不受支持 |
| 8 | 文件错误或采集收尾失败；同时检查 stop_confirmed |
| 9 | 资源容量或功能冲突 |
| 130 | 已取消 |

## 命令清单

| 命令组 | 子命令 | 主要参数 |
|---|---|---|
| serial | ports、connect、baud、send、raw | baud（已连接串口即时修改）、hex 或 text、duration、interval、output |
| param | list、read、write、batch-read、batch-write、report | name、value、min、max、input、enable on/off |
| wave | capture、start、stop、status | period、duration、count、output、ndjson |
| ethernet | discover | scan-ms（默认 400）、discovery-port（默认 5000）、host（可选定向搜索目标） |
| scope | list、info、channels、start、trigger、stop、reset、pull | id、output |
| sfra | list、info、configure、start、stop、reset、points | id、start-hz、stop-hz、amplitude、output |
| perf | info、dictionary、summary、samples、start、stop、reset | filter |
| trace | capture、start、stop、status | duration、count、filter 行号列表、output、ndjson |
| section | list、nodes | id 为目录返回的 list_id，不是行号 |
| jlink | connect、disconnect、load、symbols、expand、read、write | path、elf、device、probe、jlink-exe、name、value、filter、offset、limit |
| data | read、view、clear、export、release | dataset、offset、limit、revision、output |

数值写入支持十进制及浮点科学计数法，整数类型拒绝小数和越界，浮点拒绝 NaN/Infinity。param write 会先读取参数目录并按设备上下限校验。普通变量优先以写入 ACK 返回的类型、实际值和上下限确认成功，不再强制额外读取；ACK 超时则重新读取设备目录，核对实际值和上下限，成功结果标记 `verification=directory_readback`、`ack_received=false`，界面取消黄色并提示“ACK 未收到，已通过回读确认”。完整 ACK 确认时标记 `verification=write_ack`。校验失败、回读超时仍报错；取消或操作截止后不再查询，不自动重发写入。命令类型仍要求 ACK，不使用参数回读推断执行成功。

`param write --min ... --max ...` 可显式提交编辑后的上下限；不指定时沿用设备值。后端校验类型、上下限顺序及数据范围，验证返回的上下限与数值。沿用旧 FRAME：目录中上下限原始值相同的普通参数为只读；CMD 的写入载荷为三个零值，界面操作显示“执行”。

WPF 参数表按“参数名称、类型、数据、HEX、最小值、最大值”显示。FP32 显示浮点数（例如 1.0、0.1），HEX 仅用于整数。搜索按字符顺序模糊匹配，忽略空格与大小写；双击数据/上下限编辑，点击写入才发送。双击名称切换上报，Ctrl+C 复制参数名称。修改、忙碌、错误和上报状态分别着色，读取单项保留整张列表。顶部菜单按钮可收起/展开侧边栏，后台任务与当前页面继续存在。

批量输入是 JSON 数组，最大 1024 项。例如读取 `["DEMO_SHELL_COUNTER","DEMO_SHELL_GAIN"]`，写入 `[{"name":"DEMO_SHELL_COUNTER","value":17}]`。返回每项结果，失败项使整体标记 partial 并返回退出码 6。

## 持续 Shell

WPF 顶部选择“以太网 TCP”后填写 IP/端口，再点击连接。默认显示旧版的 `192.168.1.10:9000`，实际值应以设备配置为准。已连接时先断开，再切换连接类型。本次恢复手动 TCP 连接，不包含 UDP 自动发现或 DNS 主机名解析。

```powershell
./frame.ps1 param list --transport tcp --host 192.168.1.10 --tcp-port 9000 --json
```

Shell 中使用 `connect --transport tcp --host 192.168.1.10 --tcp-port 9000`，后续参数、波形等协议命令复用连接。设备帧格式与串口完全相同，不额外封装 TCP 报文。

```text
connect --port COM6 --json
param list --json
param read --name DEMO_SHELL_COUNTER --json
param report --name DEMO_SHELL_COUNTER --enable on --json
wave capture --duration 60 --background --json
status --json
jobs --json
cancel --id 5 --json
data read --dataset 5 --offset 0 --limit 100 --json
data export --dataset 5 --output exports/counter.json --json
data release --dataset 5 --json
disconnect --json
exit
```

任务 ID 按本会话操作递增，应使用实际返回值。Shell 复用连接，历史仅保存于当前会话；Tab 补全命令，单/双引号支持带空格的路径。`frame shell --json` 会让后续命令继承 JSON 输出，提示符与任务摘要写入 stderr。首期没有操作系统管道、变量展开或系统命令执行。重定向标准输入时按序执行，任一命令失败即终止并返回非零状态；退出会取消尚未完成的任务，冲刷导出并关闭后端。

Scope/SFRA 是设备端采集。一次性 start 返回的是启动 ACK，之后应另行查询 info。Scope 在 ready 后执行 pull；SFRA 必须同时满足 done、ready、table_length=count 才执行 points，ready 单独为真可能只有部分频点。拉取按 index/tag 校验。Scope 触发前应等待足够预采样时间。CLI 退出不会擅自停止由设备自行完成的 Scope/SFRA 采集。

```powershell
./frame.ps1 wave capture --port COM6 --duration 60 --ndjson > exports/wave.ndjson
./frame.ps1 jlink symbols --elf 'D:/firmware/device.elf' --filter counter --json
./frame.ps1 jlink read --elf 'D:/firmware/device.elf' --name s_demo_shell_counter --json
```

J-Link 使用持续 Commander 子进程，Shell 连续操作复用连接（connect 结果含 session_reused）；程序通过管道提交命令，以只读 1 字节 E507 SRAM 快照文件确认命令完成，避免依赖厂商程序缓冲的 stdout 提示符。当前默认目标 GD32E507ZE，默认 Commander 路径可通过 `--jlink-exe` 覆盖。ELF 使用 LLVM Object/DWARF，GNU MAP 仅提供地址符号，缺少类型信息时不允许猜测变量大小。结构体、联合体、数组通过 expand 逐层查询，展开后的成员路径在同一会话继续使用。RAM 写入限 E507 SRAM `0x20000000..0x20020000` 内 1/2/4 字节标量；需使用匹配当前固件的 ELF。地址身份未经自动校验，不应使用过期 ELF 写入。

## 数据边界

`--probe` 指定已枚举核对的探针序列号，映射到 Commander 的 `-USB`；本次实机为 69409716。探针序列号改变会重建 Commander 会话。具体开关见 [SEGGER Commander 文档](https://kb.segger.com/J-Link_Commander)。

采集默认按 duration/count 结束；参数波形使用 `--duration 0` 时持续运行至手动停止或 Ctrl+C，WPF 默认使用该模式。显式指定 `--timeout` 时同时受该总截止时间约束，超时先停止设备并保留部分记录。停止未确认会关闭串口并使连接 epoch 失效；退出收尾错误写入 stderr 并返回 8。

参数波形保留本次采集全部原始记录，内存随记录数量增长。`data view --dataset ID --seconds 30` 返回最近 30 秒的绘图抽样；`--seconds 0` 查看全部，或用 `--left`/`--right` 指定历史时间范围。抽样保留分桶首尾及极值，原始数据仍通过 `data read/export` 获取。

主动取消的数据集保留 partial 标记，`data read` 会返回带有效 records 的退出码 6。在非交互 Shell 输入文件中，这会触发失败即退出；若需要继续执行恢复命令，可先用 `data export` 保存，再在进程外读取文件。CLI NDJSON 和 WPF 均显示部分数据。历史容量主动淘汰时，采集结束可成功，但结果明确给出 partial/dropped，不能把历史导出当作完整长时记录。

每个后端最多 128 个未释放操作、32 个数据集，单个采集历史保留约 100000 条记录，达到上限批量淘汰旧记录并累计 dropped。常规 JSON/CSV 导出保留当前历史，发生淘汰会标记 partial；需完整长时记录时使用 NDJSON。读数据集每页最多 10000 条，可指定 --revision 校验同一数据版本；data release 释放已完成历史。

设备批量波形记录缺失/重复索引与时间回绕；旧格式波形使用主机接收时间，帧起止标记不作为参数点。Trace 保留设备 tick 和展开时间。Scope/SFRA 部分拉取失败仍保留已收到的数据集及错误原因。真实串口采集速率受波特率、协议开销和固件上报调度限制。

PLECS 的 `0x40` 批量波形按仿真时间顺序上传：新采样批次（first=0）的时间倒退、且不是 32 位计数器自然回绕时，自动清除上一轮波形，从新仿真重新显示。重新连接后续采保留的数据集，也在收到第一个 PLECS 批量包时清除旧仿真。普通 MCU 的 `0x07` 波形不触发自动清除，停止后续采仍保留历史。

波形页的“清除波形”或 Shell 中 `data clear --dataset <ID> --json` 清除该波形数据集的缓存，保留连接、采集任务和界面曲线分配；停止状态也可清除。后续导出仅包含清除后收到的数据，已保存的文件不受影响。清除会递增 `generation` 并使旧分页 `revision` 失效；NDJSON 输出 `kind=reset` 通知，再从新一代的索引 0 输出记录。

参数波形的鼠标参考线仅显示同步的细竖线。点击“测量时间差”后，依次在绘图区点击两次放置两条竖线；第一条线旁显示该点时间，第二次点击所在的波形框会在第二条线旁显示绝对时间差 Δt，按大小自动使用 s、ms 或 μs。允许反向选点和跨框选点，数据刷新保留测量标记；再次点击按钮开始新的测量，Esc 或“清除测量”图标清除测量。清除波形或开始新仿真时同时清除旧测量标记，采集过程不因测量暂停。“全图”和“全部”均持续更新，不进入暂停显示状态。

WPF 左侧导航支持将页面按钮拖出侧栏，作为独立窗口显示；侧栏展开文字和收起图标两种模式均支持。独立窗口复用原有页面、连接和采集任务，可同时打开多个页面。最小化保留独立窗口，点击侧栏对应页面可恢复显示；点击独立窗口的“×”将页面放回主窗口。退出主窗口会统一关闭独立窗口并完成设备和文件收尾。
