@echo off
setlocal
cd /d "%~dp0"

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "BOOTSTRAP_PY="
set "DIST_APP_DIR=%~dp0dist\frame"
set "FRAME_INTERACTIVE=1"

if /I "%~1"=="--no-interactive" set "FRAME_INTERACTIVE=0"
if defined FRAME_BUILD_SILENT set "FRAME_INTERACTIVE=0"

where py >nul 2>nul
if not errorlevel 1 set "BOOTSTRAP_PY=py -3"

if not defined BOOTSTRAP_PY (
    where python >nul 2>nul
    if not errorlevel 1 set "BOOTSTRAP_PY=python"
)

if not exist "%VENV_PYTHON%" (
    echo [INFO] Creating virtual environment...
    if not defined BOOTSTRAP_PY (
        echo [ERROR] Python launcher not found. Please install Python 3 or add py/python to PATH.
        if "%FRAME_INTERACTIVE%"=="1" pause
        exit /b 1
    )
    call %BOOTSTRAP_PY% -m venv ".venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv
        if "%FRAME_INTERACTIVE%"=="1" pause
        exit /b 1
    )
)

echo [INFO] Installing project requirements...
call "%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.txt
    if "%FRAME_INTERACTIVE%"=="1" pause
    exit /b 1
)

echo [INFO] Installing PyInstaller...
call "%VENV_PYTHON%" -m pip install --disable-pip-version-check --index-url https://pypi.org/simple --no-cache-dir pyinstaller==6.19.0
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller
    if "%FRAME_INTERACTIVE%"=="1" pause
    exit /b 1
)

if exist "%DIST_APP_DIR%" (
    echo [INFO] Cleaning existing application bundle...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$target = [System.IO.Path]::GetFullPath('%DIST_APP_DIR%'); if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }"
    if exist "%DIST_APP_DIR%" (
        echo [ERROR] Failed to clean existing bundle: "%DIST_APP_DIR%"
        if "%FRAME_INTERACTIVE%"=="1" pause
        exit /b 1
    )
)

echo [INFO] Building frame.exe...
call "%VENV_PYTHON%" -m PyInstaller --noconfirm --clean --windowed --name frame --distpath "dist" --workpath "build" "main.py"
if errorlevel 1 (
    echo [ERROR] Build failed
    if "%FRAME_INTERACTIVE%"=="1" pause
    exit /b 1
)

if exist "build" (
    rmdir /s /q "build"
)

echo.
echo [OK] Build complete: %~dp0dist\frame\frame.exe
if "%FRAME_INTERACTIVE%"=="1" (
    start "" "%DIST_APP_DIR%"
    pause
)
exit /b 0
