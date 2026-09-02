@echo off
chcp 65001 >nul
cd /d "D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console"

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
    echo ERROR: real python.exe not found >> logs\watchdog.log
    exit /b 1
)

:found
echo Using Python: %PYTHON% >> logs\watchdog.log
"%PYTHON%" engine\watchdog.py
