# 可维护架构说明

## 1. 当前应用分层

当前上位机代码按以下职责分层：

```text
main.py
  -> SerialDebugAssistant
      -> 页面装配、全局状态、定时任务
      -> CommunicationManager
          -> SerialService / CANService / Demo
          -> ProtocolParser
          -> ProtocolSender
          -> ProtocolRouter
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

`CommunicationManager` 负责把串口、CAN 和 Demo 统一成字节流通信入口，并负责协议发送、协议解析和帧分发。

`ProtocolControllerHub` 负责应用级协议分发顺序。新协议功能应优先接入 controller，而不是继续扩展 `app.py` 中的总处理链。

## 2. 接收数据流

```text
设备
  -> SerialService / CANService
  -> rx_queue
  -> CommunicationManager.process_rx()
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
  -> ProtocolSender
  -> SerialService / CANService
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
