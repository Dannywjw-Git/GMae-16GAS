#!/bin/bash
# GMae 显存指挥家 - 一键部署脚本 (Linux)
# One GPU, Infinite Models

set -e

cd "$(dirname "$0")"

echo "============================================================"
echo "  GMae 显存指挥家 - 一键部署脚本 (Linux)"
echo "  One GPU, Infinite Models"
echo "============================================================"
echo ""

ERRORS=0

# ============================================================
# Step 1: 环境检查
# ============================================================
echo "[1/5] 环境检查..."
echo ""

# 1.1 Python 检查
if command -v python3 &> /dev/null; then
    PYTHON=$(which python3)
    echo "  [OK] Python: $PYTHON"
    $PYTHON --version
else
    echo "  [FAIL] 未找到 python3，请安装 Python 3.8+"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
    ERRORS=$((ERRORS+1))
fi
echo ""

# 1.2 Docker 检查
if command -v docker &> /dev/null; then
    echo "  [OK] Docker:"
    docker --version
else
    echo "  [WARN] 未检测到 Docker。GMae 需要 Docker 管理 AI 容器"
    echo "  安装: https://docs.docker.com/engine/install/"
fi
echo ""

# 1.3 NVIDIA GPU 检查
if command -v nvidia-smi &> /dev/null; then
    echo "  [OK] NVIDIA GPU:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
    echo "  [FAIL] 未检测到 NVIDIA GPU 或 nvidia-smi 不可用"
    ERRORS=$((ERRORS+1))
fi
echo ""

if [ $ERRORS -gt 0 ]; then
    echo "环境检查失败，共 $ERRORS 个错误。请修复后重试。"
    exit 1
fi

# ============================================================
# Step 2: 配置初始化
# ============================================================
echo "[2/5] 配置初始化..."
echo ""

# 2.1 生成 API Token
if [ ! -f .api_token ]; then
    echo "  生成 API Token..."
    TOKEN=$($PYTHON -c "import secrets; print(secrets.token_hex(32))")
    echo "$TOKEN" > .api_token
    chmod 600 .api_token
    echo "  [OK] API Token 已生成: .api_token"
else
    echo "  [OK] API Token 已存在: .api_token"
fi

# 2.2 检查 registry.json
if [ ! -f resources/registry.json ]; then
    echo "  [INFO] registry.json 将在首次启动时自动创建"
else
    echo "  [OK] registry.json 已存在"
fi
echo ""

# ============================================================
# Step 3: 安装 CLI 工具（可选）
# ============================================================
echo "[3/5] CLI 工具安装（可选）..."
echo ""
read -p "  是否安装 GMae CLI 工具？(y/N): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "  安装中..."
    $PYTHON -m pip install -e . --quiet 2>/dev/null || {
        echo "  [WARN] CLI 安装失败（不影响核心功能）"
    }
    echo "  [OK] CLI 工具已安装，使用 \`gmae\` 命令"
else
    echo "  跳过 CLI 安装"
fi
echo ""

# ============================================================
# Step 4: 启动服务
# ============================================================
echo "[4/5] 启动 GMae 服务..."
echo ""

if curl -s --connect-timeout 2 http://127.0.0.1:8787/api/health > /dev/null 2>&1; then
    echo "  [OK] GMae 服务已在运行中"
else
    echo "  启动 watchdog..."
    nohup $PYTHON engine/watchdog.py > /tmp/gmae_watchdog.log 2>&1 &
    echo "  等待服务启动..."
    sleep 8
fi
echo ""

# ============================================================
# Step 5: 验证
# ============================================================
echo "[5/5] 服务验证..."
echo ""

HEALTH=0
for i in {1..5}; do
    if curl -s --connect-timeout 3 http://127.0.0.1:8787/api/health 2>/dev/null | grep -q "ok"; then
        HEALTH=1
        break
    fi
    sleep 2
done

if [ $HEALTH -eq 1 ]; then
    echo "  [OK] 服务健康检查通过"
    echo ""
    echo "============================================================"
    echo "  部署完成！"
    echo "============================================================"
    echo ""
    echo "  访问地址: http://127.0.0.1:8787"
    echo "  API 文档: http://127.0.0.1:8787/api/docs"
    echo ""
    echo "  常用命令:"
    echo "    启动服务: ./start.sh"
    echo "    停止服务: ./stop.sh"
    echo "    查看状态: ./status.sh"
    echo ""
else
    echo "  [WARN] 健康检查未通过，服务可能仍在启动中"
    echo "  请稍后手动运行: ./status.sh 查看状态"
    echo "  日志: /tmp/gmae_watchdog.log"
fi
