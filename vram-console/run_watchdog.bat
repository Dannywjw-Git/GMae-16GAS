@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Auto-detect real python.exe (skip WindowsApps stub)
set "PYTHON="
for /f "delims=" %%i in ('where python.exe 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        set "PYTHON=%%i"
        goto :found
    )
)

if not defined PYTHON (
    echo ERROR: real python.exe not found >> logs\watchdog.log
    exit /b 1
)

:found
echo Using Python: %PYTHON% >> logs\watchdog.log
"%PYTHON%" watchdog.py
