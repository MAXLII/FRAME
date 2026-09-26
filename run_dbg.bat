@echo off
setlocal
set "FRAME_COMM_LOG_DIR=%~dp0logs\communication"
echo Communication logs: %FRAME_COMM_LOG_DIR%
powershell.exe -NoProfile -File "%~dp0scripts\build.ps1" -Configuration Release
set "buildExitCode=%ERRORLEVEL%"
if not "%buildExitCode%"=="0" (
    echo.
    echo FRAME build failed. The previous build will not be started.
    pause
    exit /b %buildExitCode%
)
call "%~dp0frame.bat" gui
set "frameExitCode=%ERRORLEVEL%"
if not "%frameExitCode%"=="0" (
    echo.
    echo FRAME UI failed to start. See the error above.
    pause
)
exit /b %frameExitCode%
