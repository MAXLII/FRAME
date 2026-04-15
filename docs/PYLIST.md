# Python 环境、库与工具清单

本文档记录当前工程 `.venv` 虚拟环境中的 Python 版本、已安装第三方库版本，以及本工程会用到的外部工具，便于环境复现、问题排查和开源说明维护。

## 当前 Python 版本

- Python: `3.12.10`
- 虚拟环境路径: `.\.venv`

## 说明

- 以下内容来自当前 `.venv` 的实际安装结果，而不是手工推测。
- 这些库里既包含项目运行需要的依赖，也包含打包发布和文档整理时使用的辅助依赖。
- 当前项目 GUI 实际使用的是 `tkinter`，不是 `PySide6`；`PySide6` 目前存在于环境中，但不是当前主程序运行所必需的核心依赖。
- 本文后半部分额外补充了 `.venv` 之外的外部工具，例如安装包生成工具。

## 已安装库清单

| 库名 | 版本 | 作用说明 | 与本项目关系 |
| --- | --- | --- | --- |
| `altgraph` | `0.17.5` | `PyInstaller` 依赖库，用于分析模块依赖图。 | 打包依赖 |
| `packaging` | `26.1` | Python 包版本与依赖处理基础库。 | 打包/安装工具依赖 |
| `pefile` | `2024.8.26` | Windows PE 文件解析库。 | `PyInstaller` 在 Windows 下的依赖 |
| `pip` | `25.0.1` | Python 包安装工具。 | 环境管理工具 |
| `pyinstaller` | `6.19.0` | 将 Python 工程打包成 Windows 可执行程序。 | 构建 `frame.exe` 所需 |
| `pyinstaller-hooks-contrib` | `2026.4` | `PyInstaller` 的额外 hooks 集合。 | 打包依赖 |
| `pypdf` | `6.10.1` | PDF 文档读取与文本提取库。 | 本次整理 PDF 协议文档时使用，不是主程序运行依赖 |
| `pyserial` | `3.5` | 串口通信库。 | 当前上位机核心运行依赖 |
| `PySide6` | `6.11.0` | Qt for Python 主库。 | 当前环境已安装，但现有 GUI 未使用 |
| `PySide6_Addons` | `6.11.0` | `PySide6` 附加模块集合。 | `PySide6` 依赖 |
| `PySide6_Essentials` | `6.11.0` | `PySide6` 核心模块集合。 | `PySide6` 依赖 |
| `pywin32-ctypes` | `0.2.3` | Windows API ctypes 封装。 | `PyInstaller` 在 Windows 下的依赖 |
| `setuptools` | `82.0.1` | Python 打包与安装基础工具。 | 环境管理工具 |
| `shiboken6` | `6.11.0` | `PySide6` 绑定生成运行时库。 | `PySide6` 依赖 |
| `wheel` | `0.46.3` | Python wheel 包构建支持库。 | 环境管理工具 |

## 按用途分类

### 运行上位机实际需要

- `pyserial 3.5`

补充说明：

- 当前工程入口是 `main.py`，GUI 使用 Python 标准库 `tkinter`，因此 `tkinter` 不会出现在 `pip list` 结果中。
- `tkinter` 来自 Python 标准库，只要安装的是标准 Windows 版 Python，一般会随 Python 一起提供。

### 可选安装但当前代码未直接使用

- `PySide6 6.11.0`
- `PySide6_Addons 6.11.0`
- `PySide6_Essentials 6.11.0`
- `shiboken6 6.11.0`

补充说明：

- 这些库已经安装在当前 `.venv` 中。
- 现有上位机代码并没有切到 Qt 界面框架，因此它们目前属于预备环境，不是必须依赖。

### 打包发布相关

- `pyinstaller 6.19.0`
- `pyinstaller-hooks-contrib 2026.4`
- `altgraph 0.17.5`
- `pefile 2024.8.26`
- `pywin32-ctypes 0.2.3`
- `packaging 26.1`

### 环境管理基础工具

- `pip 25.0.1`
- `setuptools 82.0.1`
- `wheel 0.46.3`

### 文档整理辅助工具

- `pypdf 6.10.1`

补充说明：

- `pypdf` 是为了提取仓库根目录 PDF 资料中的协议内容而安装的。
- 它不影响上位机运行，也不是打包安装包的必要前置条件。

## 工程会用到的外部工具

下面这些工具不属于 `.venv` 内的 `pip` 包，但当前工程在运行、构建或发布过程中会实际使用到。

| 工具名 | 推荐/当前版本 | 用途说明 | 与本项目关系 |
| --- | --- | --- | --- |
| `Python` | `3.12.10` | Python 运行时。 | 当前项目开发与运行基础环境 |
| `tkinter` | 随 Python `3.12.10` 提供 | 标准库 GUI 组件。 | 当前上位机实际界面框架 |
| `py launcher` (`py`) | 跟随 Windows Python 安装 | Windows 下的 Python 启动器。 | `build_frame_exe.bat` 用它优先创建 `.venv` |
| `PowerShell` | Windows 自带 | 脚本执行、环境激活、目录清理。 | 构建脚本和 README 示例命令使用 |
| `Inno Setup 6` | `6.x` | Windows 安装包生成工具，核心编译器为 `ISCC.exe`。 | `build_frame_installer.bat` 构建安装包所必需 |

### 外部工具说明

#### Python 3.12.10

- 当前 `.venv` 使用的 Python 版本就是 `3.12.10`。
- `main.py`、`run_serial_debug_assistant.bat`、`build_frame_exe.bat` 都依赖本机先有可用的 Python。
- `build_frame_exe.bat` 会优先尝试使用 `py -3`，找不到时再尝试 `python`。

#### tkinter

- `tkinter` 属于 Python 标准库，不会出现在 `pip list` 里。
- 当前主程序界面就是基于 `tkinter` 开发的，因此它虽然不是单独安装的第三方库，但确实属于项目运行依赖的一部分。

#### PowerShell

- README 中默认给出了 `PowerShell` 下的 `.venv` 激活命令。
- `build_frame_exe.bat` 在清理旧的 `dist/frame` 目录时，也会调用 `powershell -NoProfile -ExecutionPolicy Bypass` 执行删除逻辑。

#### Inno Setup 6

- 这是当前工程生成 Windows 安装包时最关键的外部工具。
- `build_frame_installer.bat` 会优先在这些常见位置查找 `ISCC.exe`：
  - `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`
  - `%ProgramFiles%\Inno Setup 6\ISCC.exe`
  - `%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe`
- 如果默认路径里找不到，脚本还会继续尝试从 `PATH` 中查找 `ISCC.exe`。
- 如果没有安装 `Inno Setup 6`，脚本会直接报错并提示下载地址。

### 工具与流程对应关系

- 运行源码版上位机：
  - `Python 3.12.10`
  - `tkinter`
  - `.venv` 内的 `pyserial 3.5`
- 构建目录版 `frame.exe`：
  - `Python 3.12.10`
  - `py` 或 `python`
  - `PowerShell`
  - `.venv` 内的 `pyinstaller 6.19.0`
- 构建安装包 `FRAME-Setup-1.1.0.exe`：
  - 上述目录版构建环境全部可用
  - `Inno Setup 6`

## 当前环境结论

当前 `.venv` 可以覆盖以下场景：

- 直接运行当前 `tkinter + pyserial` 版本的上位机
- 构建目录版可执行程序 `frame.exe`
- 为未来迁移到 `PySide6` 预留 Qt 运行环境
- 读取和整理仓库内 PDF 协议资料

如果后续希望把环境收敛成“仅保留项目运行必需依赖”的最小版本，可以优先保留：

- Python `3.12.10`
- `pyserial 3.5`

如果后续希望保留“开发 + 打包”完整环境，则建议继续保留：

- Python `3.12.10`
- `pyserial 3.5`
- `pyinstaller 6.19.0`
- `pyinstaller-hooks-contrib 2026.4`
- `altgraph 0.17.5`
- `pefile 2024.8.26`
- `pywin32-ctypes 0.2.3`
- `packaging 26.1`
