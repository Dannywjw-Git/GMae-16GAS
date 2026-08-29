@echo off
chcp 65001 >nul
echo === GPU Maestro 调度中心状态 ===
echo.

echo [进程]
tasklist /fi "imagename eq python.exe" /fo table 2>nul | findstr /i "python"
if errorlevel 1 echo   (无 python 进程)

echo.
echo [端口 8787]
netstat -ano | findstr ":8787.*LISTENING"
if errorlevel 1 echo   (未监听)

echo.
echo [健康检查]
curl -s --connect-timeout 3 http://127.0.0.1:8787/api/health 2>nul
if errorlevel 1 echo   (服务不可达)

echo.
echo [最近日志]
if exist "logs\watchdog.log" (
  type "logs\watchdog.log" | findstr /n "." | findstr /b ".*[0-9]*:" >nul
  for /f "tokens=*" %%a in ('powershell -Command "Get-Content 'logs\watchdog.log' -Tail 5"') do echo   %%a
)
echo.
pause
