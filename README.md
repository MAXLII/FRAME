# FRAME

Windows x64 设备诊断工作台，版本以根目录 [VERSION](VERSION) 为准。C++20 后端与 C#/.NET 10 前端共用一套业务实现，提供 CLI、持续交互 Shell 和 WPF/XAML 界面。

版本按软件代际区分：`1.x` 为旧 Python 上位机的终版系列，停止后续版本迭代；`2.x` 为 C++/C# 全新上位机系列，不再按目标用户区分。日常提交递增第三位，发布 GitHub Release 时递增第二位并将第三位归零。

本期包含：串口调试、参数读写、参数波形、Scope、实时示波器、SFRA、Perf、Trace、链表顺序与 J-Link。设备连接支持串口和以太网 TCP，CLI 支持 SHUT 固件检查与 E8 下载。旧 Python 应用与测试已移除；不包含 CAN、Factory Mode、Black Box。

## 构建与启动

需要 Visual Studio 2026 C++ x64 工具链、CMake 4、.NET 10 SDK、Git。首次构建获取固定版本 LLVM 源码及 NuGet/CMake 依赖，LLVM 首次编译耗时较长。

```powershell
./scripts/build.ps1 -CliOnly
./frame.ps1 --help
./frame.ps1 serial ports --json
./frame.ps1 shell
./scripts/build.ps1
./frame.ps1 gui
```

直接入口为 `build/app/frame.exe` 和 `build/app/Frame.Desktop.exe`，同目录放置 `frame_backend.dll`，无需 Python。后续回归默认用 CLI/Shell，只有视觉或界面专属行为才打开 UI。

日常调试运行 `./run_dbg.bat`：无改动时直接启动；源码或输出变化时增量构建界面及所需后端，不构建 CLI 或运行测试。`./run_dbg.bat -FullBuild` 执行完整构建和原生测试后启动；`-BuildOnly` 只准备程序、不打开窗口。构建失败不会启动旧程序。

## 开发验证

安装包由 `build_frame_installer.bat` 生成，随包提供运行库。构建、用户数据目录、升级和发布流程见 [安装包与 Release](docs/INSTALLER_RELEASE.md)。

```powershell
ctest --test-dir build/native -C Release --output-on-failure
./tests/cli-smoke.ps1
./tests/soak.ps1  # 16 曲线 × 100 点/秒，默认 7200 秒
```

回放输入是 `tests/fixtures` 下的独立 JSON，不执行旧代码。实机结果独立留证，回放不能替代实机验收。配置、日志和导出目录保留；旧配置尚不自动转换为新界面设置。

## 文档

- [原生软件架构](docs/NATIVE_ARCHITECTURE.md)：Top Down 分层、ABI、线程和数据模型。
- [后端注册与流式协议](docs/STREAM_PROTOCOL_ARCHITECTURE.md)：模块自注册、依赖生命周期、命令与上报分发、协议扩展。
- [详细架构方案](docs/CPP_CSHARP_TOP_DOWN_ARCHITECTURE.md)：设计目标与阶段门槛。
- [CLI / Shell 手册](docs/CLI_REFERENCE.md)：功能命令、退出码、NDJSON、任务与数据集。
- [实时示波器](docs/help/realtime-scope.md)：参数选通、独立数据链路、触发、游标与历史波形。
- [验证记录](docs/NATIVE_VALIDATION.md)：构建、回放、E507、UI、持续运行证据及未完成项。

源码在 `backend/` 和 `frontend/`，统一脚本在 `scripts/`。历史协议资料继续保留；旧 Python 工程说明中的启动/构建命令不再适用。
