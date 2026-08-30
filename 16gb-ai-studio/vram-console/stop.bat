@echo off
chcp 65001 >nul
echo 停止 GPU Maestro 调度中心（看门狗 + 服务）...
echo.

echo [1/2] 精确停止 vram-console 相关进程（不误杀其他 Python 程序）...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$procs = Get-CimInstance Win32_Process -Filter \"name='python.exe' or name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*vram-console*' }; ^
   if ($procs) { $procs | ForEach-Object { Write-Host ('  停止 PID ' + $_.ProcessId + ': ' + $_.Name); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host ('  已停止 ' + $procs.Count + ' 个进程') } ^
   else { Write-Host '  未发现 vram-console 进程（可能已停止）' }"

timeout /t 2 /nobreak >nul

echo.
echo [2/2] 验证端口已释放...
netstat -ano | findstr ":8787.*LISTENING"
if errorlevel 1 (
  echo   端口 8787 已释放，服务已停止。
) else (
  echo   警告：端口仍在监听，可能有残留进程。
  echo   尝试强制释放...
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8787.*LISTENING"') do (
    echo   强制停止 PID %%a
    taskkill /f /pid %%a 2>nul
  )
)

echo.
echo 注意：开机自启已禁用（如需重新启用，运行 start.bat）。
pause
