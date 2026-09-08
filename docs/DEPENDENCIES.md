# 原生依赖与构建边界

| 依赖 | 固定版本 / 来源 | 用途 |
|---|---|---|
| LLVM | llvmorg-20.1.8，Git 87f0227cb60147a26a1eeb4fb06e3b505e9c7261 | ELF Object、DWARF 类型解析，静态链接 |
| nlohmann/json | v3.12.0，CMake FetchContent | ABI JSON 信封、数据文件 |
| System.CommandLine | 2.0.11，NuGet | CLI 与 Shell 共用命令定义 |
| ScottPlot.WPF | 5.1.59，NuGet | WPF 波形与 SFRA 图表 |
| SkiaSharp | 3.119.0，由 ScottPlot 依赖锁文件解析 | 图表绘制与原生 x64 运行库 |
| J-Link Commander | 本机 V9.36，外部安装，可用 --jlink-exe 覆盖 | 持续子进程访问已核对探针；不随 FRAME 分发 |

NuGet 完整传递依赖及内容摘要保存在各前端项目的 packages.lock.json。首次构建需要网络；之后通常复用本地缓存。`build/deps/llvm-project` 是第三方源码缓存，不是 FRAME 源码目录。

LLVM 构建系统可能探测 Python 等第三方构建工具；本次仅构建所需库，不构建 LLVM 测试或工具。FRAME 应用、测试、PowerShell 构建/启动脚本不执行旧 Python，运行只需 .NET 10 x64、原生 DLL 及 NuGet 复制的运行依赖。

许可证原文保留在下载的 LLVM LICENSE.TXT、nlohmann/json LICENSE.MIT 及 NuGet 包中。安装脚本收集许可文件，发布自包含 .NET x64 运行库与 MSVC CRT；不使用旧 PyInstaller 发行目录。详见 INSTALLER_RELEASE.md 与 THIRD_PARTY_NOTICES.md。
