@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo [2/3] Installing or updating dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. Repairing pip and retrying...
    if exist ".venv\Lib\site-packages\pip" (
        rmdir /s /q ".venv\Lib\site-packages\pip"
    )
    for /d %%D in (".venv\Lib\site-packages\pip-*.dist-info") do (
        rmdir /s /q "%%~D"
    )
    ".venv\Scripts\python.exe" -m ensurepip --upgrade --default-pip
    if errorlevel 1 (
        echo Failed to repair pip.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Failed to install dependencies.
        pause
        exit /b 1
    )
)

echo [3/3] Starting FRAME...
start "" ".venv\Scripts\python.exe" "main.py"

endlocal
