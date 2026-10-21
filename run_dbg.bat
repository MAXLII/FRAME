@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0scripts\run-debug.ps1" %*
set "frameExitCode=%ERRORLEVEL%"
if not "%frameExitCode%"=="0" (
    echo.
    echo FRAME debug startup failed. The previous build will not be started.
    pause
)
exit /b %frameExitCode%
