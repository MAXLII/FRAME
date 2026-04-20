# FRAME

Current release: `v1.2.2`

一个面向 Windows 的串口调试上位机项目，使用 `Python + tkinter + pyserial` 开发。

## 关于这个项目

这个项目的当前版本由 AI 编程助手 `Codex` 主导完成。

你现在看到的上位机功能、工程结构整理、脚本梳理、文档补全，以及一部分性能优化工作，都是在明确需求目标后，由 AI 进行连续自主分析、实现、重构和落地完成的。

如果你是第一次接触这个仓库，可以把它理解为一个“由 AI 从需求出发，持续推进到可运行桌面工具”的实际项目样例。

## 关于作者助手

`Codex` 是一个面向工程开发场景的 AI 编程助手，能够参与代码实现、问题排查、文档整理、工程重构、构建脚本维护和功能迭代。

在这个项目里，`Codex` 扮演的是一个能够独立推进任务的开发者角色，而不是只提供零散建议的问答工具。

作者很懒，一行代码都没敲，甚至这行也不是作者写的。

它目前已经包含这些主要能力：

- 串口枚举、打开与关闭
- 波特率、数据位、校验位、停止位配置
- 文本 / HEX 接收显示
- 文本 / HEX 发送
- 定时发送
- 接收时间戳显示
- 接收内容清空与保存
- 原始接收字节流持续保存到文件
- 快捷发送配置
- 主页状态显示与配置
- 参数读写
- 参数波形显示、导入导出与交互查看
- 固件升级
- 设备固件版本查询
- Black Box 范围查询与 CSV 导出
- Factory Mode 时间设置与校准

## 适用环境

- 操作系统：`Windows 10` / `Windows 11`
- Python：推荐 `Python 3.12`
- 开发方式：推荐使用项目内 `.venv` 虚拟环境
- 安装包构建环境：`Inno Setup 6`

说明：

- 当前 GUI 使用的是 `tkinter`，不是 `PySide6`。
- 运行项目只需要 `requirements.txt` 里的依赖。
- 打包目录版可执行文件时，脚本会自动安装 `PyInstaller`。
- 打包安装包时，除了 `PyInstaller` 之外，还需要本机安装 `Inno Setup 6`。

## 快速开始

### 1. 克隆仓库

```powershell
git clone <your-repo-url>
cd FRAME
```

### 2. 创建虚拟环境

```powershell
python -m venv .venv
```

### 3. 激活虚拟环境

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

CMD:

```bat
.\.venv\Scripts\activate.bat
```

### 4. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 5. 启动程序

```powershell
python .\main.py
```

## 一键启动脚本

如果你不想手动建环境，可以直接运行：

```bat
run_serial_debug_assistant.bat
```

这个脚本会自动执行以下流程：

1. 检查 `.venv` 是否存在
2. 如果不存在，则自动创建虚拟环境
3. 安装或更新 `requirements.txt` 中的依赖
4. 启动 `main.py`

适合第一次运行或给非开发同事直接使用。

## 常用脚本说明

### `main.py`

项目主启动入口。

```powershell
python .\main.py
```

### `run_serial_debug_assistant.bat`

开发/调试用一键启动脚本。会自动准备 `.venv` 并运行程序。

```bat
run_serial_debug_assistant.bat
```

### `build_frame_exe.bat`

构建目录版可执行程序。

```bat
build_frame_exe.bat
```

脚本行为：

1. 创建或复用 `.venv`
2. 安装 `requirements.txt`
3. 安装 `PyInstaller`
4. 清理旧的 `dist/frame`
5. 构建 `dist/frame/frame.exe`

输出目录：

```text
dist/frame/
```

### `build_frame_installer.bat`

构建 Windows 安装包。

```bat
build_frame_installer.bat
```

脚本行为：

1. 先调用 `build_frame_exe.bat`
2. 检查本机是否安装 `Inno Setup`
3. 调用 `installer/frame_installer.iss`
4. 生成安装包

前置条件：

- 本机已安装 `Inno Setup 6`
- 安装完成后可以找到 `ISCC.exe`

输出目录：

```text
dist/installer/
```

如果本机没有安装 `Inno Setup 6`，脚本会给出下载提示。

### `clean_build_artifacts.bat`

清理构建产物和 Python 缓存。

```bat
clean_build_artifacts.bat
```

会清理这些内容：

- `build/`
- `dist/`
- 各级 `__pycache__/`
- `*.pyc`
- `frame.spec`

## 推荐的开发启动方式

如果你是开发者，推荐使用下面这组命令：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python .\main.py
```

如果你只是想快速运行项目，推荐直接双击：

```text
run_serial_debug_assistant.bat
```

## 项目结构

```text
FRAME/
├─ docs/                         # 文档
├─ installer/                    # Inno Setup 安装包脚本
├─ serial_debug_assistant/       # 主应用包
│  ├─ app_paths.py               # 运行路径、数据目录与迁移
│  ├─ constants.py               # 常量定义
│  ├─ debug_logger.py            # 日志写入器
│  ├─ firmware_update.py         # 固件升级辅助逻辑
│  ├─ models.py                  # 数据模型
│  ├─ protocol.py                # 协议编解码
│  ├─ services/                  # 串口服务层
│  └─ ui/                        # 界面层
├─ main.py                       # 启动入口
├─ requirements.txt              # 运行依赖
├─ run_serial_debug_assistant.bat
├─ build_frame_exe.bat
├─ build_frame_installer.bat
└─ clean_build_artifacts.bat
```

## 运行数据位置

源码直接运行时，程序会在仓库目录下使用这些目录：

- `config/`
- `exports/`
- `logs/`

安装版运行时，用户数据默认存放在：

```text
%LOCALAPPDATA%\FRAME\
```

这意味着升级安装版时，快捷发送配置、导出文件和日志可以保留。

## 依赖说明

当前运行依赖写在 `requirements.txt`：

```text
pyserial>=3.5,<4.0
```

GUI 使用的是 Python 标准库中的 `tkinter`，不需要单独安装。

## 打包说明

### 构建目录版

```bat
build_frame_exe.bat
```

构建完成后可直接运行：

```text
dist/frame/frame.exe
```

### 构建安装包

```bat
build_frame_installer.bat
```

如果这是第一次在这台机器上打安装包，请先安装：

- `Python 3.12`
- `Inno Setup 6`

构建完成后安装包位于：

```text
dist/installer/FRAME-Setup-1.2.2.exe

### 构建 `DR_SSIP_Monitor` 命名安装包

```bat
build_dr_ssip_monitor_installer.bat
```

这个脚本会先复用默认的 `build_frame_exe.bat` 构建 `dist/frame/frame.exe`，
然后额外生成一个安装包文件名为：

```text
dist/installer/DR_SSIP_Monitor-Setup-1.2.2.exe
```
```

## 文档

- 工程设计文档：[docs/ENGINEERING_DESIGN.md](docs/ENGINEERING_DESIGN.md)
- AI 协作规则：[docs/AI_WORK_RULES.md](docs/AI_WORK_RULES.md)

## 说明

- 当前项目主要面向 Windows 桌面使用场景。
- 如果你准备开源发布，建议同时补充：
  - `LICENSE`
  - GitHub Release 使用说明
  - 串口协议说明或示例设备说明
