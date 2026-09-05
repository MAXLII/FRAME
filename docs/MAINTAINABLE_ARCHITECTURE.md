# 可维护架构说明

## 0. 分层后端架构

上位机后端按功能模块、数据池、框架和平台划分职责，但不机械复制嵌入式工程目录：

```text
功能模块    protocol / *_protocol / controllers
               ⇅ 业务只读接口、数据源写入接口
数据池      data_pool/RuntimeStatePool（一份私有运行状态）
框架        framework/ProtocolRuntime（收包、拆帧、路由、发帧）
平台        platform/TransportRegistry -> services（Serial/CAN/Ethernet/Demo）
```

- `RuntimeStatePool` 独占后端共享连接状态。业务侧只能取得不可变快照，传输数据源通过 exchange 接口发布或清除状态。
- `ProtocolRuntime` 只面对字节队列、字节写入口和完整协议帧，不知道串口、CAN 或 TCP 的具体 API。
- `TransportRegistry` 是框架到平台的统一边界，将各服务不同的写接口适配成同一个字节传输契约。
- `ProtocolControllerPorts` 是功能控制器到应用装配根的窄接口。兼容适配器仍接受现有 Tk 应用对象，但控制器核心不再读取任意 UI 成员。
- `CommunicationManager` 保留原有公共 API，作为旧 UI 与新后端之间的兼容门面；本次重构不修改 `serial_debug_assistant/ui/` 下的页面代码和视觉行为。

## 1. 当前应用分层

当前上位机代码按以下职责分层：

```text
main.py
  -> SerialDebugAssistant
      -> 页面装配、全局状态、定时任务
      -> CommunicationManager
          -> RuntimeStatePool
          -> ProtocolRuntime
              -> ProtocolParser / ProtocolSender / ProtocolRouter
          -> TransportRegistry
              -> SerialService / CANService / EthernetService / Demo
      -> EthernetDiscoveryService
          -> IPv4 网卡枚举 / UDP 5000 广播 / 设备响应解析
      -> ProtocolControllerHub
          -> Home
          -> Upgrade
          -> Factory Mode
          -> Black Box
          -> Scope
          -> SFRA
          -> Perf
          -> Trace
          -> Parameter / Wave
```

`SerialDebugAssistant` 是应用装配根，负责创建窗口、页面、通信服务和控制器。

`CommunicationManager` 是稳定的兼容门面。共享连接状态由 `RuntimeStatePool` 持有，协议发送、解析和分发由 `ProtocolRuntime` 调度，串口、CAN、Ethernet TCP 和 Demo 的选择与写入差异由 `TransportRegistry` 隔离。

`EthernetDiscoveryService` 使用独立的短生命周期 UDP socket 搜索局域网设备。发现结果只向连接栏提供 Host 和 TCP Port，不进入 `CommunicationManager` 的收发队列，也不改变已连接 TCP 通道的协议状态。

`ProtocolControllerHub` 负责应用级协议分发顺序。它依赖 `ProtocolControllerPorts` 提供的处理器、当前传输查询和日志能力，而不把 Tk 应用对象当作无限制的服务定位器。新协议功能应优先接入 controller，而不是继续扩展 `app.py` 中的总处理链。

## 2. 接收数据流

```text
设备
  -> SerialService / CANService / EthernetService
  -> rx_queue
  -> CommunicationManager.process_rx()
  -> ProtocolRuntime
  -> ProtocolParser.feed()
  -> ProtocolFrame
  -> ProtocolControllerHub.handle_frame()
  -> 对应功能处理器
  -> 更新页面和业务状态
```

硬件读取线程只写入 `rx_queue`，不直接更新页面。

主线程通过 `process_incoming_data()` 定时消费队列，完成原始数据显示、文件保存、协议拆帧和页面刷新。

## 3. 发送数据流

```text
页面按钮 / 输入操作
  -> SerialDebugAssistant 回调
  -> 业务 payload 构造
  -> send_protocol_frame()
  -> CommunicationManager.send_protocol()
  -> ProtocolRuntime
  -> ProtocolSender
  -> TransportRegistry
  -> SerialService / CANService / EthernetService
  -> 设备
```

页面层只发出操作意图。完整帧头、长度、CRC 和帧尾由协议层统一生成。

## 4. 维护规则

新增功能时按以下顺序组织代码：

1. 在对应 `*_protocol.py` 中定义命令号和 payload 编解码。
2. 在 `models.py` 或功能专属状态文件中定义结构化数据。
3. 在 controller 中处理接收帧和业务状态变化。
4. 在 Tab 页面中只保留控件、输入读取和数据显示。
5. 在 `SerialDebugAssistant` 中只做装配、回调连接和全局状态协调。
6. 在协议或状态机复杂时补充最小测试。

## 5. 数据与显示边界

业务逻辑使用结构化数据对象、协议 payload、ELF/DWARF 元数据和 J-Link 读取到的内存 bytes 作为输入。

页面中的文本只用于展示、复制和用户编辑输入。核心逻辑不从表格显示值、状态栏文本或格式化字符串反向解析地址、类型、指针值或协议字段。

J-Link 变量页遵循以下规则：

1. 变量地址、类型、大小、结构体成员和数组成员来自 ELF/DWARF 或 MAP 解析结果。
2. 指针展开使用内存读取结果中的指针数值字段，不解析 `Value` 列中带符号名的显示文本。
3. 树节点展开使用界面行 ID 区分不同路径下的同名字段。
4. 刷新已展开内容时只读取当前可见变量行。
5. 写入入口只接受用户编辑后的值，写入前按变量类型编码为 bytes，并限制写入范围。

## 6. 重构边界

`app.py` 后续不再新增长 `cmd_set / cmd_word` 判断链。

已有功能迁移时保持以下顺序：

1. 先把接收帧处理迁到 controller。
2. 再把请求发送方法迁到 controller。
3. 最后把散落状态收进功能状态对象。

每次迁移只处理一个功能域，例如 Scope、SFRA、Perf 或 Upgrade。
