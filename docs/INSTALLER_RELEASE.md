# 安装包与 Release

## 版本规则

根目录 `VERSION` 是唯一版本号来源，格式 `a.b.c`，遵循 `AI_WORK_RULES.md` 第 3.11 节：`a` 表示软件代际，`1.x` 为旧 Python 上位机的终版系列，停止后续版本迭代；`2.x` 为 C++20 后端与 C#/.NET 前端开发的全新上位机系列，不再按目标用户区分版本。`b` 表示大功能版本，`c` 表示小功能和后端优化版本。这不是按破坏兼容性定义主版本的 SemVer。

CMake、后端 DLL 文件版本、.NET 程序版本和安装包均读取该文件。功能、构建和文档按职责提交，最后单独提交版本号。ABI 版本、数据文件格式版本独立，不随产品版本修改。

## 构建

需要 VS 2026 C++ x64、CMake、Git、.NET 10 SDK 和 Inno Setup 6。已安装 Inno Setup 的非默认位置可用 `-IsccPath` 指定。

```powershell
./build_frame_installer.bat
# 后端已按当前 VERSION 构建并验证时：
./scripts/build-installer.ps1 -SkipNative
```

脚本构建并测试后端，在唯一的 `build/package/` 子目录发布 Windows x64 自包含 CLI/WPF，复制后端 DLL、MSVC CRT 和许可文件，然后生成：

- `dist/installer/FRAME-Setup-<版本>.exe`
- 同名 `.exe.sha256`
- 同名 `.exe.manifest.json`（构建提交与安装文件哈希）

每次重新构建使用新的暂存目录，避免混入旧文件；脚本不删除历史产物。安装包不包含用户配置、日志、导出、ELF/MAP、探针程序或 Python 源码/运行时。

## 安装行为

默认按用户安装到 `%LOCALAPPDATA%/Programs/FRAME`，保留原 FRAME AppId 以支持升级。安装版配置在 `%LOCALAPPDATA%/FRAME/config/native-ui.json`，自动导出在同一数据根目录的 `exports/`。开发版仍使用仓库目录；`FRAME_DATA_DIR` 可显式覆盖数据根目录。

开始菜单提供 GUI 和持续 Shell；安装目录加入用户 PATH。直接运行 `frame.exe` 是 CLI，GUI 使用 `Frame.Desktop.exe` 或开始菜单快捷方式，也可调用安装目录 `frame.bat gui`。卸载不删除用户数据。旧 Python `_internal` 与旧 `frame-cli.exe` 是升级时清理的已知应用文件，其他目录不清空。

验证模式：安装器 `/FRAMEVALIDATE=1 /DIR=<工作区测试目录> /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS` 仅部署负载，不注册卸载、不修改 PATH、不创建快捷方式或启动 GUI，用于隔离安装验证。

## 发布

提交并推送全部发布变更后，重新从发布提交构建安装包：

```powershell
./scripts/build-installer.ps1
./scripts/publish-release.ps1 -NotesFile docs/releases/2.0.1.md
```

发布脚本核对工作区、VERSION、upstream、安装包版本、构建提交和 SHA-256；推送对应标签，先创建草稿并上传三个文件，核对附件大小后公开为 Latest。已有 Release 或指向不同提交的标签不会被覆盖。根目录历史 `publish_github_release.ps1` 属于旧 Python 流程，不再使用。
