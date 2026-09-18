# COMM v1 (0xE9) 验证记录

记录 FRAME 后端对 COMM v1（0xE9）协议的支持与验证结果。协议定义与设备侧实现见 ATOMAN `docs/comm_v1_protocol.md` 及 `docs/test/comm_v1_test_report.md`。

## 实现

| 文件 | 内容 |
|---|---|
| `backend/src/protocol.hpp/.cpp` | `sum`、DICT/RLE/LZSS codec（内置码本与设备侧一致）、`encode_v1`（压缩择优、CODEC_SELECT 强制 RAW、范围检查）、`codec_select_request`、`is_codec_select_response`、`codebook_crc32`；`parser::feed` 同时解析 0xE8 与 0xE9 帧（SUM 校验、解压、非法帧拒绝） |
| `backend/src/frame_protocol_module.cpp` | `receive_packet` 识别 CODEC_SELECT 响应；`send` 在协商成功后使用 v1 编码与 SEQ 0~7 循环；`probe_comm_v1` 在连接后发协商探测 |
| `backend/src/runtime.hpp` | `comm_v1_ready`、`comm_v1_next_seq`、`probe_comm_v1` |
| `backend/src/services.cpp` | 连接成功后重置 v1 状态并发探测 |
| `backend/src/transport.hpp` | `replay_active()`：replay 传输不探测，保持回放序列稳定 |
| `tests/native/comm_v1_tests.cpp` | codec、SUM、编码 golden、解析、协商、混合协议流测试 |
| `CMakeLists.txt` | `frame_comm_v1_tests` 目标与 `comm_v1` ctest 用例 |

## 行为约定

- 连接后发送 v1 `CODEC_SELECT` 探测（fire-and-forget）；收到合法响应（result=0、CRC32 匹配内置码本 `0xB6DD009D`）后才启用 v1 发送与压缩，否则保持 0xE8。
- 地址超出 v1 位宽（dst>15 / dynamic_dst>7）或 replay 传输时跳过探测。
- 发送端压缩择优与设备侧一致：RAW 永远候选；`raw<=16` 省 2 B、`raw>16` 省 `max(2, ceil(raw/16))`；1~16 B 试 DICT，17~63 B 试 DICT+RLE，64~256 B 试 DICT+RLE+LZSS。

## 发送协议手动切换（GUI 顶端栏）

- 顶端栏新增「协议」下拉列表：`E8 / E9`，**默认 E8**。只切换**发送**方向（`runtime::send` 的编码选择）；接收始终同时解析 0xE8 与 0xE9 帧，不受该选择影响。
- `E8`：旧协议，不探测；`E9`：强制发送 0xE9 帧，连接后发 CODEC_SELECT 协商，协商完成前使用 RAW、完成后自动压缩。
- 连接中切换立即生效：后端 `system/wire` 命令重置协商状态并重新探测（replay 传输不探测，保持回放序列稳定）。
- 连接命令支持 `wire` 参数（默认 `e8`）；选择随界面设置持久化；下拉 ToolTip 显示当前模式与协商结果。
- 后端仍接受 `auto`（CLI 探测模式），运行时默认值为 `e8`。
- 后端回归：connect 的 `wire` 参数校验、连接中 `system/wire` 切换、snapshot 的 `wire` / `v1_negotiated` 字段，见 `tests/native/runtime_tests.cpp`。

## 串口收发数据三色显示

串口调试页实时显示三类数据，按颜色区分（发送和接收都会显示）：

| 颜色 | 前缀 | 来源 |
|---|---|---|
| 蓝 `#1D4ED8` | `→ TX` | 用户手动发送（串口页发送/定时重发） |
| 橙 `#C2410C` | `→ 协议` | 软件（协议）发送的帧，含参数/Scope 等命令与 CODEC_SELECT 探测 |
| 绿 `#047857` | `← RX` | 软件接收的所有字节（协议响应与原始接收） |

实现要点：

- 后端 `runtime::monitor(kind, bytes)` 把 `user_tx` / `protocol_tx` / `rx` 三类块按 30 ms 节流批量推送到 `serial_monitor` 事件（带会话 `epoch`）；前端每次轮询 `frame_events` 时强制 flush 残留缓冲；连接/断开时丢弃上一会话未 flush 的记录。
- 前端 `BackendClient.Monitor` 全局订阅，`RichTextBox` 三色渲染；UTF-8 文本模式合并连续 RX 分片后整体转码，避免多字节序列被拆坏；HEX 模式逐条显示；上限 512 条。
- 新连接会话（epoch 变化）自动清空显示；`system/wire` 切换不改变接收路径。
- UI 回归：串口页三色文本/HEX 渲染、清空显示、导出保留、TCP 探测帧跳过与连接切换，见 `tests/ui`（`Program.cs`、`ConnectionSwitchTests.cs`、`SectionRefreshTests.cs`、`ParameterStreamingTests.cs`）。

## 稳定性修复（噪声设备场景）

- 设备持续上发数据时，监视事件只累积记录（有界 512 条），渲染交由 250 ms 刷新周期统一执行，避免每个事件都全量重建 RichTextBox 导致 UI 卡死与事件队列堆积。
- 事务失败（code=4/130）不再关闭传输会话：只清空未匹配响应并复位解析状态，连接保持，用户可切换协议直接重试。
- 回归：`tests/ui` 新增噪声压力用例（200 块/秒 × 4 秒：监视有界、断开正常完成）；`e9_loopback` 原生测试覆盖 E9 协商 + 参数列表端到端闭环。

## 实机验证记录（2026-09-19，GD32E507 目标板）

固件经 SEGGER J-Link 烧录（Flash 139264 B，Program & Verify OK）。E9 会话（wire=e9）在串口与以太网 TCP 均刷出参数列表，全链路帧均为 0xE9：

```text
TX 探测帧: E910040000070100019D00DDB636
TX 请求帧: E91104224060
RX 协商响应（TCP）: E90808808008000100019D00DDB6B3
RX 参数条目（E9 帧）: E90A0882001708070000022000000220000002200046414C5F544553547B ...
```

完整帧序列见 `logs/communication/*.jsonl`（tx_begin / rx_begin 事件，`probe:true` 标记探测帧）。设备侧主动上报继承请求协议（E9 会话上报 E9、SEQ 循环递增），验证见 ATOMAN `docs/test/comm_v1_test_report.md`。

## 验证结果

```
ctest --test-dir build/native -C Release --output-on-failure
100% tests passed out of 6  (registry / protocol / comm_v1 / stream_link / runtime / e9_loopback)
```

- `comm_v1` 用例覆盖：SUM 已知答案、RLE 文档示例 golden、DICT/LZSS roundtrip 与非法 token、limit 提前停止、码本 CRC32 golden、纯命令帧 golden `E9 0E 08 2A 44 6D`（与设备侧一致）、256 B 帧、压缩选择、CODEC_SELECT 协商、坏 SUM 拒绝、0xE8/0xE9 混合流、任意分块解析。
- 跨端互通（临时验证工具，已移除）：设备产帧 → 主机解析、主机产帧 → 设备解析双向通过；纯命令、RAW、DICT、LZSS 帧两端编码字节一致。
- 实机：串口（COM6）与以太网 TCP（169.254.2.7:5000）E9 参数列表均通过；设备主动上报在 E9 会话下为 0xE9 帧。

## CODEC=100 ZERO 数零法

- nibble 变长编码（`1^k + 0^(m+1) + 1`，k=n>>2、m=n&3），bit MSB-first，尾 bit 补 1；解码时溢出前缀读到输入结束视为 padding。
- 加入 `codec` 枚举与 `codec_encode/decode`、`encode_v1` 择优候选（所有长度）、parser 接受 CODEC≤4。
- 回归：0~F 码表 golden `48 86 CC 61 DC E3 87 BC F1 E1`（与设备侧一致）、全零压缩、padding/未终止拒绝、limit 停止；ctest 6/6、UI 全套通过。
- 实机：串口条目帧 ZERO 17/23、TCP ZERO 22/36，参数列表正常。
