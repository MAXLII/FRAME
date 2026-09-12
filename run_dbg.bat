@echo off
setlocal
set "FRAME_COMM_LOG_DIR=%~dp0logs\communication"
echo Communication logs: %FRAME_COMM_LOG_DIR%
call "%~dp0frame.bat" gui
set "frameExitCode=%ERRORLEVEL%"
if not "%frameExitCode%"=="0" (
    echo.
    echo FRAME UI failed to start. See the error above.
    pause
)
exit /b %frameExitCode%
