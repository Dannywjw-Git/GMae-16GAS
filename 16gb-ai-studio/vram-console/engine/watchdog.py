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
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # vram-console 根目录（v2.0 模块化后脚本位于 engine/）
SERVER_SCRIPT = os.path.join(BASE_DIR, "server.py")
LOG_FILE = os.path.join(BASE_DIR, "logs", "watchdog.log")
RESTART_DELAY = 5  # 秒
MAX_RESTARTS_PER_HOUR = 10
PORT = int(os.environ.get("VRAM_CONSOLE_PORT", "8787"))

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

def log(msg: str) -> None:
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

def _port_open() -> bool:
    """探测1：端口连通性（TCP 连接，检测端口是否在监听）"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("127.0.0.1", PORT))
        s.close()
        return result == 0
    except Exception:
        return False


def _health_ok() -> bool:
    """探测2：/api/health 内容校验（检测服务内部是否正常，防半死状态）。

    注意：health 返回的 ok 字段反映的是下游服务（ollama/comfyui 等）连通状态，
    不代表调度中心 server 本身是否存活。server 健康时若下游容器未运行，ok 也会是
    false。若看门狗用 ok==True 作为存活标准，会在下游容器未启动时误判 server
    半死而疯狂重启，堆积大量重复实例（2026-08-31 事故根因）。
    因此这里只校验：HTTP 200 且返回结构包含 services（说明 health_check 正常执行）。
    """
    try:
        with urllib.request.urlopen("http://127.0.0.1:{}/api/health".format(PORT), timeout=15) as r:  # timeout=15：health 会对未运行容器端口做 HTTP 探测等待数秒，3s 会误判半死
            if r.status != 200:
                return False
            data = json.loads(r.read().decode("utf-8"))
            return "services" in data
    except Exception:
        return False


def _server_alive() -> bool:
    """双探测：端口通 + health 正常 = 服务活着；端口通但 health 异常 = 半死，需重启"""
    port_up = _port_open()
    if not port_up:
        return False
    health_ok = _health_ok()
    if not health_ok:
        log("WARNING: port open but /api/health failed (half-dead), will restart")
    return health_ok


def _start_server() -> None:
    return subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def main() -> None:
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
        if _server_alive():
            log("Port :{} up, monitoring only".format(PORT))
            while _server_alive():
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
            while time.time() < deadline and not _server_alive():
                time.sleep(2)
            if _server_alive():
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
