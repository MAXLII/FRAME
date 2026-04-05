# 工程设计

## 工程目录

```text
FRAME/
├─ bl_llc/
├─ docs/
│  ├─ AI_WORK_RULES.md
│  └─ ENGINEERING_DESIGN.md
├─ installer/
│  └─ frame_installer.iss
├─ llc/
├─ serial_debug_assistant/
│  ├─ app_paths.py
│  ├─ constants.py
│  ├─ debug_logger.py
│  ├─ firmware_update.py
│  ├─ models.py
│  ├─ protocol.py
│  ├─ __init__.py
│  ├─ __main__.py
│  ├─ services/
│  │  ├─ __init__.py
│  │  └─ serial_service.py
│  └─ ui/
│     ├─ __init__.py
│     ├─ app.py
│     ├─ debug_tab.py
│     ├─ monitor_tab.py
│     ├─ parameter_tab.py
│     ├─ upgrade_tab.py
│     └─ wave_tab.py
├─ build_frame_exe.bat
├─ build_frame_installer.bat
├─ clean_build_artifacts.bat
├─ main.py
├─ README.md
├─ requirements.txt
├─ run_serial_debug_assistant.bat
├─ 上位机.pdf
└─ 通信.pdf
```

## 工程分层

### 启动入口层

- `main.py` 作为桌面程序启动入口，负责调用 `serial_debug_assistant.ui.app.launch_app`。
- `serial_debug_assistant/__main__.py` 提供包级启动入口，入口行为与 `main.py` 保持一致。
- `run_serial_debug_assistant.bat` 负责创建虚拟环境、安装依赖并启动桌面程序。

### 构建发布层

- `build_frame_exe.bat` 负责准备虚拟环境、安装 `PyInstaller`、清理应用输出目录并生成 `dist/frame/frame.exe`。
- `build_frame_installer.bat` 负责调用目录版构建，并继续执行安装包编译流程。
- `installer/frame_installer.iss` 定义 Windows 安装包的安装目录、快捷方式、卸载入口和覆盖升级行为。
- `clean_build_artifacts.bat` 负责清理构建目录、缓存目录和 Python 编译产物。

### 应用包层

- `serial_debug_assistant/` 目录承载串口调试助手的运行时路径、协议处理、固件升级、串口服务和界面组件。

## 顶层文件与目录职责

### 文档目录

- `docs/AI_WORK_RULES.md` 定义本仓库的 AI 执行规则、Git 提交规则和工程设计文档编写规则。
- `docs/ENGINEERING_DESIGN.md` 说明本工程当前目录和模块设计。

### 参考资料

- `README.md` 说明工程用途、运行方式和打包方式。
- `上位机.pdf` 与 `通信.pdf` 作为仓库中的参考资料文件。

## `serial_debug_assistant` 包设计

### 路径与运行环境

- `app_paths.py` 统一计算源码运行和安装运行两种模式下的安装目录与数据目录。
- `app_paths.py` 负责创建运行数据目录，并处理现有用户数据的迁移。
- `constants.py` 定义窗口尺寸、轮询周期、串口默认参数和串口参数选项。

### 公共数据模型

- `models.py` 定义串口接收块、协议帧、参数项、固件尾部、固件镜像和升级会话的数据结构。

### 协议与业务计算

- `protocol.py` 定义帧结构常量、CRC16 计算、协议帧打包、协议帧解析和参数数值类型转换。
- `firmware_update.py` 定义固件尾部解析、CRC32 校验、版本格式化、模块名称映射和升级报文载荷构造。
- `debug_logger.py` 定义应用日志写入器，并提供日志订阅回调分发能力。

### 服务层

- `services/serial_service.py` 负责串口枚举、串口打开关闭、接收线程管理、接收队列投递和发送写入。
- `services/__init__.py` 作为服务子包入口文件。

### 界面层总控

- `ui/app.py` 负责创建主窗口、侧边栏和标签页，并组织串口连接、协议处理、参数管理、波形显示和固件升级流程。
- `ui/app.py` 负责将串口接收数据分发到监视区、协议解析器、参数页、波形页和升级页。
- `ui/app.py` 负责运行状态显示、计数统计、接收保存和发送控制。

## `serial_debug_assistant.ui` 组件设计

### 串口收发页

- `ui/monitor_tab.py` 定义串口监视页布局。
- `ui/monitor_tab.py` 负责接收区显示、手动发送区、快捷发送区和快捷发送配置持久化。
- `ui/monitor_tab.py` 负责主分栏位置记录和界面布局信息回传。

### 参数读写页

- `ui/parameter_tab.py` 定义参数列表页布局。
- `ui/parameter_tab.py` 负责模块地址输入、参数搜索、参数表格显示、单参数读取、参数写入和波形勾选控制。
- `ui/parameter_tab.py` 负责参数条目的忙碌态、非法态和波形选中态展示。

### 波形页

- `ui/wave_tab.py` 定义波形页布局。
- `ui/wave_tab.py` 负责已选参数列表、实时曲线绘制、最新值列表、窗口时间切换、暂停查看和回到实时视图。
- `ui/wave_tab.py` 负责波形导入导出、标记线、参考线和鼠标交互。

### 固件升级页

- `ui/upgrade_tab.py` 定义固件升级页布局。
- `ui/upgrade_tab.py` 负责固件路径显示、升级地址输入、升级类型选择、进度显示和升级日志显示。
- `ui/upgrade_tab.py` 负责呈现固件版本、编译时间、模块和校验结果。

### 日志页组件

- `ui/debug_tab.py` 定义日志文本显示组件。
- `ui/debug_tab.py` 负责日志路径展示、日志内容追加和显示内容清理。

### 界面包入口

- `ui/__init__.py` 作为界面子包入口文件。

## 模块协作关系

- 启动入口层负责启动 `ui/app.py` 中的主窗口。
- 主窗口负责调用 `SerialService` 完成串口收发，并通过 `FrameParser` 解析协议帧。
- 协议层输出的参数数据进入 `ParameterReadWriteTab` 和 `WaveformTab`。
- 固件文件解析与升级载荷构造由 `firmware_update.py` 提供，升级界面和升级状态流转由 `ui/app.py` 与 `UpgradeTab` 共同组织。
- 构建发布层负责将应用包转换为目录版可执行程序和 Windows 安装包。
