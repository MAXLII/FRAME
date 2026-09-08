@echo off
powershell.exe -NoProfile -File "%~dp0frame.ps1" %*
exit /b %ERRORLEVEL%
