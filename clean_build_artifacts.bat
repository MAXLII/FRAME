@echo off
setlocal

cd /d "%~dp0"

echo Cleaning build artifacts...
echo.

if exist "build" (
    echo [DIR] Removing build
    rmdir /s /q "build"
)

if exist "dist" (
    echo [DIR] Removing dist
    rmdir /s /q "dist"
)

if exist "__pycache__" (
    echo [DIR] Removing __pycache__
    rmdir /s /q "__pycache__"
)

for /d /r %%D in (__pycache__) do (
    if exist "%%D" (
        echo [DIR] Removing %%D
        rmdir /s /q "%%D"
    )
)

for /r %%F in (*.pyc *.pyo *.pyd) do (
    if exist "%%F" (
        echo [FILE] Removing %%F
        del /f /q "%%F"
    )
)

if exist "frame.spec" (
    echo [FILE] Removing frame.spec
    del /f /q "frame.spec"
)

echo.
echo Done.
pause
