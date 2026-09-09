#!/bin/bash
# GMae 调度中心 - Linux 启动脚本
# 用法: ./start.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== GPU Maestro 调度中心启动 (Linux) ==="

# 检测 python3
PYTHON=""
for cmd in python3 python; do
    if command -v $cmd &> /dev/null; then
        # 跳过 WindowsApps stub（Linux 下不太可能，但保险起见）
        if [ "$($cmd -c 'import sys; print(sys.executable)' 2>/dev/null)" != "" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: python3 not found. Please install Python 3.8+."
    exit 1
fi
echo "Using Python: $($PYTHON --version)"

# 检查端口是否已占用
if ss -tlnp 2>/dev/null | grep -q ":8787" || netstat -tlnp 2>/dev/null | grep -q ":8787"; then
    echo "Port 8787 already in use. Checking if service is alive..."
    if curl -s --connect-timeout 3 http://127.0.0.1:8787/api/health > /dev/null 2>&1; then
        echo "Service already running. Use status.sh to check."
        exit 0
    else
        echo "Port occupied but service not responding. Will try to start anyway."
    fi
fi

# 确保日志目录存在
mkdir -p logs

# 启动 watchdog（后台运行，输出重定向到日志）
echo "Starting watchdog..."
nohup $PYTHON engine/watchdog.py >> logs/watchdog.log 2>&1 &
WATCHDOG_PID=$!
echo "Watchdog PID: $WATCHDOG_PID"

# 等待服务启动
echo "Waiting for service to start..."
for i in $(seq 1 30); do
    if curl -s --connect-timeout 2 http://127.0.0.1:8787/api/health > /dev/null 2>&1; then
        echo ""
        echo "=== Service started successfully ==="
        curl -s http://127.0.0.1:8787/api/health | python3 -m json.tool 2>/dev/null || curl -s http://127.0.0.1:8787/api/health
        echo ""
        echo "Watchdog running in background (PID: $WATCHDOG_PID)"
        echo "Check status: ./status.sh"
        echo "Stop service: ./stop.sh"
        exit 0
    fi
    sleep 2
    echo -n "."
done

echo ""
echo "WARNING: Service did not start within 60s. Check logs/watchdog.log"
exit 1
