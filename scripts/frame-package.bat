@echo off
setlocal
if /i "%~1"=="gui" (
    start "" "%~dp0Frame.Desktop.exe"
    exit /b 0
)
"%~dp0frame.exe" %*
exit /b %ERRORLEVEL%
