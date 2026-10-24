@echo off
setlocal
chcp 65001 >nul

set "framePowerShell=powershell.exe"
where.exe /q pwsh.exe
if not errorlevel 1 set "framePowerShell=pwsh.exe"

echo 正在构建 FRAME 安装包，请勿关闭窗口。
echo.
"%framePowerShell%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-installer.ps1" %*
set "frameExitCode=%ERRORLEVEL%"
echo.
if "%frameExitCode%"=="0" (
    echo 安装包构建成功，输出目录：
    echo "%~dp0dist\installer"
) else (
    echo 安装包构建失败，错误码：%frameExitCode%。请查看上方错误信息。
)
echo.
pause
exit /b %frameExitCode%
