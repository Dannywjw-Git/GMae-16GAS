@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Starting GPU Maestro watchdog...

rem Auto-detect real python.exe (skip WindowsApps stub)
set "PYTHON="
for /f "delims=" %%i in ('where python.exe 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        set "PYTHON=%%i"
        goto :found
    )
)

rem Fallback: try common Doubao sandbox paths
if not defined PYTHON (
    for /d %%d in ("C:\Users\Danny\AppData\Local\Doubao\User Data\sandbox_runtime\bases\*") do (
        if exist "%%d\python\python.exe" (
            set "PYTHON=%%d\python\python.exe"
            goto :found
        )
    )
)

if not defined PYTHON (
    echo ERROR: real python.exe not found. WindowsApps stub is not usable.
    echo Please install Python from python.org or add real python to PATH.
    pause
    exit /b 1
)

:found
echo Using Python: %PYTHON%

rem Start watchdog in minimized window
start "" /min "%PYTHON%" watchdog.py

rem Wait for service to start
timeout /t 5 /nobreak >nul

echo.
echo Service status:
curl -s --connect-timeout 3 http://127.0.0.1:8787/api/health 2>nul
echo.
echo Done. Watchdog running in minimized window.
echo Check status: status.bat
echo Stop service: stop.bat
pause
