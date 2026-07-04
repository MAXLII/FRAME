@echo off
setlocal
set "FRAME_ROOT=%~dp0"
set "FRAME_PYTHON=%FRAME_ROOT%.venv\Scripts\python.exe"
if not exist "%FRAME_PYTHON%" set "FRAME_PYTHON=python"
"%FRAME_PYTHON%" "%FRAME_ROOT%main.py" %*
exit /b %ERRORLEVEL%
