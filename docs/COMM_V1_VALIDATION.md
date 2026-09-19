# COMM v1 (0xE9) 验证记录

记录 FRAME 后端对 COMM v1（0xE9）协议的支持与验证结果。协议定义与设备侧实现见 ATOMAN `docs/comm_v1_protocol.md` 及 `docs/test/comm_v1_test_report.md`。

## 实现

| 文件 | 内容 |
|---|---|
| `backend/src/protocol.hpp/.cpp` | `sum`、DICT/RLE/LZSS/ZERO codec（内置码本与设备侧一致）、`encode_v1`（压缩择优、CODEC_SELECT 强制 RAW、范围检查）、`codec_select_request`、`is_codec_select_response`、`codebook_crc32`；`parser::feed` 同时解析 0xE8 与 0xE9 帧（SUM 校验、解压、非法帧拒绝） |
| `backend/src/frame_protocol_module.cpp` | `receive_packet` 校验 CODEC_SELECT 响应及目标、SEQ；`send` 按发送模式选择编码，E9 使用 SEQ 0~7 循环，ACK 匹配请求协议及 SEQ |
| `backend/src/runtime.hpp` | `comm_v1_negotiated`、`comm_v1_next_seq`、`probe_comm_v1` 及待应答请求身份 |
| `backend/src/services.cpp` | 连接成功后重置 v1 状态并发探测 |
| `backend/src/transport.hpp` | `replay_active()`：replay 传输不探测，保持回放序列稳定 |
| `tests/native/comm_v1_tests.cpp` | codec、SUM、编码 golden、解析、协商、混合协议流测试 |
| `CMakeLists.txt` | `frame_comm_v1_tests` 目标与 `comm_v1` ctest 用例 |

## 行为约定

- `e8` 不探测；`e9` 与 `auto` 连接后发送 `CODEC_SELECT` 探测。响应须来自当前目标、回显探测 SEQ，且 result=0、codec=1、codebook_id=0、version=1、CRC32 小端值为 `0xB6DD009D`。`auto` 在成功后改用 E9；强制 `e9` 在成功前发送 RAW、成功后允许压缩。
- 地址超出 v1 位宽（dst>15 / dynamic_dst>7）或 replay 传输时跳过探测。
- 发送端压缩择优与设备侧一致：RAW 永远候选；`raw<=16` 省 2 B、`raw>16` 省 `max(2, ceil(raw/16))`；1~16 B 试 DICT，17~63 B 试 DICT+RLE，64~256 B 试 DICT+RLE+LZSS，所有长度另试 ZERO。

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

- 后端 `runtime::monitor(kind, bytes, source)` 把 `user_tx` / `protocol_tx` / `rx` 三类块按 30 ms 节流批量推送到 `serial_monitor` 事件（带会话 `epoch`）；轮询、连接切换和断开前会 flush 残留缓冲，保留最后一批收发。`source` 区分串口页原始收发和其他页面的协议通信，接收沿用当前原始/协议接收任务的归属。
- 前端 `BackendClient.Monitor` 全局订阅，`RichTextBox` 三色渲染；UTF-8 文本模式合并连续 RX 分片后整体转码；HEX 模式逐条显示。实时与历史显示均保留不超过 512 条、64 KiB 原始字节的尾部，显示裁剪不修改可导出的原始数据。
- 断开和重连保留现有显示，只有手动清空或打开另一份历史文件才主动替换显示内容；原有 512 条/64 KiB 显示预算继续生效。旧快照不会覆盖新会话状态，重连时恢复到最新位置。
- 向上滚轮或拖动滚动条查看历史时冻结显示文档和滚动位置，接收及有界缓存继续工作；滚动到底部自动恢复跟随，显示期间累积的新数据。
- 串口页新增「显示其他页面通信」开关，默认关闭，选择随设置保存。开启后显示其他页面的协议 TX/RX；关闭时隐藏已有协议记录且不再追加这些记录，不影响其他页面业务及串口页收发。
- UI 回归：串口页三色文本/HEX 渲染、清空显示、导出保留、TCP 探测帧跳过与连接切换，见 `tests/ui`（`Program.cs`、`ConnectionSwitchTests.cs`、`SectionRefreshTests.cs`、`ParameterStreamingTests.cs`）。

## 稳定性修复（噪声设备场景）

- 设备持续上发数据时，显示缓存同时限制记录数和字节数，渲染交由 250 ms 刷新周期统一执行。
- 事务超时或取消（code=4/130）会关闭连接、清空解析状态并使会话失效；重试前必须重连，防止没有事务序号的 E8 迟到 ACK 污染下一次操作。E9 还校验直接响应的 SEQ。
- 回归：`tests/ui` 新增噪声压力用例（200 块/秒 × 4 秒：监视有界、断开正常完成）；`e9_loopback` 原生测试覆盖 E9 协商 + 参数列表端到端闭环。

## 实机验证记录（2026-09-19，GD32E507 目标板）

固件经 SEGGER J-Link 烧录（Flash 139264 B，Program & Verify OK）。E9 会话（wire=e9）在串口与以太网 TCP 均刷出参数列表，全链路帧均为 0xE9：

```text
TX 探测帧: E910040000070100019D00DDB636
TX 请求帧: E91104224060
RX 参数条目（E9 帧）: E90A0882001708070000022000000220000002200046414C5F544553547B ...
```

原记录中的协商响应 `E90808808008000100019D00DDB6B3` 有命令位和 SUM 错误，已撤出实机样例。依据协议及设备源码构造的回归向量为 `E90808008008000100019D00DDB6B3`，这是构造向量，不能冒充重新提取的实机日志。上面的参数列表历史记录不证明主机协商或压缩发送成功；修复后仍需重新进行实机协商与压缩发送验证。

完整历史帧序列的原记录位置为 `logs/communication/*.jsonl`（tx_begin / rx_begin 事件，`probe:true` 标记探测帧）。设备侧主动上报行为见 ATOMAN `docs/test/comm_v1_test_report.md`。

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

## 评审修复验证（2026-09-19）

- 原生目标重新构建，ctest 6/6 通过；协商测试使用独立的小端固定向量，闭环校验实际 SOP、协商成功状态，并注入错误 SEQ 的迟到 ACK。
- 闭环模拟器使用 future 发布监听就绪状态；监听、接收和异常清理均有界，主线程仅在线程结束后读取测试结果。
- WPF 全套回归通过，覆盖同 epoch 事件保留、旧快照/旧事件拒绝、单个大块及总显示配额、断开保留、暂停滚动、到底部/重连恢复跟随和其他页面 TX/RX 显示开关；原生回归另验证断开前最后一批记录保留和来源标记。移除了为绕开新会话清空窗口而添加的固定等待。
- AddressSanitizer 针对 ZERO 小缓冲区越界复现通过，四种 codec 的 1~256 B 长度往返检查共 1024 例通过。
- 已重新生成 CLI/桌面程序并更新 `build/app`。以上为主机验证；本轮未重新烧录固件或执行实机协商、压缩发送测试。
