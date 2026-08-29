#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Maestro 看门狗 - 监控 server.py 进程，崩溃后自动重启
用法：pythonw watchdog.py （无窗口后台运行）
"""
import subprocess
import time
import os
import sys
import datetime
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(BASE_DIR, "server.py")
LOG_FILE = os.path.join(BASE_DIR, "logs", "watchdog.log")
RESTART_DELAY = 5  # 秒
MAX_RESTARTS_PER_HOUR = 10
PORT = int(os.environ.get("VRAM_CONSOLE_PORT", "8787"))

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "{} | {}".format(ts, msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def _port_up():
    """探测 8787 健康端点：端口在 = 服务活着（无论 admin/非 admin server）。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:{}/api/health".format(PORT), timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _start_server():
    return subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def main():
    log("=" * 50)
    log("Watchdog started (port-based health), server: {}".format(SERVER_SCRIPT))
    log("Python: {}".format(sys.executable))
    restart_times = []

    while True:
        # 检查1小时内重启次数，防止死循环
        one_hour_ago = time.time() - 3600
        restart_times = [t for t in restart_times if t > one_hour_ago]
        if len(restart_times) >= MAX_RESTARTS_PER_HOUR:
            log("WARNING: {} restarts in last hour, pausing 5min".format(MAX_RESTARTS_PER_HOUR))
            time.sleep(300)
            restart_times = []
            continue

        # 端口在 → 只监控不重复启动（server 可能已自提权为 admin，原进程退出不影响）
        if _port_up():
            log("Port :{} up, monitoring only".format(PORT))
            while _port_up():
                time.sleep(5)
            log("Port :{} went down".format(PORT))
            restart_times.append(time.time())
            time.sleep(RESTART_DELAY)
            continue

        # 端口不在 → 启动 server
        log("Starting server...")
        try:
            proc = _start_server()
            log("Server started, PID: {}".format(proc.pid))
            deadline = time.time() + 90
            while time.time() < deadline and not _port_up():
                time.sleep(2)
            if _port_up():
                log("Server up on :{}".format(PORT))
            else:
                log("Server failed to come up within 90s (may be UAC pending)")
        except Exception as e:
            log("Failed to start server: {}".format(e))

        restart_times.append(time.time())
        log("Checking again in {}s... ({} restarts in last hour)".format(RESTART_DELAY, len(restart_times)))
        time.sleep(RESTART_DELAY)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Watchdog stopped by user")
    except Exception as e:
        log("Watchdog crashed: {}".format(e))
        raise
