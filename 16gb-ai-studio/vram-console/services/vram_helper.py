#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vram-helper.py — 最小提权 Helper（方案A，2026-08-28）
能力仅两项：读 Windows 性能计数器（逐进程 GPU 显存明细）+ taskkill 结束桌面进程。
只在用户需要查看/管理 Windows 进程显存时经 UAC 启动，默认不运行、不参与容器管理。
监听 127.0.0.1:8788（仅本机），独立 token 认证（X-API-Key）。
用法：python vram-helper.py --token <token>   （通常由调度中心 ShellExecute runas 启动）
"""
import json
import os
import subprocess
import sys
import threading
import time
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # vram-console 根目录
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_FILE = os.path.join(BASE_DIR, "logs", "helper.log")
PORT = 8788
HOST = "127.0.0.1"


def _read_idle_timeout() -> int:
    """空闲超时（秒）：无任何请求超过该时长 → 自动退出（安全增强，提权进程用完即走）。
    优先级：命令行 --idle-timeout > config.json helper_idle_timeout > 默认 300s。"""
    try:
        i = sys.argv.index("--idle-timeout")
        if len(sys.argv) > i + 1:
            return int(sys.argv[i + 1])
    except ValueError:
        pass
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("helper_idle_timeout", 300))
    except Exception:
        return 300


IDLE_TIMEOUT = _read_idle_timeout()
_last_activity = time.time()


def _touch() -> None:
    global _last_activity
    _last_activity = time.time()


def _idle_monitor() -> None:
    """后台监控：空闲超时自动退出（记录日志）。"""
    while True:
        time.sleep(10)
        idle = time.time() - _last_activity
        if idle > IDLE_TIMEOUT:
            _log("idle {:.0f}s > timeout {}s -> auto-exit (安全增强，提权进程用完即走)".format(idle, IDLE_TIMEOUT))
            try:
                os._exit(0)
            except Exception:
                pass
            return


def _log(msg: str) -> None:
    """helper 生命周期日志（诊断意外退出用，如"3 分钟自动关闭"）。"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "{} | pid={} | {}".format(ts, os.getpid(), msg)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _read_token() -> str:
    # 优先级：命令行 --token > config.json
    try:
        i = sys.argv.index("--token")
        if len(sys.argv) > i + 1:
            return sys.argv[i + 1]
    except ValueError:
        pass
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("helper_token", "")
    except Exception:
        return ""


TOKEN = _read_token()


def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def desktop_vram() -> dict:
    """读性能计数器 GPU Process Memory\\Dedicated Usage → 逐进程 GPU 显存（需管理员）。
    - 多实例计数器必须用 (*) 通配语法
    - 实例名格式 pid_<pid>_luid_...（多 GPU 引擎），需提取 pid 并映射进程名
    - 值单位是字节，需 /1MB 转 MB
    """
    ps = ("$procMap=@{}; Get-Process -ErrorAction SilentlyContinue | ForEach-Object { $procMap[$_.Id]=$_.ProcessName }; "
          "Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' -ErrorAction SilentlyContinue "
          "| Select-Object -ExpandProperty CounterSamples "
          "| Where-Object { $_.CookedValue -gt 0 } "
          "| ForEach-Object { "
          "$p=0; if ($_.InstanceName -match 'pid_(\\d+)_') { $p=[int]$Matches[1] }; "
          "[PSCustomObject]@{ Name=$(if($procMap.ContainsKey($p)){$procMap[$p]}else{''}); Pid=$p; MB=[math]::Round($_.CookedValue/1MB,1) } } "
          "| Where-Object { $_.Pid -gt 0 } "
          "| Sort-Object MB -Descending "
          "| ConvertTo-Json -Compress")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=20)
        out = p.stdout.strip()
        if not out:
            return {"ok": False, "processes": [], "count": 0,
                    "error": "no counter data", "admin": _is_admin()}
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return {"ok": True, "processes": data, "count": len(data), "admin": _is_admin()}
    except Exception as e:
        return {"ok": False, "processes": [], "count": 0, "error": str(e), "admin": _is_admin()}


PROTECT = {"explorer", "dwm", "csrss", "winlogon", "services", "lsass", "wininit", "taskhostw"}


def desktop_kill(pid: int) -> dict:
    """结束桌面进程：taskkill /F，保护系统关键进程 + 低 PID。"""
    try:
        pid = int(pid)
    except Exception:
        return {"ok": False, "error": "invalid pid"}
    if pid < 1000:
        return {"ok": False, "error": "refuse: system-critical pid (<1000) protected"}
    name = ""
    try:
        pr = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process -Id {} -ErrorAction SilentlyContinue).ProcessName".format(pid)],
            capture_output=True, text=True, timeout=8)
        name = (pr.stdout or "").strip()
    except Exception:
        pass
    if name.lower() in PROTECT:
        return {"ok": False, "error": "refuse: protected system process: " + name}
    try:
        p = subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, text=True, timeout=10)
        return {"ok": p.returncode == 0, "pid": pid,
                "output": (p.stdout or p.stderr).strip()[-200:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class H(BaseHTTPRequestHandler):
    def _check(self):
        return self.headers.get("X-API-Key", "") == TOKEN

    def _json(self, d, code=200):
        b = json.dumps(d, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_GET(self):
        _touch()
        if not self._check():
            return self._json({"ok": False, "error": "auth failed"}, 401)
        if self.path == "/api/health":
            return self._json({"ok": True, "admin": _is_admin()})
        if self.path == "/api/desktop_vram":
            return self._json(desktop_vram())
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        _touch()
        if not self._check():
            return self._json({"ok": False, "error": "auth failed"}, 401)
        ln = int(self.headers.get("Content-Length", 0) or 0)
        data = {}
        if ln:
            try:
                data = json.loads(self.rfile.read(ln).decode("utf-8"))
            except Exception:
                data = {}
        if self.path == "/api/desktop/kill":
            return self._json(desktop_kill(data.get("pid", "")))
        if self.path == "/api/exit":
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
            return self._json({"ok": True, "msg": "exiting"})
        return self._json({"ok": False, "error": "not found"}, 404)


def main() -> None:
    _log("vram-helper starting (admin={}, idle_timeout={}s)".format(_is_admin(), IDLE_TIMEOUT))
    threading.Thread(target=_idle_monitor, daemon=True).start()
    try:
        srv = ThreadingHTTPServer((HOST, PORT), H)
    except Exception as e:
        _log("bind failed: {} (端口 8788 可能被占用)".format(e))
        print("vram-helper bind failed: {}".format(e), flush=True)
        return
    _log("up on {}:{} admin={} token_set={}".format(HOST, PORT, _is_admin(), bool(TOKEN)))
    print("vram-helper up on {}:{} admin={}".format(HOST, PORT, _is_admin()), flush=True)
    try:
        srv.serve_forever()
    except Exception as e:
        _log("serve crashed: {}".format(e))
    finally:
        _log("exit")


if __name__ == "__main__":
    main()
