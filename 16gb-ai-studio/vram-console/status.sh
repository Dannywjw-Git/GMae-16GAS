#!/bin/bash
# GMae 调度中心 - Linux 状态查看脚本
# 用法: ./status.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== GPU Maestro 调度中心状态 (Linux) ==="
echo ""

echo "[进程]"
PIDS=$(ps aux | grep -E "vram-console|watchdog\.py|server\.py" | grep -v grep)
if [ -n "$PIDS" ]; then
    echo "$PIDS" | awk '{printf "  PID %s: %s %s %s\n", $2, $11, $12, $13}'
else
    echo "  (no vram-console processes)"
fi
echo ""

echo "[端口 8787]"
if ss -tlnp 2>/dev/null | grep -q ":8787" || netstat -tlnp 2>/dev/null | grep -q ":8787"; then
    ss -tlnp 2>/dev/null | grep ":8787" || netstat -tlnp 2>/dev/null | grep ":8787"
else
    echo "  (not listening)"
fi
echo ""

echo "[健康检查]"
if curl -s --connect-timeout 3 http://127.0.0.1:8787/api/health > /dev/null 2>&1; then
    curl -s http://127.0.0.1:8787/api/health | python3 -m json.tool 2>/dev/null || curl -s http://127.0.0.1:8787/api/health
else
    echo "  (service unreachable)"
fi
echo ""

echo "[最近日志]"
if [ -f "logs/watchdog.log" ]; then
    tail -5 logs/watchdog.log | sed 's/^/  /'
else
    echo "  (no log file)"
fi
echo ""
