# 后端注册机制与流式协议

## 目标和分层

后端通过模块自注册组织业务。参考 base 的 `REG_SECTION_FUNC`、分类扫描和 `link_process()`：模块声明自身入口，运行时负责装配、调度和会话生命周期。C ABI、C# Client、WPF 与已有 FRAME 线上字段保持兼容。

```text
模块静态描述 (.frmod$m)
  → BackendRegistry 扫描 / 冲突校验 / 依赖排序 / 冻结
  → 服务初始化 → 核心执行器与探针执行器

CLI / Shell / WPF → C ABI → 操作队列 → 注册命令处理器
串口 / TCP → StreamLink → 已选协议解码器 → 注册上报处理器
                                            → 未消费的包进入事务匹配队列
```

## 注册种类与代码归属

| 注册项 | 声明内容 | 调度职责 |
| --- | --- | --- |
| Service | 名称、依赖、启动、关闭、断开通知 | 启动按依赖顺序，关闭与断开按逆序；启动失败回滚已进入的服务 |
| Commands | 组、动作、处理器、执行队列、传输需求、协议、进度事件类型 | 精确匹配后执行；未知命令在访问设备前拒绝 |
| Protocol | 协议名称、解码器工厂 | 每个会话创建独立解码器；连接前校验所选协议 |
| Report | 协议、命令组、命令字、处理器 | 主动上报按注册项派发；ACK 保留给事务匹配 |
| Stream | 数据准备、停止、完整性收尾、记录保留上限 | 通用采集调度器执行模块提供的策略 |

`backend_registry.*` 实现注册表与链接段扫描。`runtime.cpp` 管理操作、事件、收发调度、缓存和收尾，`services.cpp` 实现通用命令调度与连接切换。

业务入口归属如下：

- `system_module.cpp`：连接、断开、状态、以太网搜索、注册目录查询。
- `frame_protocol_module.cpp`：FRAME 解码器工厂、地址过滤、编码发送和 ACK 事务匹配。
- `serial_module.cpp`：端口、波特率和原始收发。
- `param_module.cpp`：参数字典、读写、上报配置及进度事件。
- `data_module.cpp`：数据集查询、视口、清除、导出入口。
- `acquisition_module.cpp`：参数波形与 Trace 的命令、主动上报、数据准备和采集收尾。
- `capture_module.cpp`：Scope 与 SFRA 的对象命令；SFRA 扫频点和完成上报。
- `perf_module.cpp`、`section_module.cpp`、`jlink.cpp`：各自业务命令，J-Link 声明探针队列与独占写入策略。

注册描述只保存常量名称和安装函数。设备连接、解码半帧、参数字典、波形历史及探针均属于 runtime 会话，不存入进程全局注册描述。

## 模块自注册

模块源文件内部提供安装函数，并在文件末尾使用 `FRAME_REGISTER_MODULE(唯一符号, 安装函数)`。安装函数向注册表声明 Service 及其 Commands、Protocol、Report 或 Stream。

当前 Windows x64 / MSVC 构建使用 `.frmod$a`、`.frmod$m`、`.frmod$z` 链接段和 `/include` 保留符号。无需维护中央模块调用列表，也不依赖跨翻译单元的动态构造顺序。新增源文件仍需加入 CMake 构建列表；若以后将模块装入静态库，须保证归档成员被链接进 DLL。其他工具链需要实现对应段枚举机制，当前不宣称跨平台可用。此机制是编译期模块装配，不是外部 DLL 热加载。

服务依赖缺失、循环依赖、重复命令/协议/上报/采集组、未注册的所属服务及引用不存在协议均会拒绝。完成校验后冻结注册表。初始化失败时逆序调用关闭函数，包括已进入但启动失败的服务；关闭函数必须无异常且能清理部分初始化状态。

## 扩展协议和业务

1. 新建模块，实现 `StreamDecoder::Name / Feed / Reset`。解码器自行定义包头、长度、CRC、噪声重同步及缓存上限。非 FRAME 协议可使用自己的消息类型，不必生成 FRAME `packet`。
2. 在模块内注册协议工厂和业务命令。业务处理器接收会话与操作，按需使用传输、取消、截止时间、数据集及事件设施。FRAME 格式的主动上报可使用 Report 注册；其他消息模型由其协议模块自己分发。
3. 命令声明需要的协议与执行队列；长期采集再注册 Stream 策略。原有 FRAME 业务命令要求 `frame-v1`，不会自动套用到新协议。
4. 加入 CMake 源文件列表后，用 `frame.exe backend catalog --json` 检查实际装配。通过 `connect --protocol 名称` 选择已实现协议。默认 `frame-v1`，WPF 当前仍使用默认协议。
5. 新增用户可见 CLI 命令时，补充 CLI 命令定义和必要选项；Shell 复用这些定义。后端自注册不会自动生成 WPF 页面或任意 CLI 参数。
6. 添加协议回放、拆包/粘包、取消、超时、重连和异常输入测试，再开展实机验证。

## 流式执行与边界

`StreamLink` 按有界字节块分发。所有已装配消费者按线序收到相同数据，各自跨调用保存半帧；默认单协议，连接切换会重建接收链。仅当明确配置且格式可区分时才使用多个独立解码器，广播字节不等于自动识别协议。

- 每个链路使用单个核心执行器；解码器上限 8，开始接收后不允许追加。
- 接收队列上限 256 KiB，超限整块拒绝，不静默截断半帧。
- 每轮默认处理 16 KiB，积压优先于下一次读取。字节预算不是严格时间预算，回调不能阻塞等待 ACK。
- 重连、断开和解码失败清除接收积压及半帧。异常前已产生的事件不会回滚，失败输入不会重复派发。
- J-Link 走独立探针执行器。注册策略保留与采集互斥的写入保护；读取不占用核心执行器。
- FRAME 上报仍保留 PLECS 新仿真代际清除、MCU 时间语义、SFRA 标签与版本检查、Trace 过滤、波形历史及缺样判定。

## 自测入口

```powershell
cmake --build build/native --config Release --target frame_registry_tests frame_stream_tests frame_runtime_tests
ctest --test-dir build/native -C Release --output-on-failure
./tests/cli-smoke.ps1
./build/app/frame.exe backend catalog --json
```

注册单元测试使用独立测试宿主，验证链接段保留、冲突、依赖、路由、启动回滚和逆序关闭。C ABI 运行时测试使用真正的后端 DLL，覆盖业务回放和模块装配。流式测试中的文本协议是扩展性测试夹具，不是已交付的设备协议。回放和模拟探针结果不代替实机验收。

### 2026-09-10 本地验证结果

- Release 原生构建通过；注册、协议、流式链路、运行时四组 CTest 全部通过。
- CLI/Shell 冒烟通过：注册目录、未知协议拒绝、持续会话、JSON/NDJSON、退出码、实际 Ctrl+C 与停止 ACK。
- C# CLI 与 WPF 产品构建通过，零警告、零错误。
- WPF 集成测试通过：九页面、增量参数、采集、脱离窗口、J-Link 结构体链、读回及关闭冲刷。测试工程存在三处既有 nullable 警告。
- 实际装配为 10 个服务、65 个命令入口、1 个协议、5 个上报入口、2 类采集策略。目录输出保存在 `build/registry-catalog.json`；构建和 UI 回归日志为 `build/registry-build.log`、`build/registry-managed-build.log`、`build/registry-ui-tests.log`。
- 本轮使用回放、本地 TCP/UDP 测试端点和模拟 Commander，未进行实机通信或物理鼠标键盘验收；没有修改固件、版本号或发布安装包。
