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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(BASE_DIR, "server.py")
LOG_FILE = os.path.join(BASE_DIR, "logs", "watchdog.log")
RESTART_DELAY = 5  # 秒
MAX_RESTARTS_PER_HOUR = 10

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

def main():
    log("=" * 50)
    log("Watchdog started, server: {}".format(SERVER_SCRIPT))
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

        log("Starting server...")
        try:
            # 用 Popen 启动，不捕获输出（server.py 自己写日志文件）
            proc = subprocess.Popen(
                [sys.executable, SERVER_SCRIPT],
                cwd=BASE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            log("Server started, PID: {}".format(proc.pid))

            # 等待进程退出
            while proc.poll() is None:
                time.sleep(2)

            exit_code = proc.returncode
            log("Server exited with code: {}".format(exit_code))
        except Exception as e:
            log("Failed to start server: {}".format(e))

        restart_times.append(time.time())
        log("Restarting in {}s... ({} restarts in last hour)".format(RESTART_DELAY, len(restart_times)))
        time.sleep(RESTART_DELAY)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Watchdog stopped by user")
    except Exception as e:
        log("Watchdog crashed: {}".format(e))
        raise
