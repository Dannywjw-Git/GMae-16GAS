#!/bin/bash
# GMae 调度中心 - Linux 停止脚本
# 用法: ./stop.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== GPU Maestro 调度中心停止 (Linux) ==="

# 精确停止 vram-console 相关进程（不误杀其他 Python 程序）
echo "[1/2] Stopping vram-console processes..."
PIDS=$(ps aux | grep -E "vram-console|watchdog\.py|server\.py" | grep -v grep | awk '{print $2}')
if [ -n "$PIDS" ]; then
    echo "$PIDS" | while read pid; do
        echo "  Stopping PID $pid"
        kill "$pid" 2>/dev/null || true
    done
    # 等待进程退出
    sleep 3
    # 强制停止仍在运行的进程
    PIDS_REMAIN=$(ps aux | grep -E "vram-console|watchdog\.py|server\.py" | grep -v grep | awk '{print $2}')
    if [ -n "$PIDS_REMAIN" ]; then
        echo "  Force killing remaining processes..."
        echo "$PIDS_REMAIN" | while read pid; do
            kill -9 "$pid" 2>/dev/null || true
        done
    fi
    echo "  Stopped."
else
    echo "  No vram-console processes found (may already be stopped)."
fi

# 验证端口已释放
echo ""
echo "[2/2] Verifying port 8787 released..."
sleep 1
if ss -tlnp 2>/dev/null | grep -q ":8787" || netstat -tlnp 2>/dev/null | grep -q ":8787"; then
    echo "  WARNING: Port 8787 still listening. There may be residual processes."
    # 尝试强制释放
    PID=$(ss -tlnp 2>/dev/null | grep ":8787" | grep -oP 'pid=\K[0-9]+' | head -1)
    if [ -n "$PID" ]; then
        echo "  Force killing PID $PID..."
        kill -9 "$PID" 2>/dev/null || true
    fi
else
    echo "  Port 8787 released. Service stopped."
fi

echo ""
echo "Done."
