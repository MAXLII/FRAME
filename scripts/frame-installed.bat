@echo off
setlocal
call "%~dp0..\frame.bat" %*
exit /b %ERRORLEVEL%
