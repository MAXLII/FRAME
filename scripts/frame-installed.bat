@echo off
setlocal
"%~dp0frame-cli.exe" %*
exit /b %ERRORLEVEL%
