#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 桌面 Helper 客户端模块（services/helper.py）

【职责边界 - P2-2 明确】
本文件是主服务（vram-console）中的 Helper **客户端**，负责：
- Helper 进程管理（启动/停止/状态探测）
- 调用 Helper HTTP API（经代理，UAC 提权）
- 自动防死机配置
- Windows GPU 进程数据获取（经 Helper 代理）

【与 vram_helper.py 的关系】
- services/vram_helper.py 是独立的 Helper **服务端**脚本（可执行）
- 本文件通过 HTTP API 调用 vram_helper.py 提供的服务
- 两者是客户端-服务端架构，不是职责重叠，不可合并
- desktop_kill() 在本文件是 API 代理，在 vram_helper.py 是实际执行

【P1-3 改造说明】
- HTTP 调用应逐步迁移到 clients/helper_client.py
- subprocess 调用应逐步迁移到 clients/process_client.py
"""
import json
import os
import time
import uuid
import subprocess
import urllib.request
from core.logger import log_event, log_error, log_info
from core.config import BASE_DIR

# === Helper 配置 ===
HELPER_PORT = 8788
HELPER_HOST = "127.0.0.1"
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# === 自动防死机配置 ===
AUTO_PROTECT_MODES = ("conservative", "standard", "aggressive")


def _config():
    """读取/初始化 config.json（含 helper_token）。"""
    d = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        log_error("exception_suppressed", error=e, context="helper.py:33")
    if not d.get("helper_token"):
        d["helper_token"] = uuid.uuid4().hex
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log_error("exception_suppressed", error=e, context="helper.py:40")
    return d


def _auto_protect_cfg():
    """读取 auto_protect 配置（带默认值：关闭 + 标准模式）。"""
    d = _config()
    ap = d.get("auto_protect") or {}
    mode = ap.get("mode", "standard")
    if mode not in AUTO_PROTECT_MODES:
        mode = "standard"
    return {"enabled": bool(ap.get("enabled", False)), "mode": mode}


def _auto_protect_save(patch):
    """保存 auto_protect 配置到 config.json。"""
    d = _config()
    ap = dict(d.get("auto_protect") or {})
    if "enabled" in patch:
        ap["enabled"] = bool(patch["enabled"])
    if "mode" in patch and patch["mode"] in AUTO_PROTECT_MODES:
        ap["mode"] = patch["mode"]
    d["auto_protect"] = ap
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log_error("auto_protect_config_save_error", error=str(e))
        return False


def _helper_health():
    """探测 Helper 是否在运行（timeout 0.5s，避免拖慢冷路径）。"""
    token = _config().get("helper_token", "")
    try:
        req = urllib.request.Request("http://{}:{}/api/health".format(HELPER_HOST, HELPER_PORT),
                                     headers={"X-API-Key": token})
        with urllib.request.urlopen(req, timeout=0.5) as r:
            return r.status == 200
    except Exception:
        return False


def _helper_req(path, data=None):
    """代理请求到 Helper（带 token）。返回 (ok, dict)。"""
    token = _config().get("helper_token", "")
    url = "http://{}:{}{}".format(HELPER_HOST, HELPER_PORT, path)
    try:
        if data is not None:
            req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"),
                                         headers={"X-API-Key": token, "Content-Type": "application/json"},
                                         method="POST")
        else:
            req = urllib.request.Request(url, headers={"X-API-Key": token})
        with urllib.request.urlopen(req, timeout=15) as r:
            return True, json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def _helper_process_count():
    """进程级探测：返回 vram_helper.py 进程数。"""
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'vram[_-]helper' } | Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=10)
        n = int((ps.stdout or "0").strip() or "0")
        return n
    except Exception:
        return 0


def _helper_kill_processes():
    """强杀所有 vram_helper 进程。"""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'vram[_-]helper' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True, text=True, timeout=10)
    except Exception as e:
        log_error("exception_suppressed", error=e, context="helper.py:122")


def helper_status() -> dict:
    return {"ok": True, "running": _helper_health(), "process_count": _helper_process_count()}


def helper_start() -> dict:
    """启用 Helper：以管理员身份启动 vram-helper.py。"""
    if _helper_health():
        return {"ok": True, "running": True, "msg": "Helper 已在运行"}
    if _helper_process_count() > 0:
        log_info("helper_start_cleanup", detail="检测到残留 vram-helper 进程但 8788 无响应，自动清理")
        _helper_kill_processes()
        for _wait in range(5):
            time.sleep(1.0)
            if _helper_process_count() == 0:
                break
        if _helper_process_count() > 0:
            return {"ok": False, "running": False,
                    "msg": "检测到 vram-helper 残留进程且自动清理失败，请手动结束进程后重试"}
    token = _config().get("helper_token", "")
    script = os.path.join(BASE_DIR, "services", "vram_helper.py")
    import sys

    is_admin = False
    try:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False

    spawn_ok = False
    spawn_method = "none"
    try:
        subprocess.Popen(
            [sys.executable, script, "--token", token],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        spawn_ok = True
        spawn_method = "direct"
        log_info("helper_start_direct", detail="直接启动 vram-helper.py（is_admin={}）".format(is_admin))
    except Exception as e:
        log_error("helper_start_direct_failed", error=e)

    if not spawn_ok:
        try:
            import ctypes
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable,
                '"{}" --token {}'.format(script, token), BASE_DIR, 1)
            if ret <= 32:
                log_error("helper_start_uac_failed", error="ShellExecuteW 返回 {}".format(ret))
            else:
                spawn_ok = True
                spawn_method = "uac"
                log_info("helper_start_uac", detail="UAC 已弹出，等待用户确认")
        except Exception as e:
            log_error("helper_start_uac_exception", error=e)

    if not spawn_ok:
        return {"ok": False, "running": False,
                "msg": "Helper 启动失败（请查看日志）。若 UAC 弹窗被拒绝，请重新点击并点「是」"}

    for _ in range(16):
        time.sleep(0.5)
        if _helper_health():
            return {"ok": True, "running": True, "msg": "Helper 已启动（8788 端口响应正常）"}

    running = _helper_health()
    if running:
        return {"ok": True, "running": True, "msg": "Helper 已启动"}
    log_error("helper_start_timeout", error="启动后 8 秒内 8788 端口无响应")
    return {"ok": False, "running": False,
            "msg": "Helper 启动超时：8 秒内 8788 端口无响应。若 UAC 弹窗仍在，请点「是」"}


def helper_stop() -> dict:
    """停用 Helper：先请求自退，再进程级兜底强杀。"""
    if _helper_health():
        _helper_req("/api/exit")
        time.sleep(1.0)
    _helper_kill_processes()
    return {"ok": True, "running": False, "msg": "Helper 已停止"}


def get_windows_gpu_processes() -> dict:
    """获取 Windows 进程级 GPU 显存占用（直接调用 PowerShell 性能计数器，参考 Helper 原理）。

    原理：使用 Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' 性能计数器
    - 多实例计数器用 (*) 通配语法
    - 实例名格式 pid_<pid>_luid_...，需提取 pid
    - 值单位是字节，需 /1MB 转 MB
    - 用 Get-Process 映射 pid 到进程名

    注意：不需要 UAC 提权（性能计数器普通用户可读），但某些系统进程可能
    无法获取进程名。与 Helper 的区别：不启动独立提权进程，直接在主服务
    中调用 PowerShell，简单轻量。

    Returns:
        dict: {"ok": bool, "processes": [{"name": str, "pid": int, "used_mb": float}],
               "count": int, "total_mb": float}
    """
    import subprocess
    ps = ("$procMap=@{}; Get-Process -ErrorAction SilentlyContinue | ForEach-Object { $procMap[$_.Id]=$_.ProcessName }; "
          "Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' -ErrorAction SilentlyContinue "
          "| Select-Object -ExpandProperty CounterSamples "
          "| Where-Object { $_.CookedValue -gt 0 } "
          "| ForEach-Object { "
          "$p=0; if ($_.InstanceName -match 'pid_(\\d+)_') { $p=[int]$Matches[1] }; "
          "[PSCustomObject]@{ Name=$(if($procMap.ContainsKey($p)){$procMap[$p]}else{'unknown'}); Pid=$p; MB=[math]::Round($_.CookedValue/1MB,1) } } "
          "| Where-Object { $_.Pid -gt 0 } "
          "| Sort-Object MB -Descending "
          "| ConvertTo-Json -Compress")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=15)
        out = p.stdout.strip()
        if not out:
            return {"ok": False, "processes": [], "count": 0, "total_mb": 0, "error": "no counter data"}
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        # 过滤掉显存占用过小的进程（<10MB），减少噪音
        processes = [{"name": p.get("Name", "unknown"), "pid": p.get("Pid", 0),
                      "used_mb": float(p.get("MB", 0))} for p in data if p.get("MB", 0) >= 10]
        total_mb = sum(p["used_mb"] for p in processes)
        return {"ok": True, "processes": processes, "count": len(processes), "total_mb": round(total_mb, 1)}
    except Exception as e:
        return {"ok": False, "processes": [], "count": 0, "total_mb": 0, "error": str(e)}


def desktop_vram_detail() -> dict:
    """桌面逐进程显存明细：优先直接调用 PowerShell，失败则经 Helper 代理。"""
    # 优先直接调用 PowerShell（不需要提权，简单轻量）
    direct = get_windows_gpu_processes()
    if direct.get("ok"):
        direct["helper"] = False
        direct["source"] = "powershell_direct"
        return direct
    # 失败则回退到 Helper 代理（需要 UAC 提权）
    if not _helper_health():
        return {"ok": False, "processes": [], "count": 0, "error": "helper not running", "helper": False}
    ok, r = _helper_req("/api/desktop_vram")
    if ok:
        r["helper"] = True
        r["source"] = "helper_proxy"
    return r


def desktop_kill(pid: int) -> dict:
    """结束桌面进程：经 Helper 代理。"""
    if not _helper_health():
        return {"ok": False, "error": "helper not running"}
    ok, r = _helper_req("/api/desktop/kill", {"pid": pid})
    return r
