@echo off
chcp 65001 >nul
echo 停止 GPU Maestro 调度中心（看门狗 + 服务）...
echo.

echo [1/2] 停止 python 进程（watchdog.py + server.py）...
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul

timeout /t 2 /nobreak >nul

echo.
echo [2/2] 验证端口已释放...
netstat -ano | findstr ":8787.*LISTENING"
if errorlevel 1 (
  echo   端口 8787 已释放，服务已停止。
) else (
  echo   警告：端口仍在监听，可能有残留进程。
)

echo.
echo 注意：开机自启已禁用（如需重新启用，运行 start.bat 或恢复 Startup 中的 VRAM_Console.vbs）。
pause
