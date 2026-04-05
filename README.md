# Serial Debug Assistant

一个基于 `tkinter + pyserial` 的 Windows 桌面串口调试工具，适合在 `Python 3.x + .venv + VS Code` 环境中直接运行和继续扩展。

## 当前工程结构

```text
FRAME/
|-- main.py
|-- requirements.txt
|-- run_serial_debug_assistant.bat
`-- serial_debug_assistant/
    |-- __init__.py
    |-- constants.py
    |-- models.py
    |-- services/
    |   `-- serial_service.py
    `-- ui/
        `-- app.py
```

## 模块说明

- `main.py`：程序启动入口
- `serial_debug_assistant/constants.py`：应用常量和串口参数选项
- `serial_debug_assistant/models.py`：数据模型
- `serial_debug_assistant/services/serial_service.py`：串口连接、读取、写入服务
- `serial_debug_assistant/ui/app.py`：Tkinter 界面和交互逻辑

## 功能

- 串口枚举与刷新
- 串口打开 / 关闭
- 波特率、数据位、校验位、停止位配置
- 接收区实时显示
- 文本 / HEX 接收显示切换
- 发送区文本发送 / HEX 发送
- 定时发送
- 接收时间戳
- 接收内容清空
- 接收数据保存为文本
- 接收原始字节流持续保存到文件
- 收发字节计数

## 运行方式

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\main.py
```

也可以直接双击：

```text
run_serial_debug_assistant.bat
```

## 打包发布

生成可执行目录版：

```text
build_frame_exe.bat
```

生成 Windows 安装包（`Setup.exe`）：

```text
build_frame_installer.bat
```

说明：

- `build_frame_installer.bat` 会先生成 `dist\frame\frame.exe`
- 然后使用 `Inno Setup` 把 `dist\frame` 打成可安装软件
- 如果本机未安装 `Inno Setup 6`，脚本会提示下载地址
- 安装包输出目录为 `dist\installer\`
- 新版 `Setup.exe` 会沿用原安装目录，并在安装前关闭旧版程序后覆盖升级

## 说明

- 界面使用 `tkinter`，无需额外 GUI 框架依赖。
- 串口通信使用 `pyserial`。
- 当前已经按标准小型工程方式完成拆分，后续继续加功能会更方便。
- 安装版的用户数据会保存在 `%LOCALAPPDATA%\FRAME\` 下，升级覆盖不会影响快捷发送配置、导出文件和日志。
