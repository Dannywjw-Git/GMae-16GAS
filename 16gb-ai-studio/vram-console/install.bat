@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   GMae 显存指挥家 - 一键部署脚本 (Windows)
echo   One GPU, Infinite Models
echo ============================================================
echo.

set "ERRORS=0"

rem ============================================================
rem Step 1: 环境检查
rem ============================================================
echo [1/5] 环境检查...
echo.

rem 1.1 Python 检查
set "PYTHON="
for /f "delims=" %%i in ('where python.exe 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        set "PYTHON=%%i"
        goto :python_found
    )
)
if not defined PYTHON (
    for /d %%d in ("%LOCALAPPDATA%\Doubao\User Data\sandbox_runtime\bases\*") do (
        if exist "%%d\python\python.exe" (
            set "PYTHON=%%d\python\python.exe"
            goto :python_found
        )
    )
)
:python_found
if defined PYTHON (
    echo   [OK] Python: %PYTHON%
    "%PYTHON%" --version 2>nul
) else (
    echo   [FAIL] 未找到可用的 Python.exe（WindowsApps stub 不可用）
    echo   请从 https://www.python.org/downloads/ 安装 Python 3.8+
    set /a ERRORS+=1
)
echo.

rem 1.2 Docker 检查
docker --version >nul 2>&1
if %errorlevel%==0 (
    echo   [OK] Docker: 
    docker --version
) else (
    echo   [WARN] 未检测到 Docker。GMae 需要 Docker 管理 AI 容器（ComfyUI/Ollama等）
    echo   请安装 Docker Desktop: https://www.docker.com/products/docker-desktop/
)
echo.

rem 1.3 NVIDIA GPU 检查
nvidia-smi >nul 2>&1
if %errorlevel%==0 (
    echo   [OK] NVIDIA GPU:
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
) else (
    echo   [FAIL] 未检测到 NVIDIA GPU 或 nvidia-smi 不可用
    echo   GMae 需要 NVIDIA GPU 才能运行
    set /a ERRORS+=1
)
echo.

if %ERRORS% gtr 0 (
    echo 环境检查失败，共 %ERRORS% 个错误。请修复后重试。
    pause
    exit /b 1
)

rem ============================================================
rem Step 2: 配置初始化
rem ============================================================
echo [2/5] 配置初始化...
echo.

rem 2.1 生成 API Token
if not exist .api_token (
    echo   生成 API Token...
    for /f "delims=" %%t in ('"%PYTHON%" -c "import secrets; print(secrets.token_hex(32))"') do set "TOKEN=%%t"
    echo %TOKEN% > .api_token
    echo   [OK] API Token 已生成: .api_token
) else (
    echo   [OK] API Token 已存在: .api_token
)

rem 2.2 检查 registry.json
if not exist resources\registry.json (
    echo   [WARN] resources\registry.json 不存在，将在首次启动时自动创建
) else (
    echo   [OK] registry.json 已存在
)

rem 2.3 检查 scene_state.json
if not exist resources\scene_state.json (
    echo   [INFO] scene_state.json 将在首次场景切换后创建
)
echo.

rem ============================================================
rem Step 3: 安装 CLI 工具（可选）
rem ============================================================
echo [3/5] CLI 工具安装（可选）...
echo.
choice /c YN /n /m "  是否安装 GMae CLI 工具？(Y/N): "
if %errorlevel%==1 (
    echo   安装中...
    "%PYTHON%" -m pip install -e . --quiet 2>nul
    if %errorlevel%==0 (
        echo   [OK] CLI 工具已安装，使用 `gmae` 命令
    ) else (
        echo   [WARN] CLI 安装失败（不影响核心功能），可手动运行: pip install -e .
    )
) else (
    echo   跳过 CLI 安装
)
echo.

rem ============================================================
rem Step 4: 启动服务
rem ============================================================
echo [4/5] 启动 GMae 服务...
echo.

rem 检查是否已在运行
curl -s --connect-timeout 2 http://127.0.0.1:8787/api/health >nul 2>&1
if %errorlevel%==0 (
    echo   [OK] GMae 服务已在运行中
) else (
    echo   启动 watchdog...
    start "" /min "%PYTHON%" engine\watchdog.py
    echo   等待服务启动...
    timeout /t 8 /nobreak >nul
)
echo.

rem ============================================================
rem Step 5: 验证
rem ============================================================
echo [5/5] 服务验证...
echo.

set "HEALTH=0"
for /l %%i in (1,1,5) do (
    for /f "delims=" %%h in ('curl -s --connect-timeout 3 http://127.0.0.1:8787/api/health 2^>nul') do (
        echo %%h | findstr "ok" >nul
        if !errorlevel!==0 (
            set "HEALTH=1"
            goto :health_ok
        )
    )
    timeout /t 2 /nobreak >nul
)
:health_ok

if %HEALTH%==1 (
    echo   [OK] 服务健康检查通过
    echo.
    echo ============================================================
    echo   部署完成！
    echo ============================================================
    echo.
    echo   访问地址: http://127.0.0.1:8787
    echo   API 文档: http://127.0.0.1:8787/api/docs
    echo.
    echo   常用命令:
    echo     启动服务: start.bat
    echo     停止服务: stop.bat
    echo     查看状态: status.bat
    echo.
) else (
    echo   [WARN] 健康检查未通过，服务可能仍在启动中
    echo   请稍后手动运行: status.bat 查看状态
    echo   或查看日志: engine\watchdog.py 窗口
)

echo.
pause
