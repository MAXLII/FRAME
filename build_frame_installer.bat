@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=FRAME"
set "PUBLISHER=LWX"
set "ISS_FILE=%~dp0installer\frame_installer.iss"
set "DIST_APP_DIR=%~dp0dist\frame"
set "BRAND_FILE=%DIST_APP_DIR%\app_brand.txt"
set "ISCC_EXE="
set "BASE_APP_VERSION="
set "BASE_APP_VERSION_RAW="

for /f "tokens=2 delims==" %%I in ('findstr /B /C:"BASE_APP_VERSION" "serial_debug_assistant\constants.py"') do set "BASE_APP_VERSION_RAW=%%I"
set "BASE_APP_VERSION=%BASE_APP_VERSION_RAW: =%"
set "BASE_APP_VERSION=%BASE_APP_VERSION:"=%"
if not defined BASE_APP_VERSION (
    echo [ERROR] Failed to read BASE_APP_VERSION from serial_debug_assistant\constants.py
    exit /b 1
)

set "APP_VERSION=%BASE_APP_VERSION%"

echo [INFO] Building application bundle...
set "FRAME_BUILD_SILENT=1"
call "%~dp0build_frame_exe.bat" --no-interactive
if errorlevel 1 (
    echo [ERROR] Application bundle build failed.
    exit /b 1
)

if not exist "%DIST_APP_DIR%\frame.exe" (
    echo [ERROR] Expected executable was not found: "%DIST_APP_DIR%\frame.exe"
    exit /b 1
)

> "%BRAND_FILE%" (
    echo app_name=FRAME
    echo app_version=%APP_VERSION%
    echo hidden_tabs=home
)
if errorlevel 1 (
    echo [ERROR] Failed to create brand marker file: "%BRAND_FILE%"
    exit /b 1
)

for %%I in (
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    "%LOCALAPPDATA%\Programs\Inno Setup 5\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
    "%ProgramFiles%\Inno Setup 5\ISCC.exe"
) do (
    if exist %%~I (
        set "ISCC_EXE=%%~I"
        goto :found_iscc
    )
)

where ISCC >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where ISCC') do (
        set "ISCC_EXE=%%~I"
        goto :found_iscc
    )
)

echo [ERROR] Inno Setup compiler was not found.
echo [INFO] This script needs Inno Setup 6 to build the installer package.
echo [INFO] Please install Inno Setup 6 first, then rerun this script.
echo [INFO] Download: https://jrsoftware.org/isdl.php
echo [INFO] After installation, make sure ISCC.exe is available in one of the default install locations or in PATH.
echo [INFO] The application bundle is already available at: "%DIST_APP_DIR%"
exit /b 1

:found_iscc
if not exist "%ISS_FILE%" (
    echo [ERROR] Installer script was not found: "%ISS_FILE%"
    exit /b 1
)

if not exist "%~dp0dist\installer" (
    mkdir "%~dp0dist\installer"
)

echo [INFO] Using Inno Setup compiler: "%ISCC_EXE%"
echo [INFO] Building installer package...
call "%ISCC_EXE%" /DMyAppVersion=%APP_VERSION% /DMyAppPublisher=%PUBLISHER% "%ISS_FILE%"
if errorlevel 1 (
    echo [ERROR] Installer build failed.
    exit /b 1
)

echo.
echo [OK] Installer build complete: %~dp0dist\installer\FRAME-Setup-%APP_VERSION%.exe
start "" "%~dp0dist\installer"
exit /b 0
