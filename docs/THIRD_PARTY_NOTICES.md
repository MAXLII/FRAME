# FRAME 分发依赖

安装包的 `licenses/` 包含依赖包附带的许可文件与 NuGet 元数据。自包含 .NET 发布输出的 LICENSE、ThirdPartyNotices 文件也随程序保留。

| 组件 | 许可 / 来源 |
|---|---|
| FRAME | MIT，安装目录 LICENSE |
| LLVM 20.1.8 | Apache-2.0 WITH LLVM-exception，licenses/LLVM.txt |
| nlohmann/json 3.12.0 | MIT，licenses/nlohmann-json.txt |
| .NET Runtime / Windows Desktop Runtime | MIT 及随运行库提供的第三方声明 |
| System.CommandLine、ScottPlot、ScottPlot.WPF、CommunityToolkit.HighPerformance | NuGet 包许可文件与元数据 |
| SkiaSharp、HarfBuzzSharp 及其原生依赖 | NuGet 包许可文件与第三方声明 |
| Microsoft Visual C++ Runtime | 随 Visual Studio 提供的可再发行运行库，按 Microsoft 软件许可条款分发 |

J-Link Commander、探针驱动、MCU 固件与用户 ELF/MAP 不随安装包分发。
