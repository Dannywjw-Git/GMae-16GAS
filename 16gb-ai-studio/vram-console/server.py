#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Maestro-显存指挥家 调度中心 - 后端 (Python 标准库, 零依赖)
GET  /              前端页面
GET  /api/status    显存/模型/容器/场景 实时状态
GET  /api/health    健康检查（各服务连通性）
POST /api/scene     切换场景 {scene: dialogue|comfy|h3|fooocus|music|game}
POST /api/free      释放 ComfyUI 显存（/free 官方端点，卸载模型+缓存）
POST /api/guard     门卫 {evict: true|false}：evict=驱逐低优先级占用；否则只读检查
POST /api/service   启停服务 {name: comfyui|fooocus, action: start|stop}
POST /api/model     模型加载/停止 {name, action: load|stop}
启动: python server.py   (默认端口 8787, 带结构化日志)
"""
import json
import os
import re
import shutil
import subprocess
import time
import datetime
import logging
import threading
import socket
import base64
import hashlib
import struct
import uuid
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from logging.handlers import TimedRotatingFileHandler
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# === 结构化日志配置 ===
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "vram-console.log")

logger = logging.getLogger("gmae")
logger.setLevel(logging.INFO)
# 文件日志：按天轮转，保留 30 天
file_handler = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1, backupCount=30, encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
logger.addHandler(file_handler)
# 控制台日志
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
logger.addHandler(console_handler)

def log_event(event_type, **kwargs):
    """记录结构化事件日志，JSON 格式"""
    entry = {"ts": datetime.datetime.now().isoformat(), "event": event_type}
    entry.update(kwargs)
    logger.info(json.dumps(entry, ensure_ascii=False))

def log_error(event_type, error, **kwargs):
    """记录错误日志"""
    entry = {"ts": datetime.datetime.now().isoformat(), "event": event_type, "error": str(error)}
    entry.update(kwargs)
    logger.error(json.dumps(entry, ensure_ascii=False))


# === 桌面 toast 通知（蓝图 Step 0，三路通知：UI banner + 日志 + 桌面 toast）===
_toast_enabled = True
_toast_cooldown = {}
_TOAST_PS_B64 = "CgBbAFcAaQBuAGQAbwB3AHMALgBVAEkALgBOAG8AdABpAGYAaQBjAGEAdABpAG8AbgBzAC4AVABvAGEAcwB0AE4AbwB0AGkAZgBpAGMAYQB0AGkAbwBuAE0AYQBuAGEAZwBlAHIALAAgAFcAaQBuAGQAbwB3AHMALgBVAEkALgBOAG8AdABpAGYAaQBjAGEAdABpAG8AbgBzACwAIABDAG8AbgB0AGUAbgB0AFQAeQBwAGUAIAA9ACAAVwBpAG4AZABvAHcAcwBSAHUAbgB0AGkAbQBlAF0AIAB8ACAATwB1AHQALQBOAHUAbABsAAoAWwBXAGkAbgBkAG8AdwBzAC4ARABhAHQAYQAuAFgAbQBsAC4ARABvAG0ALgBYAG0AbABEAG8AYwB1AG0AZQBuAHQALAAgAFcAaQBuAGQAbwB3AHMALgBEAGEAdABhAC4AWABtAGwALgBEAG8AbQAuAFgAbQBsAEQAbwBjAHUAbQBlAG4AdAAsACAAQwBvAG4AdABlAG4AdABUAHkAcABlACAAPQAgAFcAaQBuAGQAbwB3AHMAUgB1AG4AdABpAG0AZQBdACAAfAAgAE8AdQB0AC0ATgB1AGwAbAAKACQAdABpAHQAbABlACAAPQAgACQAYQByAGcAcwBbADAAXQAKACQAbQBzAGcAIAA9ACAAJABhAHIAZwBzAFsAMQBdAAoAJAB0AGUAbQBwAGwAYQB0AGUAIAA9ACAAIgA8AHQAbwBhAHMAdAAgAGQAdQByAGEAdABpAG8AbgA9ACcAcwBoAG8AcgB0ACcAPgA8AHYAaQBzAHUAYQBsAD4APABiAGkAbgBkAGkAbgBnACAAdABlAG0AcABsAGEAdABlAD0AJwBUAG8AYQBzAHQARwBlAG4AZQByAGkAYwAnAD4APAB0AGUAeAB0AD4AJAB0AGkAdABsAGUAPAAvAHQAZQB4AHQAPgA8AHQAZQB4AHQAPgAkAG0AcwBnADwALwB0AGUAeAB0AD4APAAvAGIAaQBuAGQAaQBuAGcAPgA8AC8AdgBpAHMAdQBhAGwAPgA8AC8AdABvAGEAcwB0AD4AIgAKACQAeABtAGwAIAA9ACAATgBlAHcALQBPAGIAagBlAGMAdAAgAFcAaQBuAGQAbwB3AHMALgBEAGEAdABhAC4AWABtAGwALgBEAG8AbQAuAFgAbQBsAEQAbwBjAHUAbQBlAG4AdAAKACQAeABtAGwALgBMAG8AYQBkAFgAbQBsACgAJAB0AGUAbQBwAGwAYQB0AGUAKQAKACQAdABvAGEAcwB0ACAAPQAgAE4AZQB3AC0ATwBiAGoAZQBjAHQAIABXAGkAbgBkAG8AdwBzAC4AVQBJAC4ATgBvAHQAaQBmAGkAYwBhAHQAaQBvAG4AcwAuAFQAbwBhAHMAdABOAG8AdABpAGYAaQBjAGEAdABpAG8AbgAgACQAeABtAGwACgBbAFcAaQBuAGQAbwB3AHMALgBVAEkALgBOAG8AdABpAGYAaQBjAGEAdABpAG8AbgBzAC4AVABvAGEAcwB0AE4AbwB0AGkAZgBpAGMAYQB0AGkAbwBuAE0AYQBuAGEAZwBlAHIAXQA6ADoAQwByAGUAYQB0AGUAVABvAGEAcwB0AE4AbwB0AGkAZgBpAGUAcgAoACIARwBNAGEAZQAiACkALgBTAGgAbwB3ACgAJAB0AG8AYQBzAHQAKQAKAA=="


def toast_notify(title, message, event_type="general", cooldown_s=30):
    """发送 Windows 桌面 toast 通知（零依赖，PowerShell Windows.UI.Notifications）。
    三路通知：UI banner + 日志 + 桌面 toast。同类型事件 cooldown_s 秒内只弹一次。"""
    if not _toast_enabled:
        return False
    now = time.time()
    last = _toast_cooldown.get(event_type, 0)
    if now - last < cooldown_s:
        return False
    _toast_cooldown[event_type] = now
    try:
        import base64 as _b64
        ps = _b64.b64decode(_TOAST_PS_B64).decode('utf-16-le')
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps,
             str(title), str(message)],
            capture_output=True, timeout=10, check=False
        )
        log_event("toast_sent", title=title, message=message, event_type=event_type)
        return True
    except Exception as e:
        log_error("toast_failed", error=e, title=title)
        return False


PORT = int(os.environ.get("VRAM_CONSOLE_PORT", "8787"))
HOST = os.environ.get("VRAM_CONSOLE_HOST", "0.0.0.0")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 认证模块（邮件+密码+Session，2026-08-29 主公批准）
import auth as auth_mod


def _load_token():
    """Token 认证配置：优先环境变量 VRAM_CONSOLE_TOKEN，其次本地 .api_token 文件。
    设置后所有 POST 和 /api/status 需带 X-API-Key 请求头。.api_token 不应纳入公开仓库。"""
    env = os.environ.get("VRAM_CONSOLE_TOKEN", "")
    if env:
        return env
    try:
        with open(os.path.join(BASE_DIR, ".api_token"), "r", encoding="ascii") as f:
            return f.read().strip()
    except Exception:
        return ""


API_TOKEN = _load_token()
# 脚本路径：默认使用项目内 scripts/ 目录，可通过环境变量覆盖
GPU_RELEASE_PS1 = os.environ.get("GPU_RELEASE_PS1",
    os.path.join(BASE_DIR, "..", "scripts", "vram_cleanup.ps1"))
GAME_ON_PS1 = os.environ.get("GAME_ON_PS1",
    os.path.join(BASE_DIR, "..", "scripts", "game-on.ps1"))
# === 资源注册表（配置驱动，消除硬编码）===
REGISTRY_PATH = os.path.join(BASE_DIR, "resources", "registry.json")

def load_registry():
    """加载资源注册表，失败时返回空 dict（使用硬编码兜底）"""
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_error("registry_load_failed", error=e, path=REGISTRY_PATH)
        return {}

REGISTRY = load_registry()

# 从注册表读取配置，无则用硬编码兜底
OLLAMA_CONTAINER = REGISTRY.get("ollama", {}).get("container", "ollama")
# 需要管理的 Ollama 模型列表（从注册表动态生成，过滤掉 CPU 模型）
BIG_MODELS = [m["id"] for m in REGISTRY.get("ollama", {}).get("models", [])
              if m.get("category") == "llm"] or ["qwen3.5:9b", "qwen3:0.6b", "qwythos-9b:q4km", "darkidol-8b:q4km"]
LAST_SCENE = {"scene": None}  # 记录最近一次手动切换(区分 comfy/music/h3 共用容器)

log_event("registry_loaded", models_count=len(BIG_MODELS), container=OLLAMA_CONTAINER)

# Ollama 模型名安全格式：字母/数字/点/冒号/破折号/斜杠，禁止分号、管道、空格等 shell 元字符
_MODEL_NAME_RE = re.compile(r'^[A-Za-z0-9._:/\-]+$')


def _safe_model_name(name):
    """校验模型名是否安全，返回 (ok, name_or_error)。
    禁止路径穿越（..）、绝对路径开头、shell 元字符。"""
    if not name or not isinstance(name, str):
        return False, "empty model name"
    if len(name) > 128:
        return False, "model name too long"
    if ".." in name:
        return False, "invalid model name (path traversal '..' not allowed)"
    if name.startswith("/") or name.startswith("\\"):
        return False, "invalid model name (absolute path not allowed)"
    if not _MODEL_NAME_RE.match(name):
        return False, "invalid model name (only letters, digits, . : / - allowed)"
    return True, name


def run_args(args, timeout=30):
    """安全执行命令（shell=False + 参数数组），用于包含用户输入的命令"""
    try:
        p = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -2, str(e)


def run_ps1(path, timeout=120):
    """执行 PowerShell 脚本（shell=False + 参数数组，路径经硬编码常量传入）"""
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
            shell=False, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -2, str(e)


def gpu_status():
    rc, out = run_args(["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu", "--format=csv,noheader,nounits"], 10)
    if rc != 0:
        return {"ok": False, "error": out[:200]}
    parts = [x.strip() for x in out.strip().split(",")]
    util = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    return {"ok": True, "total_mb": int(parts[0]), "used_mb": int(parts[1]), "free_mb": int(parts[2]),
            "utilization": util}


def _container_pids(cont):
    """容器内进程 PID → comm 映射（docker exec ps，只读）。"""
    rc, out = run_args(["docker", "exec", cont, "ps", "-eo", "pid=,comm="], 10)
    if rc != 0:
        return {}
    pmap = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            pmap[parts[0]] = parts[1]
    return pmap


def _gpu_app_pids(names=None):
    """从在跑的受管容器拿 GPU 计算进程 PID 列表（容器内 NVML compute-apps）。
    WSL2 实测：容器内 NVML 可见 GPU 进程 PID（跨容器全局视角），但 used_memory/process_name 拿不到（[N/A]/[Not Found]）。
    高负载下 docker exec 可能超时→返回空，由调用方用 ps 进程名识别兜底。
    返回 (pids_list, src_container)。"""
    if names is None:
        names = docker_containers()
    for cont in ("comfyui", "ollama", "fooocus"):
        if cont in names:
            rc, out = run_args(["docker", "exec", cont, "nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"], 10)
            if rc == 0:
                pids = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
                if pids:
                    return pids, cont
    return [], None


# === Windows 桌面 GPU 进程账本（2026-08-28，主公：完整显存账本拼合） ===
def desktop_gpu_processes():
    """宿主机侧 nvidia-smi 进程表 → Windows 桌面 GPU 进程（PID+进程名）。
    WSL2 GPU-PV 实测：宿主机 nvidia-smi 能列出 Windows 桌面进程的 PID+process_name，
    但 used_memory 为 [N/A]（拿不到逐进程显存）。与容器账本互补 → 拼成完整显存账本。"""
    rc, out = run_args(["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"], 10)
    desktop = []
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            pid_s, name = parts[0], parts[1]
            if pid_s.isdigit() and name and name.lower() not in (
                    "[insufficient permissions]", "[not found]", "n/a", "[n/a]"):
                desktop.append({"pid": int(pid_s), "name": os.path.basename(name.replace("\\", "/"))})
    return {"ok": rc == 0, "processes": desktop, "count": len(desktop)}


# === Windows 桌面进程 Helper（方案A：主 server 不提权，仅用户需要时经 UAC 启用最小提权 Helper） ===
HELPER_PORT = 8788
HELPER_HOST = "127.0.0.1"
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


def _config():
    d = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        pass
    if not d.get("helper_token"):
        d["helper_token"] = uuid.uuid4().hex
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return d


def _helper_health():
    """探测 Helper 是否在运行（127.0.0.1:8788，带 token）。"""
    token = _config().get("helper_token", "")
    try:
        req = urllib.request.Request("http://{}:{}/api/health".format(HELPER_HOST, HELPER_PORT),
                                     headers={"X-API-Key": token})
        with urllib.request.urlopen(req, timeout=2) as r:
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
    """进程级探测：返回 vram-helper.py 进程数（幂等防重复，不依赖端口/token）。"""
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vram-helper' } | Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=10)
        n = int((ps.stdout or "0").strip() or "0")
        return n
    except Exception:
        return 0


def _helper_kill_processes():
    """强杀所有 vram-helper 进程（用于端口不通时的停止/清理）。"""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vram-helper' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        pass


def helper_status():
    return {"ok": True, "running": _helper_health(), "process_count": _helper_process_count()}


def helper_start():
    """启用 Helper：异步以管理员身份启动 vram-helper.py（ShellExecute runas → UAC，用户确认）。
    防重复双保险：端口探测（_helper_health）+ 进程探测（_helper_process_count），绝不启动多个。"""
    if _helper_health():
        return {"ok": True, "running": True, "msg": "Helper 已在运行"}
    if _helper_process_count() > 0:
        return {"ok": False, "running": False,
                "msg": "检测到 vram-helper 进程已存在但 8788 端口无响应（token 不匹配/端口占用），请先点「停用 Helper」清理后再启用"}
    token = _config().get("helper_token", "")
    script = os.path.join(BASE_DIR, "vram-helper.py")

    def _spawn():
        try:
            import sys
            import ctypes
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable,
                '"{}" --token {}'.format(script, token), BASE_DIR, 1)
        except Exception as e:
            log_error("helper_start_failed", error=e)

    threading.Thread(target=_spawn, daemon=True).start()
    return {"ok": True, "running": False, "msg": "UAC 已弹出，请在弹窗中点「是」启用 Helper"}


def helper_stop():
    """停用 Helper：先请求自退，再进程级兜底强杀（保证不残留、可重新启用）。"""
    if _helper_health():
        _helper_req("/api/exit")
        time.sleep(1.0)
    _helper_kill_processes()
    return {"ok": True, "running": False, "msg": "Helper 已停止"}


def desktop_vram_detail():
    """桌面逐进程显存明细：经 Helper 代理（需 Helper 已启用）。"""
    if not _helper_health():
        return {"ok": False, "processes": [], "count": 0, "error": "helper not running", "helper": False}
    ok, r = _helper_req("/api/desktop_vram")
    if ok:
        r["helper"] = True
    return r


def desktop_kill(pid):
    """结束桌面进程：经 Helper 代理（需 Helper 已启用）。"""
    if not _helper_health():
        return {"ok": False, "error": "helper not running"}
    ok, r = _helper_req("/api/desktop/kill", {"pid": pid})
    return r


def gpu_processes():
    """进程级显存账本（主公要求 2026-08-28，按蓝图进程级实现）：
    - PID：容器内 NVML compute-apps 可见的 GPU 进程 PID（跨容器全局视角）
    - 进程名：各受管容器 ps
    - 显存：进程自身运行时自报（ollama /api/ps 模型 size；comfyui /system_stats torch_vram_used；fooocus 规格 6.9G）
    - 未归属受管容器的 GPU 进程 → unknown_pids（白占，门卫点名）
    WSL2 实测依据：NVML 拿得到 PID、拿不到 used_memory/process_name（[N/A]/[Not Found]），
    故「PID 以 NVML 为准 + 显存以进程自报为准」拼接出进程级账本。"""
    gpu = gpu_status()
    names = docker_containers()
    # 1. 受管容器进程表（pid -> (app, comm)）
    cont_pids = {}
    for cont, app in (("comfyui", "comfyui"), ("ollama", "ollama"), ("fooocus", "fooocus")):
        if cont in names:
            for pid, comm in _container_pids(cont).items():
                cont_pids[pid] = (app, comm)
    # 2. GPU 进程 PID（优先 NVML；WSL2 高负载下 docker exec 可能超时→用容器内 ps 进程名识别兜底）
    gpu_pids, src = _gpu_app_pids(names)
    if not gpu_pids:
        gpu_pids = [pid for pid, (app, comm) in cont_pids.items()
                    if (app == "ollama" and "llama-server" in comm.lower())
                    or (app == "comfyui" and ("python" in comm.lower() or "comfy" in comm.lower()))
                    or (app == "fooocus" and "python" in comm.lower())]
        src = "ps_fallback" if gpu_pids else None
    # 3. 服务自报显存（进程级数据源）
    ollama_models = ollama_ps().get("models", [])
    ollama_used_mb = sum(int(m.get("size_gb", 0) * 1024) for m in ollama_models)
    comfy_stat = comfy_system_stats()
    comfy_used_mb = comfy_stat.get("torch_vram_used_mb", 0) or 0
    # 4. 组装进程级条目
    processes = []
    for pid in gpu_pids:
        if pid not in cont_pids:
            continue
        app, comm = cont_pids[pid]
        if app == "ollama":
            used = ollama_used_mb if ("llama" in comm.lower() or comm.lower() == "ollama") else 0
        elif app == "comfyui":
            used = comfy_used_mb if ("python" in comm.lower() or "comfy" in comm.lower()) else 0
        elif app == "fooocus":
            used = int(6.9 * 1024)
        else:
            used = 0
        processes.append({"pid": pid, "name": comm, "app": app, "used_mb": used, "known": True})
    # 5. unknown：GPU 进程不在受管容器（白占嫌疑）
    known_pids = {p["pid"] for p in processes}
    unknown_pids = [pid for pid in gpu_pids if pid not in known_pids]
    # 6. unknown 差量（实际 used − 底噪 − 已知进程自报）
    known_total = sum(p["used_mb"] for p in processes)
    unknown_mb = 0
    if gpu.get("ok"):
        unknown_mb = max(0, gpu["used_mb"] - 1536 - known_total)
    # 7. 进程生命周期差分（首见/退出时间戳 + 显存快照）——主公要求 2026-08-28
    _update_process_lifecycle(gpu_pids, processes)
    for p in processes:
        lc = _proc_lifecycle.get(p["pid"])
        if lc:
            p["first_seen"] = lc["first_seen"]
            p["first_used_mb"] = lc["first_used_mb"]
            p["exit_seen"] = lc.get("exit_seen")
    # 8. Windows 桌面进程账本（完整账本拼合：容器 + 桌面）
    #    桌面显存汇总 = 总显存 − 容器已归因 − 桌面合成底噪(约 400MB: DWM/桌面合成器)
    desktop = desktop_gpu_processes()
    desktop_used_mb = 0
    if gpu.get("ok"):
        desktop_used_mb = max(0, gpu["used_mb"] - known_total - 400)
    return {
        "ok": True, "processes": processes,
        "unknown_pids": unknown_pids, "unknown_mb": unknown_mb,
        "baseline_mb": 1536, "known_total_mb": known_total,
        "desktop_processes": desktop.get("processes", []),
        "desktop_count": desktop.get("count", 0),
        "desktop_used_mb": desktop_used_mb,
        "system_baseline_mb": 400,
        "gpu_pid_source": src,
        "events": list(_proc_events),
    }


# === 进程生命周期追踪（2026-08-28，主公要求：何时开始/退出/首见显存） ===
_proc_lifecycle = {}      # pid -> {first_seen,last_seen,name,app,first_used_mb,exit_seen}
_proc_events = deque(maxlen=200)  # 事件时间线：{ts,event:up|down|kick,pid,name,app,used_mb,alive_s?}
_last_known_pids = set()
_lifecycle_init = False


def _update_process_lifecycle(gpu_pids, processes):
    """进程状态差分：新 PID 记首见(时间+显存快照)+up 事件；消失 PID 记退出+down 事件。
    首次调用只登记不产生事件（避免把存量进程误报为'新出现'）。"""
    global _last_known_pids, _lifecycle_init
    now = int(time.time())
    cur = set(gpu_pids)
    by_pid = {p["pid"]: p for p in processes}
    if not _lifecycle_init:
        for pid in cur:
            p = by_pid.get(pid)
            _proc_lifecycle[pid] = {
                "first_seen": now, "last_seen": now,
                "name": (p or {}).get("name", "unknown"),
                "app": (p or {}).get("app", "unknown"),
                "first_used_mb": (p or {}).get("used_mb", 0),
                "exit_seen": None}
        _last_known_pids = cur
        _lifecycle_init = True
        return
    # 新出现
    for pid in cur - _last_known_pids:
        p = by_pid.get(pid)
        _proc_lifecycle[pid] = {
            "first_seen": now, "last_seen": now,
            "name": (p or {}).get("name", "unknown"),
            "app": (p or {}).get("app", "unknown"),
            "first_used_mb": (p or {}).get("used_mb", 0),
            "exit_seen": None}
        _proc_events.appendleft({"ts": now, "event": "up", "pid": pid,
                                 "name": _proc_lifecycle[pid]["name"],
                                 "app": _proc_lifecycle[pid]["app"],
                                 "used_mb": _proc_lifecycle[pid]["first_used_mb"]})
    # 已在的进程刷新 last_seen + name/app
    for pid in cur & _last_known_pids:
        if pid not in _proc_lifecycle:
            continue
        p = by_pid.get(pid)
        if p:
            _proc_lifecycle[pid]["name"] = p.get("name", _proc_lifecycle[pid]["name"])
            _proc_lifecycle[pid]["app"] = p.get("app", _proc_lifecycle[pid]["app"])
        _proc_lifecycle[pid]["last_seen"] = now
    # 消失
    for pid in _last_known_pids - cur:
        if pid in _proc_lifecycle:
            lc = _proc_lifecycle[pid]
            lc["exit_seen"] = now
            _proc_events.appendleft({"ts": now, "event": "down", "pid": pid,
                                     "name": lc["name"], "app": lc["app"],
                                     "used_mb": lc.get("first_used_mb", 0),
                                     "alive_s": now - lc["first_seen"]})
    _last_known_pids = cur


# === L2 强制驱逐（2026-08-28，主公要求：强制驱逐能力） ===
PROTECT_COMMS = {"dwm.exe", "explorer.exe", "init", "supervisord", "caddy"}


def _find_pid_container(pid):
    """找 PID 归属的容器（受管优先，再遍历全部）。返回容器名或 None。"""
    names = docker_containers()
    for cont in ("comfyui", "ollama", "fooocus"):
        if cont in names and pid in _container_pids(cont):
            return cont
    rc, out = run_args(["docker", "ps", "--format", "{{.Names}}"], 10)
    if rc == 0:
        for cont in out.splitlines():
            cont = cont.strip()
            if cont and pid in _container_pids(cont):
                return cont
    return None


def gpu_guard_kick(pid):
    """L2 强制驱逐单个进程：验明正身（容器归属 + 进程名）→ docker exec kill -9。
    保护边界：protect 类进程拒绝；找不到容器（WSL2 VM 直跑）拒绝并提示。"""
    pid = str(pid).strip()
    if not pid.isdigit():
        return {"ok": False, "error": "invalid pid"}
    cont = _find_pid_container(pid)
    if not cont:
        return {"ok": False,
                "error": "PID %s 未在任何容器中找到，无法自动驱逐（可能 WSL2 VM 直跑，需人工处理）" % pid}
    cmap = _container_pids(cont)
    comm = cmap.get(pid, "")
    if comm.lower() in PROTECT_COMMS:
        return {"ok": False, "error": "拒绝驱逐 protect 进程 %s (PID %s)" % (comm, pid)}
    rc, out = run_args(["docker", "exec", cont, "kill", "-9", pid], 10)
    if rc == 0:
        _proc_events.appendleft({"ts": int(time.time()), "event": "kick", "pid": pid,
                                 "name": comm, "app": cont, "used_mb": 0})
        log_event("guard_kick", pid=pid, container=cont, comm=comm)
        toast_notify("GMae 门卫驱逐", "已强制驱逐进程 %s (PID %s) 于容器 %s" % (comm, pid, cont),
                     event_type="guard_kick", cooldown_s=60)
        return {"ok": True, "message": "已强制驱逐 PID %s (%s) 于容器 %s" % (pid, comm, cont),
                "pid": pid, "container": cont, "comm": comm}
    return {"ok": False, "error": "驱逐失败 rc=%s %s" % (rc, out[-200:])}


def ollama_ps():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=3) as r:
            d = json.loads(r.read().decode("utf-8"))
        models = [{"name": m.get("name", ""), "size_gb": round(m.get("size", 0) / 1e9, 1),
                   "until": (m.get("expires_at") or "")[11:19]} for m in d.get("models", [])]
        return {"ok": True, "models": models}
    except Exception:
        return {"ok": False, "models": [], "error": "offline/timeout"}


def ollama_tags():
    """获取已安装的 Ollama 模型列表，返回 set(name)；失败返回空 set"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        return {m.get("name", "") for m in d.get("models", [])}
    except Exception:
        return set()


def docker_containers():
    rc, out = run_args(["docker", "ps", "--format", "{{.Names}}"], 10)
    if rc != 0:
        return []
    return [x.strip() for x in out.splitlines() if x.strip()]


def infer_scene(containers):
    if "fooocus" in containers:
        return "fooocus"
    if "comfyui" in containers:
        return "comfy"
    return "dialogue"


def comfy_system_stats():
    """ComfyUI /system_stats：设备级显存实测（容器内服务自报，torch 视角）。
    这是「服务级显存账本」中 ComfyUI 的权威数据源：
    宿主机/容器内 nvidia-smi compute-apps 在 WSL2 GPU-PV 下均拿不到进程显存（实测 [Not Found]/[N/A]），
    但 ComfyUI 自身通过 torch 知道它占了多少（torch_vram_used）。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        dev = (d.get("devices") or [{}])[0]
        return {"ok": True, "device": dev.get("name", ""),
                "vram_total_mb": (dev.get("vram_total") or 0) // 1024 // 1024,
                "vram_free_mb": (dev.get("vram_free") or 0) // 1024 // 1024,
                "torch_vram_used_mb": (dev.get("torch_vram_used") or 0) // 1024 // 1024}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def comfy_queue():
    """ComfyUI /queue：正在跑 / 排队任务（蓝图 5.1 待接，配合进程账本判断'ComfyUI 是否在忙'）。
    queue_running/queue_pending 每项为 [prompt_id, workflow_nodes, ...]，取首节点 class_type 作概要。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

    def brief(items):
        out = []
        for it in (items or []):
            if not isinstance(it, (list, tuple)) or not it:
                continue
            # ComfyUI 队列项结构：[序号, prompt_id, workflow_nodes, extra...]；取第一个 dict 为节点
            nodes = next((x for x in it if isinstance(x, dict)), None)
            cls = ""
            if nodes:
                for _k, v in nodes.items():
                    if isinstance(v, dict) and v.get("class_type"):
                        cls = v["class_type"]
                        break
            pid = it[1] if len(it) > 1 and isinstance(it[1], str) else (it[0] if it else "")
            out.append({"id": pid, "class_type": cls})
        return out

    running = brief(d.get("queue_running"))
    pending = brief(d.get("queue_pending"))
    return {"ok": True, "running": running, "pending": pending,
            "running_count": len(running), "pending_count": len(pending)}


# === 服务活跃度追踪（蓝图 5.2，Idle Reaper 依据） ===
_LAST_BUSY = {}  # service -> 最后观测到忙碌的时间戳


def _mark_busy(svc):
    _LAST_BUSY[svc] = int(time.time())


def service_activity():
    """蓝图 5.2 服务活跃度：观测式记录各服务最后忙碌时间 → 空闲时长，供 Idle Reaper 判定空闲。
    观测信号：ollama /api/ps 有模型加载；comfyui /queue 有任务。忙碌时刷新 last_busy；
    不忙时 idle_s = 距最后忙碌的时间。"""
    now = int(time.time())
    om = ollama_ps().get("models", [])
    if om:
        _mark_busy("ollama")
    cq = comfy_queue()
    busy_comfy = cq.get("ok") and (cq.get("running_count", 0) + cq.get("pending_count", 0)) > 0
    if busy_comfy:
        _mark_busy("comfyui")
    out = {}
    for svc, running in (("ollama", bool(om)), ("comfyui", busy_comfy), ("fooocus", False)):
        lb = _LAST_BUSY.get(svc)
        out[svc] = {"busy": running, "last_busy": lb,
                    "idle_s": (now - lb) if (lb is not None and not running) else 0}
    return {"ok": True, "services": out, "ts": now}


# === Idle Reaper：空闲自动回收显存（基于蓝图 5.2 活跃度） ===
# 默认启用；阈值可通过环境变量覆盖（VRAM_REAPER_*）。
REAPER_CFG = {
    "enabled": os.environ.get("VRAM_REAPER_ENABLED", "1") != "0",
    "check_interval_s": int(os.environ.get("VRAM_REAPER_INTERVAL", "60")),
    "thresholds_s": {
        "ollama": int(os.environ.get("VRAM_REAPER_OLLAMA_S", "1800")),      # 空闲 30 分钟
        "comfyui": int(os.environ.get("VRAM_REAPER_COMFYUI_S", "1800")),
        "fooocus": int(os.environ.get("VRAM_REAPER_FOOOCUS_S", "1800")),
    },
}


def _reap_service(svc, idle_s):
    """执行空闲回收：ollama 卸载空闲模型；comfyui 释放显存。调用前已确认该服务不忙。"""
    log_event("idle_reaper_reap", service=svc, idle_s=idle_s)
    if svc == "ollama":
        for m in ollama_ps().get("models", []):
            name = m.get("model") or m.get("name")
            if not name:
                continue
            try:
                rc, _ = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "stop", name], 60)
                log_event("idle_reaper_ollama_stop", model=name, rc=rc)
            except Exception as e:
                log_error("idle_reaper_ollama_stop_failed", error=e, model=name)
    elif svc == "comfyui":
        try:
            r = comfy_free()
            log_event("idle_reaper_comfy_free", ok=r.get("ok"), error=r.get("error"))
        except Exception as e:
            log_error("idle_reaper_comfy_free_failed", error=e)
    # 防重复：回收后清空 last_busy，直到下次真正忙碌才重新进入可回收态
    _LAST_BUSY.pop(svc, None)


def _idle_reaper_loop():
    log_event("idle_reaper_start", enabled=REAPER_CFG["enabled"],
              thresholds_s=REAPER_CFG["thresholds_s"], check_interval_s=REAPER_CFG["check_interval_s"])
    while True:
        try:
            time.sleep(REAPER_CFG["check_interval_s"])
            if not REAPER_CFG["enabled"]:
                continue
            act = service_activity()
            if not act.get("ok"):
                continue
            now = act["ts"]
            for svc, x in act["services"].items():
                thr = REAPER_CFG["thresholds_s"].get(svc)
                if not thr:
                    continue
                if x.get("busy"):
                    continue          # 绝不打断忙碌服务
                lb = x.get("last_busy")
                if lb is None:
                    continue          # 从未忙碌：无需回收
                if (now - lb) >= thr:
                    _reap_service(svc, now - lb)
        except Exception as e:
            log_error("idle_reaper_error", error=e)


def start_idle_reaper():
    t = threading.Thread(target=_idle_reaper_loop, daemon=True, name="idle-reaper")
    t.start()
    return t


# === Step 5 QoS 服务等级引擎（蓝图 §5，2026-08-30 主公确认：分级降级）===
# 紧急（空闲<2GB）：直接停最低优先级模型 + 简洁通知
# 非紧急（空闲<4GB）：给降级建议 + 用户确认后执行
QOS_CFG = {
    "emergency_threshold_mb": 2048,
    "warning_threshold_mb": 4096,
    "check_interval_s": 10,
    "enabled": True,
    "cooldown_s": 60,
}
_qos_state = {
    "level": "ok",
    "last_emergency_ts": 0,
    "last_action": None,
    "suggestions": [],
    "history": deque(maxlen=50),
}


def qos_check():
    if not QOS_CFG["enabled"]:
        return {"level": "disabled"}
    gpu = gpu_status()
    if not gpu.get("ok"):
        return {"level": "unknown", "error": "nvidia-smi unavailable"}
    free_mb = gpu.get("free_mb", 99999)
    now = time.time()
    if free_mb < QOS_CFG["emergency_threshold_mb"]:
        if now - _qos_state["last_emergency_ts"] > QOS_CFG["cooldown_s"]:
            result = _qos_emergency_downgrade(free_mb)
            _qos_state["last_emergency_ts"] = now
            _qos_state["level"] = "emergency"
            _qos_state["last_action"] = result
            _qos_state["history"].append({"ts": now, "level": "emergency", "free_mb": free_mb})
            return result
        else:
            return {"level": "emergency", "cooldown": True}
    elif free_mb < QOS_CFG["warning_threshold_mb"]:
        suggestions = _qos_build_suggestions(free_mb)
        _qos_state["level"] = "warning"
        _qos_state["suggestions"] = suggestions
        return {"level": "warning", "free_mb": free_mb, "free_gb": round(free_mb / 1024, 1),
                "suggestions": suggestions,
                "message": "显存紧张（%.1fGB 空闲），建议释放以下资源：" % (free_mb / 1024)}
    else:
        _qos_state["level"] = "ok"
        _qos_state["suggestions"] = []
        return {"level": "ok", "free_mb": free_mb, "free_gb": round(free_mb / 1024, 1)}


def _qos_emergency_downgrade(free_mb):
    actions = []
    freed_mb = 0
    try:
        if "comfyui" in docker_containers():
            result = comfy_free()
            if result.get("ok"):
                actions.append("已释放 ComfyUI 显存")
                freed_mb += 2000
    except Exception as e:
        log_error("qos_emergency_comfy_free_error", error=str(e))
    try:
        ollama_loaded = ollama_ps().get("models", [])
        if len(ollama_loaded) > 1:
            to_stop = [m.get("model") for m in ollama_loaded[1:] if m.get("model")]
            if to_stop:
                ollama_stop(to_stop)
                actions.append("已停止 Ollama 模型: %s" % ", ".join(to_stop))
    except Exception as e:
        log_error("qos_emergency_ollama_stop_error", error=str(e))
    try:
        if freed_mb < 2048 and "fooocus" in docker_containers():
            docker_action("fooocus", "stop")
            actions.append("已停止 Fooocus 容器")
    except Exception as e:
        log_error("qos_emergency_fooocus_stop_error", error=str(e))
    message = "紧急：显存仅 %.1fGB，已自动释放。建议：关闭非必要应用。" % (free_mb / 1024)
    log_event("qos_emergency_downgrade", free_mb=free_mb, actions=actions)
    toast_notify("GMae 紧急显存释放", message, event_type="qos_emergency", cooldown_s=120)
    return {"level": "emergency", "free_mb": free_mb, "free_gb": round(free_mb / 1024, 1),
            "actions": actions, "message": message,
            "next_step": "显存释放后可恢复正常使用；如持续紧张，请关闭非必要 GPU 应用。"}


def _qos_build_suggestions(free_mb):
    suggestions = []
    try:
        ollama_loaded = ollama_ps().get("models", [])
        for m in ollama_loaded:
            model_name = m.get("model", "")
            size_gb = float(m.get("size_gb", 0))
            suggestions.append({
                "id": "ollama_stop_%s" % model_name,
                "type": "ollama_stop",
                "model": model_name,
                "vram_gb": round(size_gb, 1),
                "action": "停止 %s（释放 %.1fGB）" % (model_name, size_gb),
                "priority": "medium",
            })
    except Exception:
        pass
    try:
        if "comfyui" in docker_containers():
            suggestions.append({
                "id": "comfy_free", "type": "comfy_free",
                "action": "ComfyUI /free（释放生成模型显存，约 2-6GB）",
                "priority": "low",
            })
    except Exception:
        pass
    try:
        if "fooocus" in docker_containers():
            suggestions.append({
                "id": "fooocus_stop", "type": "fooocus_stop",
                "action": "停止 Fooocus 容器（释放约 7GB）",
                "priority": "high",
            })
    except Exception:
        pass
    priority_order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))
    return suggestions


def qos_execute_suggestion(suggestion_id):
    suggestions = _qos_state.get("suggestions", [])
    target = next((s for s in suggestions if s["id"] == suggestion_id), None)
    if not target:
        return {"ok": False, "error": "suggestion not found: %s" % suggestion_id}
    try:
        if target["type"] == "ollama_stop":
            ollama_stop([target["model"]])
            msg = "已停止 %s" % target["model"]
        elif target["type"] == "comfy_free":
            comfy_free()
            msg = "已释放 ComfyUI 显存"
        elif target["type"] == "fooocus_stop":
            docker_action("fooocus", "stop")
            msg = "已停止 Fooocus 容器"
        else:
            return {"ok": False, "error": "unknown type"}
        log_event("qos_user_downgrade", suggestion_id=suggestion_id, message=msg)
        new_state = qos_check()
        return {"ok": True, "message": msg, "new_state": new_state}
    except Exception as e:
        log_error("qos_execute_error", error=str(e))
        return {"ok": False, "error": str(e)}


def qos_status():
    return {
        "level": _qos_state["level"],
        "last_action": _qos_state["last_action"],
        "suggestions": _qos_state["suggestions"],
        "config": QOS_CFG,
        "history": list(_qos_state["history"])[-10:],
    }


def _qos_loop():
    log_event("qos_loop_start", enabled=QOS_CFG["enabled"])
    while True:
        try:
            qos_check()
        except Exception as e:
            log_error("qos_loop_error", error=str(e))
        time.sleep(QOS_CFG["check_interval_s"])


def start_qos():
    t = threading.Thread(target=_qos_loop, daemon=True, name="qos-engine")
    t.start()
    return t


# === ComfyUI WebSocket 实时事件（蓝图 5.1 待接：任务开始/完成/进度推送，取代纯轮询） ===
_COMFY_EVENTS = deque(maxlen=300)          # 最近事件（前端 /api/comfy_events 拉取）
_COMFY_EVENTS_LOCK = threading.Lock()


class ComfyWS:
    """极简 WebSocket 客户端（纯标准库，无第三方依赖）：连接 ComfyUI /ws 实时事件流。"""

    def __init__(self, host="127.0.0.1", port=8188):
        self.host, self.port = host, port
        self.client_id = uuid.uuid4().hex
        self.sock = None
        self._buf = b""

    def connect(self):
        key = base64.b64encode(os.urandom(16)).decode()
        path = "/ws?clientId=" + self.client_id
        req = ("GET %s HTTP/1.1\r\n"
               "Host: %s:%d\r\n"
               "Upgrade: websocket\r\n"
               "Connection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n") % (path, self.host, self.port, key)
        s = socket.create_connection((self.host, self.port), timeout=5)
        s.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        if b"101" not in resp.split(b"\r\n", 1)[0]:
            s.close()
            raise ConnectionError("ws 握手失败: " + resp[:80].decode(errors="replace"))
        self.sock = s
        self._buf = b""

    def _read_frame(self):
        """读一帧（服务端→客户端不 mask）。返回 (opcode, payload)。"""
        while len(self._buf) < 2:
            self._buf += self.sock.recv(4096)
        opcode = self._buf[0] & 0x0F
        ln = self._buf[1] & 0x7F
        off = 2
        if ln == 126:
            while len(self._buf) < 4:
                self._buf += self.sock.recv(4096)
            ln = struct.unpack(">H", self._buf[2:4])[0]
            off = 4
        elif ln == 127:
            while len(self._buf) < 10:
                self._buf += self.sock.recv(4096)
            ln = struct.unpack(">Q", self._buf[2:10])[0]
            off = 10
        while len(self._buf) < off + ln:
            self._buf += self.sock.recv(4096)
        payload = self._buf[off:off + ln]
        self._buf = self._buf[off + ln:]
        return opcode, payload

    def send_ctrl(self, opcode, payload=b""):
        """发送控制帧（客户端→服务器需 mask）。opcode 9=ping, 10=pong。"""
        mask = os.urandom(4)
        ln = len(payload)
        header = bytearray([0x80 | opcode])
        if ln < 126:
            header += bytearray([0x80 | ln])
        elif ln < 65536:
            header += bytearray([0x80 | 126]) + struct.pack(">H", ln)
        else:
            header += bytearray([0x80 | 127]) + struct.pack(">Q", ln)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_message(self, timeout=30):
        """收一条文本消息；收到 ping 自动回 pong；close 抛异常（上层重连）。"""
        self.sock.settimeout(timeout)
        while True:
            op, payload = self._read_frame()
            if op == 9:      # ping → pong
                self.send_ctrl(10, payload)
                continue
            if op == 8:      # close
                raise ConnectionError("ws closed")
            if op in (1, 2):  # text / binary
                return payload.decode("utf-8", errors="replace")
            # 其余 opcode 忽略


def _on_comfy_ws(raw):
    """解析 ComfyUI ws 消息：status / executing / executed / progress → 刷新活跃度 + 记录事件。"""
    try:
        m = json.loads(raw)
    except Exception:
        return
    t = m.get("type")
    d = m.get("data") or {}
    rec = {"ts": time.time(), "type": t}
    if t == "status":
        qr = (d.get("exec_info") or {}).get("queue_remaining", 0)
        if qr > 0:
            _mark_busy("comfyui")
        rec["queue_remaining"] = qr
    elif t in ("executing", "executed", "progress"):
        _mark_busy("comfyui")   # 任何任务推进都算 comfyui 活跃
        rec["prompt_id"] = (d.get("prompt_id") or "")[:8]
        node = d.get("node")
        if t == "executing":
            rec["state"] = "done" if node is None else "executing"
        if t == "progress":
            rec["progress"] = "{}/{}".format(d.get("value"), d.get("max"))
        if node is not None:
            rec["node"] = str(node)[:40]
    else:
        return
    with _COMFY_EVENTS_LOCK:
        _COMFY_EVENTS.append(rec)


def _comfy_ws_loop():
    """ComfyUI WebSocket 监听线程，断线指数退避重连（5s→10s→20s→30s封顶）。"""
    backoff = 5
    while True:
        ws = ComfyWS()
        try:
            ws.connect()
            log_event("comfy_ws_connected", client_id=ws.client_id)
            backoff = 5  # 连接成功，重置退避
            while True:
                msg = ws.recv_message(timeout=45)
                if msg:
                    _on_comfy_ws(msg)
        except Exception as e:
            log_error("comfy_ws_error", error=e, backoff_s=backoff)
            try:
                if ws.sock:
                    ws.sock.close()
            except Exception:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)  # 指数退避，封顶 30 秒


def comfy_events():
    """GET /api/comfy_events：最近 ComfyUI 实时事件（前端展示事件流）。"""
    with _COMFY_EVENTS_LOCK:
        events = list(_COMFY_EVENTS)
    return {"ok": True, "count": len(events), "events": events[-100:]}


def start_comfy_ws():
    t = threading.Thread(target=_comfy_ws_loop, daemon=True, name="comfy-ws")
    t.start()
    return t


def comfy_loaded_models():
    """从 ComfyUI /history 推断当前加载的模型（方案 A：工作流推断）。
    ComfyUI 无公开的 '当前加载模型' API，模型执行后会保留在显存中。
    取最近一次成功执行的工作流，解析其模型加载节点，映射到 registry.json。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/history", timeout=5) as r:
            history = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {"ok": False, "models": [], "total_vram_gb": 0, "note": "ComfyUI offline"}

    if not history:
        return {"ok": True, "models": [], "total_vram_gb": 0, "note": "no history"}

    # 找最近一次成功的 prompt（按 create_time 排序）
    latest_prompt = None
    latest_time = 0
    for pid, data in history.items():
        status = data.get("status", {})
        if status.get("status_str") != "success":
            continue
        prompt_data = data.get("prompt", [])
        if len(prompt_data) < 3:
            continue
        create_time = prompt_data[3].get("create_time", 0) if len(prompt_data) > 3 else 0
        if create_time > latest_time:
            latest_time = create_time
            latest_prompt = prompt_data[2]  # workflow nodes

    if not latest_prompt:
        return {"ok": True, "models": [], "total_vram_gb": 0, "note": "no successful prompt"}

    # 解析模型加载节点
    comfy_models = REGISTRY.get("comfyui", {}).get("models", [])
    # 关键词 → registry model id 映射
    keyword_map = {}
    for m in comfy_models:
        mid = m["id"]
        if mid == "SDXL":
            keyword_map["sd_xl"] = mid
            keyword_map["sdxl"] = mid
        elif mid == "Flux-Q5":
            keyword_map["flux"] = mid
        elif mid == "Wan2.2-TI2V":
            keyword_map["wan2"] = mid
            keyword_map["wan2.2"] = mid
            keyword_map["ti2v"] = mid
        elif mid == "Music3":
            keyword_map["music3"] = mid
            keyword_map["minimax_music3"] = mid

    loaded_ids = set()
    loaded_files = []
    for node_id, node in latest_prompt.items():
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})
        # 主模型加载节点
        model_file = None
        if class_type == "CheckpointLoaderSimple":
            model_file = inputs.get("ckpt_name", "")
        elif class_type == "UNETLoader":
            model_file = inputs.get("unet_name", "")
        if not model_file:
            continue
        loaded_files.append(model_file)
        # 关键词匹配
        model_lower = model_file.lower()
        for kw, mid in keyword_map.items():
            if kw in model_lower:
                loaded_ids.add(mid)
                break

    # 组装结果
    models = []
    total_vram = 0
    for m in comfy_models:
        if m["id"] in loaded_ids:
            models.append({
                "id": m["id"],
                "name": m["name"],
                "vram_gb": m["vram_gb"],
                "category": m.get("category", ""),
                "exclusive": m.get("exclusive", False),
            })
            total_vram += m["vram_gb"]

    note = "inferred from last workflow" if models else "no model detected in last workflow"
    # 用 ComfyUI 自报显存判断模型是否仍在显存（权威源 torch_vram_used，
    # 比 gpu used−底噪 可靠：桌面进程/系统占用不会干扰；每次轮询实时刷新）
    cstat = comfy_system_stats()
    torch_used = cstat.get("torch_vram_used_mb") or 0
    likely_loaded = False
    if models and torch_used > 1024:   # ComfyUI 自身占用 > 1G → 有模型驻留
        likely_loaded = True
        note = "inferred from last workflow (in VRAM, torch_vram_used={} MiB)".format(torch_used)
    elif models:
        note = "last workflow used this model, but currently not in VRAM (torch_vram_used={} MiB)".format(torch_used)
    return {
        "ok": True,
        "models": models,
        "total_vram_gb": round(total_vram, 1),
        "source_files": loaded_files,
        "note": note,
        "likely_loaded": likely_loaded,
        "torch_vram_used_mb": torch_used,
    }


# === /api/status 缓存（2.5s TTL，前端 3s 轮询时大多数请求即时返回）===
_STATUS_CACHE = {"data": None, "ts": 0}
_STATUS_CACHE_TTL = 2.5


def invalidate_status_cache():
    """POST 操作（切换场景/释放/驱逐）成功后调用，强制下次 status 重新采集。"""
    _STATUS_CACHE["ts"] = 0


def _safe_call(fn, default=None):
    """并行采集时单个调用失败不影响整体，返回 default。"""
    try:
        return fn()
    except Exception as e:
        log_error("status_parallel_fetch_error", func=fn.__name__, error=e)
        return default


def current_status():
    # 1. 缓存命中：直接返回（<10ms）
    now = time.time()
    if _STATUS_CACHE["data"] is not None and (now - _STATUS_CACHE["ts"]) < _STATUS_CACHE_TTL:
        cached = _STATUS_CACHE["data"].copy()
        cached["ts"] = int(now)
        cached["cached"] = True
        return cached

    # 2. 缓存未命中：并行采集所有独立外部调用
    tasks = {
        "gpu": gpu_status,
        "ops": ollama_ps,
        "names": docker_containers,
        "comfy_models": comfy_loaded_models,
        "comfy_q": comfy_queue,
        "gpu_procs": gpu_processes,
        "guard": gpu_guard_check,
        "ollama_tags": ollama_tags,
        "activity": service_activity,
        "helper": _helper_health,
    }
    results = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_map = {executor.submit(_safe_call, fn): key for key, fn in tasks.items()}
        for future in future_map:
            key = future_map[future]
            results[key] = future.result()

    gpu = results["gpu"] or {}
    ops = results["ops"] or {}
    names = results["names"] or set()
    comfy_models = results["comfy_models"]
    comfy_q = results["comfy_q"]
    gpu_procs = results["gpu_procs"]
    guard = results["guard"]
    installed = results["ollama_tags"] or []
    activity = results["activity"]
    helper = results["helper"]

    # 3. 场景推断（依赖 docker_containers 结果，纯计算）
    scene = infer_scene(names)
    last = LAST_SCENE["scene"]
    if last:
        if last in ("comfy", "music", "h3") and "comfyui" in names:
            scene = last
        elif last == "fooocus" and "fooocus" in names:
            scene = last
        elif last == "game" and "comfyui" not in names and "fooocus" not in names:
            scene = last
        elif last == "dialogue" and scene == "dialogue":
            scene = last

    # === 显存账本双源一致性检查（P0-1：nvidia-smi 权威总量 + ollama/comfy 明细，检测加载中/释放中）===
    ollama_models_list = ops.get("models", []) if ops else []
    ollama_loaded_mb = sum(int(float(m.get("size_gb", 0)) * 1024) for m in ollama_models_list)
    comfy_loaded_mb = 0
    if comfy_models:
        for cm in comfy_models:
            rm = next((x for x in REGISTRY.get("comfyui", {}).get("models", []) if x.get("id") == cm), None)
            if rm:
                comfy_loaded_mb += int(rm.get("vram_gb", 0) * 1024)
    noise_mb = 1200  # 桌面进程+系统噪声基线（空闲时约1.1GB，2026-08-29 观察数据得出）
    actual_used_mb = gpu.get("used_mb", 0) if gpu else 0
    expected_used_mb = noise_mb + ollama_loaded_mb + comfy_loaded_mb
    diff_mb = actual_used_mb - expected_used_mb
    if diff_mb > 1000:
        ledger_state = "loading"
        ledger_note = "显存高于模型明细 %.1fGB，可能有模型正在加载（ollama ps 延迟约15秒）" % (diff_mb / 1024)
    elif diff_mb < -1000:
        ledger_state = "releasing"
        ledger_note = "显存低于模型明细 %.1fGB，可能有模型正在释放" % (abs(diff_mb) / 1024)
    else:
        ledger_state = "consistent"
        ledger_note = "nvidia-smi 与模型明细一致"
    vram_ledger = {
        "state": ledger_state, "note": ledger_note,
        "actual_used_mb": actual_used_mb, "expected_used_mb": expected_used_mb,
        "diff_mb": diff_mb, "noise_mb": noise_mb,
        "ollama_loaded_mb": ollama_loaded_mb, "ollama_model_count": len(ollama_models_list),
        "comfy_loaded_mb": comfy_loaded_mb,
    }
    # P2-6: 加载/释放进度估算（前端显示"模型加载中，已占用X GB，预计还需Y秒"）
    if ledger_state == "loading":
        loading_mb = diff_mb  # 超出预期的显存 = 正在加载的模型已占用
        eta_s = max(3, int(loading_mb / 500))  # 粗略估算：500MB/秒，最少3秒
        vram_ledger["loading_progress"] = {
            "loaded_mb": loading_mb,
            "estimated_total_mb": loading_mb + 2000,  # 假设还有约2GB要加载
            "percent": min(95, int(loading_mb / (loading_mb + 2000) * 100)),
            "eta_seconds": eta_s,
            "message": "模型加载中，已占用 %.1fGB，预计还需 %d 秒（ollama ps 延迟约15秒）" % (loading_mb / 1024, eta_s),
        }
    elif ledger_state == "releasing":
        releasing_mb = abs(diff_mb)
        vram_ledger["releasing_progress"] = {
            "releasing_mb": releasing_mb,
            "eta_seconds": max(2, int(releasing_mb / 1000)),  # 释放较快，1GB/秒
            "message": "模型释放中，还有 %.1fGB 待释放，预计 %d 秒" % (releasing_mb / 1024, max(2, int(releasing_mb / 1000))),
        }

    data = {
        "gpu": gpu,
        "gpu_processes": gpu_procs,
        "guard": guard,
        "ollama": {**ops, "installed": sorted(installed)},
        "comfyui_models": comfy_models,
        "comfy_queue": comfy_q,
        "activity": activity,
        "containers": {
            "comfyui": "comfyui" in names,
            "fooocus": "fooocus" in names,
            "all": sorted(names),
        },
        "scene": scene,
        "helper_running": helper,
        "qos": {"level": _qos_state.get("level"), "degraded": _qos_state.get("last_action") is not None,
                "used_gb": None, "msg": _qos_state.get("last_action", {}).get("message", "") if _qos_state.get("last_action") else ""},
        "vram_ledger": vram_ledger,
        "ts": int(time.time()),
        "cached": False,
    }

    # 4. 存入缓存
    _STATUS_CACHE["data"] = data
    _STATUS_CACHE["ts"] = time.time()
    return data


def docker_action(name, action):
    """启停 Docker 容器，name/action 均做白名单校验，shell=False 防注入"""
    if name not in ("comfyui", "fooocus"):
        return -1, "unsupported container: " + str(name)
    if action not in ("start", "stop", "restart"):
        return -1, "unsupported action: " + str(action)
    return run_args(["docker", action, name], 60)


def ollama_stop_all():
    """停止所有已加载的 ollama 模型。
    优先从 /api/ps 动态获取当前加载的模型列表（避免硬编码遗漏），
    容器化后用 docker exec 调用 ollama CLI。"""
    # 动态获取当前已加载模型
    loaded = set()
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        for m in d.get("models", []):
            loaded.add(m.get("name", ""))
    except Exception:
        pass
    # 合并硬编码列表（兜底，防止 ps API 异常）
    targets = loaded | set(BIG_MODELS)
    bad = []
    outs = []
    for m in targets:
        if not m:
            continue
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "stop", m], 60)
        outs.append("{}:rc{}".format(m, rc))
        if rc != 0:
            bad.append(m)
    return (0 if not bad else 1), " | ".join(outs) + ("" if not bad else "  FAILED: " + ",".join(bad))


def wait_ready(port, timeout=90):
    """轮询容器 HTTP 端口就绪, 返回 (ok, waited_s)"""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:{}/".format(port), timeout=2):
                return True, int(timeout - (deadline - time.time()))
        except Exception:
            time.sleep(2)
    return False, timeout


def comfy_free():
    """Step 1 灵魂机制：调用 ComfyUI 官方 /free 端点，卸载模型 + 释放显存缓存。
    官方 API：POST /free  body={"unload_models": true, "free_memory": true}
    返回释放前后的显存快照。comfyui 容器未运行时无需释放。"""
    if "comfyui" not in docker_containers():
        return {"ok": False, "error": "comfyui 容器未运行，无需释放"}
    before = gpu_status()
    try:
        body = json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:8188/free", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            http_rc = resp.getcode()
    except Exception as e:
        log_error("comfy_free_failed", error=e)
        return {"ok": False, "error": "ComfyUI /free 调用失败: " + str(e)}
    # 显存释放为异步，短暂等待回落
    time.sleep(1)
    after = gpu_status()
    log_event("comfy_free", http=http_rc,
              vram_free_before=before.get("free_mb"), vram_free_after=after.get("free_mb"))
    return {
        "ok": True, "http": http_rc,
        "free_mb_before": before.get("free_mb"),
        "free_mb_after": after.get("free_mb"),
        "freed_mb": max(0, after.get("free_mb", 0) - before.get("free_mb", 0)),
    }


# === Step 2.5 gpu_guard 门卫（登记簿 + 驱逐） ===
GUARD_CFG = REGISTRY.get("gpu_guard", {})
GUARD_WARN_THRESHOLD = GUARD_CFG.get("warn_threshold_mb", 2048)
GUARD_UNKNOWN_POLICY = GUARD_CFG.get("unknown_policy", "warn")


def _guard_level(cur, new):
    order = {"ok": 0, "warning": 1, "critical": 2}
    return cur if order.get(cur, 0) >= order.get(new, 0) else new


def gpu_guard_check():
    """门卫检查（只读）：显存水位 + 场景违规 + 未登记占用 → 告警与建议驱逐清单。
    驱逐是事后执法 + 用户触发（L0 warn 默认），绝不自动杀（防误伤正在跑的任务）。"""
    gpu = gpu_status()
    procs = gpu_processes()
    names = docker_containers()
    g = {"ok": True, "level": "ok", "alerts": [], "suggest": [], "ts": int(time.time())}
    if not gpu.get("ok"):
        g["ok"] = False
        g["level"] = "error"
        g["alerts"].append("nvidia-smi 不可用，门卫盲区")
        return g
    free = gpu.get("free_mb", 0)
    # 1. 水位判定
    if free < 2048:
        g["level"] = _guard_level(g["level"], "critical")
        g["alerts"].append("显存空闲 %dMB < 2G，逼近打满（死机风险），建议立即驱逐" % free)
    elif free < 4096:
        g["level"] = _guard_level(g["level"], "warning")
        g["alerts"].append("显存空闲 %dMB < 4G，注意多余占用" % free)
    # 2. 场景违规（已登记容器在不该出现的场景运行）
    if "fooocus" in names and "comfyui" in names:
        g["level"] = _guard_level(g["level"], "warning")
        g["alerts"].append("Fooocus 与 ComfyUI 同跑 = 显存叠加风险")
        g["suggest"].append({"target": "fooocus", "evict": "docker stop fooocus", "reason": "scene conflict"})
    # 3. 未登记 GPU 进程（unknown_pids，白占点名）+ 显存差量
    unk = procs.get("unknown_mb", 0)
    unknown_pids = procs.get("unknown_pids", [])
    if unknown_pids:
        g["level"] = _guard_level(g["level"], "warning")
        g["alerts"].append("未登记 GPU 进程 %d 个（PID %s，差量 %dMB），策略=%s" %
                           (len(unknown_pids), ",".join(unknown_pids[:6]), unk, GUARD_UNKNOWN_POLICY))
        g["suggest"].append({"target": "unknown", "evict": "排查白占进程", "reason": "unknown pids"})
    elif unk > GUARD_WARN_THRESHOLD:
        g["level"] = _guard_level(g["level"], "warning")
        g["alerts"].append("显存差量 %dMB（已减底噪与已知进程自报），策略=%s" % (unk, GUARD_UNKNOWN_POLICY))
        g["suggest"].append({"target": "unknown", "evict": "排查白占进程", "reason": "unknown %dMB" % unk})
    return g


def gpu_guard_evict():
    """门卫驱逐（L2，仅对登记簿 managed 中可安全重启的服务，按优先级）：
    ollama 已加载模型 → comfyui /free → fooocus 容器。
    仅由用户显式触发（POST /api/guard evict=true），不自动执行。"""
    results = []
    gpu = gpu_status()
    rc, out = ollama_stop_all()
    results.append(("stop ollama models (L2a)", rc, out))
    if "comfyui" in docker_containers():
        r = comfy_free()
        results.append(("comfyui /free (L2b)", 0 if r.get("ok") else -1,
                        r.get("error", "freed %dMB" % r.get("freed_mb", 0))))
    if "fooocus" in docker_containers():
        rc, out = docker_action("fooocus", "stop")
        results.append(("stop fooocus (L2c)", rc, out))
    gpu2 = gpu_status()
    log_event("gpu_guard_evict", free_before=gpu.get("free_mb"), free_after=gpu2.get("free_mb"))
    return {"ok": True,
            "actions": [{"step": n, "rc": rc, "output": o[-200:]} for n, rc, o in results],
            "free_before": gpu.get("free_mb"), "free_after": gpu2.get("free_mb")}


def budget_engine(context_overrides=None):
    """Step 4 显存预算引擎（蓝图 §6）：核算每个已知模型「能不能跑、要释放多少、差多少」。
    context_overrides: {model_id: context_size} — 用户在预演模式指定的 context 大小，
                       优先从 model.context_vram 查找对应显存，找不到则用默认值+KV cache估算。
    公式（蓝图 6.1）：avail = total − 底噪 − 保留 − 其他进程占用(非受管)
         能跑 = 请求模型标称 + 不可释放占用 ≤ total − reserve
    决策四选一（6.2）：ok / free_L1 / free_L2 / reject（连释放都不够 → 差多少 GB）
    独占硬约束（6.4）：exclusive 模型加载前须释放所有其他受管模型（L1/L2 可释放）。"""
    sys_cfg = REGISTRY.get("system", {})
    total_mb = int(float(sys_cfg.get("gpu_vram_total_gb", 16)) * 1024)
    noise_mb = int(float(sys_cfg.get("gpu_base_noise_gb", 1.0)) * 1024)
    reserve_mb = int(float(sys_cfg.get("vram_reserve_gb", 2.5)) * 1024)
    safe_ceiling_mb = total_mb - reserve_mb   # 能加载的上限线
    gpu = gpu_status()
    procs = gpu_processes()   # 进程级账本（known / unknown / desktop）
    gen_stats = _load_gen_stats()  # 生成时间统计（预演模式"预计时间"）
    # 不可释放占用（非受管：unknown 白占 + 桌面进程，L4 只能提示）
    unreleasable_mb = (procs.get("unknown_mb") or 0) + (procs.get("desktop_used_mb") or 0)
    # 受管可释放（L1/L2/L3：已加载受管模型显存和）
    releasable_mb = procs.get("known_total_mb") or 0
    # 已加载模型集合
    ol_loaded = set()
    for m in ollama_ps().get("models", []):
        ol_loaded.add(m.get("model") or m.get("name"))
    cf_loaded = {m.get("id") or m.get("name") for m in comfy_loaded_models().get("models", [])}

    models = []
    for src_key, loaded_set in (("ollama", ol_loaded), ("comfyui", cf_loaded)):
        for m in REGISTRY.get(src_key, {}).get("models", []):
            mid = m["id"]
            # P0-2: context 维度显存计算（预演模式指定 context 时优先从 context_vram 查找）
            default_vram = float(m.get("vram_gb", 0))
            context_vram_map = m.get("context_vram", {}) or {}
            specified_ctx = (context_overrides or {}).get(mid)
            ctx_note = ""
            if specified_ctx and str(specified_ctx) in context_vram_map:
                vram = float(context_vram_map[str(specified_ctx)])
                ctx_note = "（%dK context）" % (specified_ctx // 1024)
            elif specified_ctx and specified_ctx in context_vram_map:
                vram = float(context_vram_map[specified_ctx])
                ctx_note = "（%dK context）" % (specified_ctx // 1024)
            else:
                vram = default_vram
            excl = bool(m.get("exclusive", False))
            loaded = mid in loaded_set
            if loaded:
                decision, need_free, gap = "ok", 0, 0
                note = "已加载（利用缓存）"
            else:
                needed = int(vram * 1024 + noise_mb + unreleasable_mb)
                if needed <= safe_ceiling_mb:
                    decision, need_free, gap = "ok", 0, 0
                    note = "可直接加载（不触发释放）"
                else:
                    gap0 = needed - safe_ceiling_mb
                    if releasable_mb >= gap0:
                        decision = "free_L2" if src_key == "comfyui" else "free_L1"
                        need_free = round(gap0 / 1024, 1)
                        gap = 0
                        note = "释放 %s GB（%s）后可加载" % (round(gap0 / 1024, 1),
                                                       "ComfyUI /free" if src_key == "comfyui" else "Ollama 停模型")
                    else:
                        decision = "reject"
                        need_free = round(gap0 / 1024, 1)
                        gap = round((gap0 - releasable_mb) / 1024, 1)
                        note = "差 %s GB，连释放都不够" % gap
            # 预计生成时间（从历史统计读取，无统计则按模型大小估算）
            gs = gen_stats.get(mid, {})
            avg_sec = gs.get("avg_seconds")
            if avg_sec:
                est_text = "基于 %d 次历史生成，平均约 %s" % (
                    gs.get("count", 0),
                    ("%d分%d秒" % (avg_sec // 60, avg_sec % 60)) if avg_sec >= 60 else ("%d秒" % avg_sec))
            else:
                est_sec = int(vram * 30)  # 粗略估算：每GB约30秒
                est_text = "首次运行，估算约 %s" % (
                    ("%d分%d秒" % (est_sec // 60, est_sec % 60)) if est_sec >= 60 else ("%d秒" % est_sec))
            models.append({
                "source": src_key, "id": mid, "name": m.get("name", mid),
                "vram_gb": vram, "exclusive": excl, "loaded": loaded,
                "decision": decision, "need_free_gb": need_free, "gap_gb": gap,
                "note": note + ctx_note,
                "avg_seconds": avg_sec, "gen_count": gs.get("count", 0), "est_time_text": est_text,
                "context_vram": context_vram_map, "default_ctx": int(m.get("ctx", 0)),
                "specified_ctx": specified_ctx,
            })
    # 当前加载的模型列表（用于预演模式"释放清单"）
    loaded_models = []
    for mid in ol_loaded:
        rm = next((x for x in REGISTRY.get("ollama", {}).get("models", []) if x["id"] == mid), None)
        loaded_models.append({"source": "ollama", "id": mid,
                              "name": rm.get("name", mid) if rm else mid,
                              "vram_gb": rm.get("vram_gb", 0) if rm else 0,
                              "exclusive": bool(rm.get("exclusive", False)) if rm else False})
    for mid in cf_loaded:
        rm = next((x for x in REGISTRY.get("comfyui", {}).get("models", []) if x["id"] == mid), None)
        loaded_models.append({"source": "comfyui", "id": mid,
                              "name": rm.get("name", mid) if rm else mid,
                              "vram_gb": rm.get("vram_gb", 0) if rm else 0,
                              "exclusive": bool(rm.get("exclusive", False)) if rm else False})
    # 按显存从大到小排序（释放时优先释放大的）
    loaded_models.sort(key=lambda x: x.get("vram_gb", 0), reverse=True)

    return {
        "ok": True,
        "total_gb": round(total_mb / 1024, 1),
        "noise_gb": round(noise_mb / 1024, 1),
        "reserve_gb": round(reserve_mb / 1024, 1),
        "safe_ceiling_gb": round(safe_ceiling_mb / 1024, 1),
        "used_gb": round(gpu.get("used_mb", 0) / 1024, 1) if gpu.get("ok") else None,
        "unreleasable_gb": round(unreleasable_mb / 1024, 1),
        "releasable_gb": round(releasable_mb / 1024, 1),
        "avail_gb": round(max(0, safe_ceiling_mb - noise_mb - unreleasable_mb) / 1024, 1),
        "models": models,
        "loaded_models": loaded_models,
        "ts": int(time.time()),
    }



# === Step 10.3 模型扫描器（蓝图§10.3：扫描实际模型 vs registry 比对，提示新模型/缺失模型） ===
# ComfyUI 登记模型 → 实际文件关键词映射（用于 known/missing 判定）
COMFY_FILE_MAP = {
    "SDXL": ["sd_xl_base", "sdxl"],
    "Flux-Q5": ["flux1-dev", "flux1"],
    "Music3": ["minimax_music3", "music3"],
    "Wan2.2-TI2V": ["wan2.2_ti2v", "wan2.2"],
}
# ComfyUI 主模型目录（checkpoints/unet/diffusion_models 是可登记模型；vae/clip/text_encoders 是配套，不单独登记）
_COMFY_SCAN_DIRS = ["checkpoints", "unet", "diffusion_models"]


def _comfy_model_files():
    """扫描 ComfyUI 容器模型目录，返回 {类别: [模型文件名]}（只读，不落盘）。"""
    out = {}
    for d in _COMFY_SCAN_DIRS:
        rc, ls = run_args(["docker", "exec", "comfyui", "sh", "-c", "ls /workspace/models/%s 2>/dev/null" % d], 10)
        if rc != 0:
            continue
        files = [x.strip() for x in ls.splitlines() if x.strip() and not x.startswith("total")]
        files = [f for f in files if f.lower().endswith((".safetensors", ".gguf", ".ckpt", ".bin"))]
        if files:
            out[d] = files
    return out


def _guess_family(fname):
    """按文件名粗判家族：video/music/image。"""
    fl = fname.lower()
    if any(k in fl for k in ("ltx", "hunyuan", "wan2", "wan_", "wav2lip", "videogen")):
        return "video"
    if any(k in fl for k in ("minimax_music", "ace_step", "music", "dav", "suno")):
        return "music"
    return "image"


def _scan_docker_dir(t):
    """扫描容器内模型目录（配置驱动）：docker exec {container} ls {base}/{dir}。"""
    container = t.get("container", t.get("source"))
    base = t.get("base", "/")
    files_by_dir = {}
    for d in t.get("dirs", []):
        rc, ls = run_args(["docker", "exec", container, "sh", "-c", "ls %s/%s 2>/dev/null" % (base, d)], 10)
        if rc != 0:
            continue
        files = [x.strip() for x in ls.splitlines() if x.strip() and not x.startswith("total")]
        files = [f for f in files if f.lower().endswith((".safetensors", ".gguf", ".ckpt", ".bin"))]
        if files:
            files_by_dir[d] = files
    return files_by_dir


def _scan_api(t):
    """HTTP API 拉模型列表（如 ollama /api/tags），返回模型名列表。"""
    try:
        with urllib.request.urlopen(t.get("url", ""), timeout=8) as r:
            d = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in d.get("models", []) if m.get("name")]
    except Exception:
        return []


def model_scan():
    """蓝图§10.3 模型扫描器（配置驱动）：从 registry.scanner.targets 读取扫描目标。
    支持 docker_dir（容器内目录扫描）+ api（HTTP 拉模型列表）。
    **容器名 / 目录 / API / 关键词映射全在 registry.scanner 配置**：ComfyUI 或 Ollama 装到别处，
    或要扫描其他容器（fooocus 等）→ 只改 registry，不碰代码。"""
    targets = REGISTRY.get("scanner", {}).get("targets", [])
    sources = {}
    for t in targets:
        if not t.get("enabled", True):
            continue
        source = t.get("source", "?")
        ttype = t.get("type", "docker_dir")
        registered = {m["id"] for m in REGISTRY.get(source, {}).get("models", [])}
        actual, files_by_dir = [], {}
        if ttype == "api":
            actual = _scan_api(t)
        else:
            files_by_dir = _scan_docker_dir(t)
            actual = [f for lst in files_by_dir.values() for f in lst]
        actual = sorted(set(actual))
        # known：registered 关键词命中 actual（COMFY_FILE_MAP 默认 + 每 target 可覆盖 model_keywords）
        kws = t.get("model_keywords", {})
        known = set()
        missing = []
        for rid in sorted(registered):
            rkw = kws.get(rid) or COMFY_FILE_MAP.get(rid) or [rid.lower()]
            hit = [f for f in actual if any(k in f.lower() for k in rkw)]
            if hit:
                known.update(hit)
            else:
                missing.append(rid)
        new_files = [f for f in actual if f not in known]
        default_cat = t.get("default_category", "")
        new_meta = [{"file": f,
                     # 文件名关键词识别（video/music）优先；纯 image 用 default_category 兜底
                     "category": (_guess_family(f) if _guess_family(f) != "image" else (default_cat or "image")),
                     "dir": next((d for d, lst in files_by_dir.items() if f in lst), "api")}
                    for f in new_files]
        sources[source] = {
            "type": ttype,
            "registered": sorted(registered),
            "actual": actual,
            "known": sorted(known),
            "new": new_meta,
            "missing": missing,
        }
    return {"ok": True, "ts": int(time.time()), "sources": sources}


def scan_register(source, name, vram_gb=None, category="image"):
    """用户确认后把扫描到的新模型写入 registry（蓝图10.3 一键登记）。
    source 为 registry 顶层键（comfyui/ollama/fooocus…），动态适配。写前备份 registry.json，可回滚。"""
    global REGISTRY
    # 修复：未知 source 直接报错，不默认 comfyui（避免错误登记）
    if source not in REGISTRY:
        return {"ok": False, "error": "unknown source: " + source + "（请先在 registry.json 中添加该 source 配置）"}
    src = source
    if "models" not in REGISTRY.get(src, {}):
        return {"ok": False, "error": "source has no models list: " + source}
    models = REGISTRY.get(src, {}).get("models", [])
    # 修复：用 m.get("id") 避免 KeyError
    if any(m.get("id") == name for m in models):
        return {"ok": False, "error": "already registered: " + name}
    # 显存估算：ollama 用实际文件大小估算，其他按家族默认
    if vram_gb is None:
        if src == "ollama":
            vram_gb = _estimate_ollama_vram(name)
        else:
            vram_gb = {"video": 10.0, "music": 6.0, "image": 6.5, "llm": 8.0}.get(category, 6.5)
    # 补全 entry 字段（与 registry 现有模型结构一致）
    entry = {
        "id": name, "name": name, "vram_gb": float(vram_gb),
        "ctx": 8192 if category == "llm" else 0,
        "exclusive": category in ("video", "music"),
        "category": category,
        "full_name": name,
        "vendor": "手动登记",
        "release": "2026",
        "desc": "一键登记，显存为" + ("估算值" if src == "ollama" else "默认值") + "，待实测验证",
        "detail": "由扫描器发现并手动登记",
        "auto_registered": False,
        "vram_verified": False,
        "context_vram": {},
    }
    # 备份原 registry
    reg_path = os.path.join(BASE_DIR, "resources", "registry.json")
    bak = reg_path + ".bak_scan"
    try:
        shutil.copyfile(reg_path, bak)
    except Exception:
        pass
    models.append(entry)
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(REGISTRY, f, ensure_ascii=False, indent=2)
    # 回读生效
    REGISTRY = load_registry()
    log_event("scan_register", source=src, model=name, vram_gb=vram_gb, backup=bak)
    return {"ok": True, "registered": name, "vram_gb": vram_gb, "backup": bak, "source": src}


# === P0-3 自动扫描器（事件驱动+定时兜底：ollama 新模型自动登记，标记待验证）===
_last_ollama_tags = set()
_auto_scanner_running = False


def _estimate_ollama_vram(name):
    """估算 ollama 模型显存（P0-3 合并版：优先实际文件大小，失败回退模型名参数×量化系数）。
    用于自动登记的新模型初始值，后续需实测验证。"""
    # 方式1：优先用 /api/tags 实际文件大小 + 上下文/计算缓冲（更准确）
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        for m in d.get("models", []):
            if m.get("name") == name:
                return round(m.get("size", 0) / 1e9 + 0.8, 1)
    except Exception:
        pass
    # 方式2：回退到模型名参数×量化系数估算（ollama 未运行时的兜底）
    n = name.lower()
    import re
    m = re.search(r'(\d+\.?\d*)b', n)
    params_b = float(m.group(1)) if m else 7.0
    if 'q8' in n or 'f16' in n or 'fp16' in n:
        q = 1.0
    elif 'q4' in n or 'q5' in n or 'q6' in n:
        q = 0.55
    elif 'q3' in n or 'iq3' in n:
        q = 0.4
    else:
        q = 0.75
    return round(params_b * q + 1.0, 1)


def _auto_register_ollama_model(name):
    """自动登记新 ollama 模型（显存估算，标记 auto_registered + vram_verified=false）。"""
    global REGISTRY
    models = REGISTRY.setdefault("ollama", {}).setdefault("models", [])
    if any(m.get("id") == name for m in models):
        return False
    vram = _estimate_ollama_vram(name)
    entry = {
        "id": name, "name": name, "vram_gb": vram,
        "ctx": 8192, "exclusive": False, "category": "llm",
        "full_name": name, "vendor": "自动登记", "release": "2026",
        "desc": "自动扫描登记，显存为估算值，待实测验证",
        "detail": "由自动扫描器发现并登记",
        "auto_registered": True, "vram_verified": False,
        "context_vram": {},
    }
    models.append(entry)
    reg_path = os.path.join(BASE_DIR, "resources", "registry.json")
    try:
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(REGISTRY, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("auto_register_write_failed", model=name, error=e)
    log_event("auto_register", source="ollama", model=name, vram_gb=vram, note="自动登记，待验证")
    return True


def _auto_scanner_loop():
    """自动扫描器后台线程：每60s轮询ollama list，新模型自动登记；每5min完整扫描。
    检测两类新模型：(1) 基线之后新增的模型；(2) 已安装但 registry.json 中未登记的模型。"""
    global _last_ollama_tags, _auto_scanner_running
    _auto_scanner_running = True
    full_scan_counter = 0
    while _auto_scanner_running:
        try:
            current = ollama_tags()
            if current:
                # (1) 基线之后新增的模型
                if _last_ollama_tags:
                    new_models = current - _last_ollama_tags
                    for name in sorted(new_models):
                        try:
                            _auto_register_ollama_model(name)
                        except Exception as e:
                            log_error("auto_register_error", model=name, error=e)
                # (2) 已安装但 registry.json 中未登记的模型（启动时批量补登记）
                registered = {m.get("id") for m in REGISTRY.get("ollama", {}).get("models", [])}
                unregistered = current - registered
                if unregistered:
                    log_event("auto_scanner_unregistered", count=len(unregistered),
                              models=",".join(sorted(unregistered))[:200])
                    for name in sorted(unregistered):
                        try:
                            _auto_register_ollama_model(name)
                        except Exception as e:
                            log_error("auto_register_error", model=name, error=e)
                _last_ollama_tags = current
            full_scan_counter += 1
            if full_scan_counter >= 5:
                full_scan_counter = 0
                try:
                    result = model_scan()
                    new_count = sum(len(s.get("new", [])) for s in result.get("sources", {}).values())
                    if new_count > 0:
                        log_event("auto_scan_full", new_found=new_count, note="完整扫描发现新文件，待用户确认")
                except Exception as e:
                    log_error("auto_scan_full_error", error=e)
        except Exception as e:
            log_error("auto_scanner_loop_error", error=e)
        time.sleep(60)


def start_auto_scanner():
    """启动自动扫描器后台线程（daemon）。"""
    global _last_ollama_tags
    _last_ollama_tags = ollama_tags()
    t = threading.Thread(target=_auto_scanner_loop, daemon=True, name="auto-scanner")
    t.start()
    log_event("auto_scanner_start", interval_s=60, baseline_models=len(_last_ollama_tags))


# === Step 8 任务队列（蓝图§9：16G 单卡串行化；提交→排队→预检→释放→加载→生成→完成） ===
_QUEUE_CLIENT_ID = str(uuid.uuid4())
_tasks = {}            # id -> task
_task_queue = deque()  # 排队 id（FIFO 串行）
_task_lock = threading.Lock()
_worker_alive = False


def _load_workflow(workflow_name):
    """读取工作流模板（vram-console/workflows/ 下），返回 dict；失败返回 None。
    utf-8-sig 兼容 Windows PowerShell 导出产生的 BOM。"""
    p = os.path.join(BASE_DIR, "workflows", workflow_name)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def _apply_params(wf, params):
    """按 input 名匹配替换模板参数（不硬编码节点号，兼容 Wan2.2/Flux/Music3 等任意模板）：
    - prompt → 首个含 text 的编码节点（正向；后续负向 text 保持原样）
    - seed → 所有含 seed 的节点（KSampler / 文本编码）
    - width/height → 含 width/height 的节点（EmptyLatentImage / 视频 latent）
    - filename_prefix → SaveImage/SaveAudio/SaveVideo 等保存节点"""
    wf = json.loads(json.dumps(wf))  # 深拷贝
    prompt_done = False
    for node in wf.values():
        ins = node.get("inputs")
        cls = node.get("class_type", "")
        if not isinstance(ins, dict):
            continue
        if "prompt" in params and not prompt_done:
            if "text" in ins:      # CLIPTextEncode 等（正向）
                ins["text"] = params["prompt"]
                prompt_done = True
            elif "caption" in ins:  # MiniMaxMusic3TextEncode 等（音乐）
                ins["caption"] = params["prompt"]
                prompt_done = True
        if "seed" in params and "seed" in ins:
            ins["seed"] = int(params["seed"])
        if "width" in params and "width" in ins:
            ins["width"] = int(params["width"])
        if "height" in params and "height" in ins:
            ins["height"] = int(params["height"])
        if "filename_prefix" in params and "filename_prefix" in ins:
            ins["filename_prefix"] = params["filename_prefix"]
    return wf


# === 生成时间统计（预演模式"预计时间"用，按模型记录历史生成耗时）===
_GEN_STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "generation_stats.json")


def _load_gen_stats():
    """读取生成时间统计 {model_id: {count, total_seconds, avg_seconds}}。"""
    try:
        with open(_GEN_STATS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_gen_stats(stats):
    """保存生成时间统计。"""
    try:
        os.makedirs(os.path.dirname(_GEN_STATS_PATH), exist_ok=True)
        with open(_GEN_STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("gen_stats_save_error", error=e)


def _update_gen_stats(model_id, seconds):
    """任务完成后更新该模型的生成时间统计。"""
    if not model_id or seconds <= 0 or seconds > 3600:  # 超过1小时的异常值不统计
        return
    stats = _load_gen_stats()
    s = stats.get(model_id, {"count": 0, "total_seconds": 0, "avg_seconds": 0})
    s["count"] += 1
    s["total_seconds"] = round(s["total_seconds"] + seconds, 1)
    s["avg_seconds"] = round(s["total_seconds"] / s["count"], 1)
    stats[model_id] = s
    _save_gen_stats(stats)


def queue_enqueue(model, params):
    """提交任务入队。model=registry comfyui 模型 id；params={prompt,seed,width,height,...}"""
    global _worker_alive
    m = next((x for x in REGISTRY.get("comfyui", {}).get("models", []) if x["id"] == model), None)
    if not m:
        return {"ok": False, "error": "unknown model: " + model}
    wf_name = m.get("workflow")
    if not wf_name or not _load_workflow(wf_name):
        return {"ok": False, "error": "工作流模板缺失: %s（需先在 ComfyUI 前端导出到 vram-console/workflows/）" % wf_name}
    tid = uuid.uuid4().hex[:10]
    task = {
        "id": tid, "model": model, "workflow": wf_name,
        "params": {k: v for k, v in (params or {}).items()},
        "status": "queued", "progress": "", "prompt_id": None,
        "created": int(time.time()), "started": None, "ended": None, "error": "",
        "result": None,
    }
    with _task_lock:
        _tasks[tid] = task
        _task_queue.append(tid)
    if not _worker_alive:
        _worker_alive = True
        threading.Thread(target=_queue_worker, daemon=True).start()
    log_event("queue_enqueue", task=tid, model=model, workflow=wf_name)
    return {"ok": True, "task": task}


def _queue_submit_comfy(wf):
    """POST ComfyUI /prompt 提交工作流，返回 prompt_id / 错误。"""
    payload = {"prompt": wf, "client_id": _QUEUE_CLIENT_ID}
    try:
        req = urllib.request.Request("http://127.0.0.1:8188/prompt",
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("prompt_id"), None
    except Exception as e:
        return None, str(e)


def _queue_wait(prompt_id, task, timeout=3600):
    """轮询 /history/{prompt_id} 直到 success/error，回填进度。"""
    url = "http://127.0.0.1:8188/history/%s" % prompt_id
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                h = json.loads(r.read().decode("utf-8"))
            if prompt_id in h:
                st = h[prompt_id].get("status", {})
                s = st.get("status_str")
                if s == "success":
                    task["result"] = {"outputs": list((h[prompt_id].get("outputs") or {}).keys())}
                    return "done"
                if s == "error":
                    task["error"] = "comfy_error: " + json.dumps(st.get("messages", [])[-1:] if st.get("messages") else {})
                    return "failed"
        except Exception:
            pass
        time.sleep(3)
    return "failed"


def _run_task(task):
    """执行单个任务：预检 → 释放 → 提交 → 等待完成。"""
    try:
        # 预检（预算引擎决策）
        task["status"] = "precheck"
        m = next((x for x in REGISTRY.get("comfyui", {}).get("models", []) if x["id"] == task["model"]), None)
        if m:
            dec = None
            for bm in budget_engine().get("models", []):
                if bm["id"] == task["model"]:
                    dec = bm
                    break
            if dec and dec["decision"] == "reject":
                task["status"] = "failed"
                task["error"] = "预检拒绝：%s" % dec["note"]
                return
            if dec and dec["decision"].startswith("free"):
                task["status"] = "freeing"
                task["progress"] = "释放 L1/L2 显存…"
                gpu_guard_evict()   # L2 /free（若受管模型占用）
                time.sleep(2)
        # 加载模板并参数化
        wf = _load_workflow(task["workflow"])
        if not wf:
            task["status"] = "failed"
            task["error"] = "模板读取失败"
            return
        wf = _apply_params(wf, task["params"])
        # 提交
        task["status"] = "running"
        task["started"] = int(time.time())
        pid, err = _queue_submit_comfy(wf)
        if not pid:
            task["status"] = "failed"
            task["error"] = "ComfyUI 提交失败: " + (err or "")
            task["ended"] = int(time.time())
            return
        task["prompt_id"] = pid
        task["progress"] = "已提交，等待执行…"
        # 等待完成
        rc = _queue_wait(pid, task)
        if task.get("cancel_requested"):
            task["status"] = "canceled"
        else:
            task["status"] = "done" if rc == "done" else "failed"
    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
    finally:
        task["ended"] = int(time.time())
        # 更新生成时间统计（仅成功完成的任务，用于预演模式"预计时间"）
        if task["status"] == "done" and task.get("started"):
            elapsed = task["ended"] - task["started"]
            _update_gen_stats(task["model"], elapsed)
        log_event("queue_finish", task=task["id"], model=task["model"], status=task["status"],
                  err=task["error"][-200:] if task["error"] else "")


def _queue_worker():
    """串行 worker：取队首 → 执行 → 下一个；队列空时休眠 2s。"""
    global _worker_alive
    while True:
        with _task_lock:
            if not _task_queue:
                _worker_alive = False
                return
            tid = _task_queue.popleft()
        task = _tasks.get(tid)
        if task:
            _run_task(task)


def queue_snapshot():
    """队列观察：全部任务（含历史）+ 当前 worker 状态。"""
    with _task_lock:
        tasks = [dict(t) for t in _tasks.values()]
        queue = list(_task_queue)
    tasks.sort(key=lambda t: t.get("created", 0), reverse=True)
    return {"ok": True, "queue": queue, "tasks": tasks,
            "worker_alive": _worker_alive, "client_id": _QUEUE_CLIENT_ID}


def queue_cancel(tid):
    """取消排队中任务（运行中无法中断 ComfyUI，标记请求取消，完成后置 canceled）。"""
    with _task_lock:
        task = _tasks.get(tid)
        if not task:
            return {"ok": False, "error": "task not found"}
        if task["status"] == "queued":
            try:
                _task_queue.remove(tid)
            except ValueError:
                pass
            task["status"] = "canceled"
            task["ended"] = int(time.time())
            log_event("queue_cancel", task=tid)
            return {"ok": True, "task": task}
        if task["status"] in ("precheck", "freeing", "running"):
            task["cancel_requested"] = True
            return {"ok": True, "note": "运行中，完成/失败后置 canceled", "task": task}
        return {"ok": False, "error": "已结束的任务无法取消"}


def scene_switch(scene):
    start_time = time.time()
    results = []
    gpu_before = gpu_status()
    log_event("scene_switch_start", scene=scene, vram_free_before=gpu_before.get("free_mb"))
    # M1 铁律：切换场景前必须先释放显存到 <4G，防止打满死机
    gpu = gpu_status()
    if gpu.get("ok") and gpu.get("free_mb", 99999) < 4096:
        log_event("vram_pre_release", reason="free<4096MB", free_mb=gpu.get("free_mb"))
        results.append(("pre-release VRAM (<4G detected, gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
    if scene == "dialogue":
        results.append(("stop fooocus", docker_action("fooocus", "stop")))
        results.append(("stop comfyui (回对话态停文生图容器, 释放 WSL RAM)", docker_action("comfyui", "stop")))
    elif scene == "comfy":
        results.append(("stop ollama models (free VRAM for image gen)", ollama_stop_all()))
        results.append(("start comfyui", docker_action("comfyui", "start")))
        results.append(("stop fooocus", docker_action("fooocus", "stop")))
        results.append(("release VRAM (gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
        ok, w = wait_ready(8188)
        results.append(("wait comfyui ready (:8188)", (0 if ok else -1, "waited {}s".format(w))))
    elif scene == "h3":
        # 视频场景（原 MiniMax H3，2026-08-28 已删模型，现可用 Wan2.2）：走 ComfyUI，独占全卡，需桌面程序尽量关
        results.append(("stop ollama models (H3 needs full VRAM)", ollama_stop_all()))
        results.append(("start comfyui", docker_action("comfyui", "start")))
        results.append(("stop fooocus (防叠加)", docker_action("fooocus", "stop")))
        results.append(("release VRAM (gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
        ok, w = wait_ready(8188)
        results.append(("wait comfyui ready (:8188)", (0 if ok else -1, "waited {}s".format(w))))
    elif scene == "fooocus":
        results.append(("stop ollama models (free VRAM for Flux)", ollama_stop_all()))
        results.append(("start fooocus", docker_action("fooocus", "start")))
        results.append(("stop comfyui (防 SDXL 驻留叠加)", docker_action("comfyui", "stop")))
        results.append(("release VRAM (gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
        ok, w = wait_ready(7865)
        results.append(("wait fooocus ready (:7865)", (0 if ok else -1, "waited {}s".format(w))))
    elif scene == "music":
        # MiniMax Music 3 音乐生成: 走 ComfyUI, 文本编码器巨大需独占显存
        results.append(("stop ollama models (Music3 needs full VRAM)", ollama_stop_all()))
        results.append(("start comfyui", docker_action("comfyui", "start")))
        results.append(("stop fooocus", docker_action("fooocus", "stop")))
        results.append(("release VRAM (gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
        ok, w = wait_ready(8188)
        results.append(("wait comfyui ready (:8188)", (0 if ok else -1, "waited {}s".format(w))))
    elif scene == "game":
        results.append(("stop comfyui", docker_action("comfyui", "stop")))
        results.append(("stop fooocus", docker_action("fooocus", "stop")))
        results.append(("release for game (game-on.ps1)", run_ps1(GAME_ON_PS1)))
    else:
        log_error("scene_switch_unknown", scene=scene)
        return {"ok": False, "error": "unknown scene: " + scene}
    LAST_SCENE["scene"] = scene
    duration_ms = int((time.time() - start_time) * 1000)
    gpu_after = gpu_status()
    # 关键步骤检查：启动容器/等待就绪/预释放显存 失败则整体失败
    # 非关键步骤（stop容器/stop模型/可选释放）失败不影响整体成功
    CRITICAL_PREFIXES = ("start ", "wait ", "pre-release ")
    failed_critical = []
    for name, (rc, out) in results:
        if any(name.startswith(p) for p in CRITICAL_PREFIXES) and rc != 0:
            failed_critical.append(name)
    overall_ok = len(failed_critical) == 0
    log_event("scene_switch_done", scene=scene, duration_ms=duration_ms,
              vram_free_after=gpu_after.get("free_mb"), actions_count=len(results),
              ok=overall_ok, failed_critical=failed_critical)
    return {
        "ok": overall_ok,
        "scene": scene,
        "error": "关键步骤失败: " + ", ".join(failed_critical) if failed_critical else None,
        "actions": [
            {"step": name, "rc": rc, "output": out[-300:]} for name, (rc, out) in results
        ]
    }


def health_check():
    """健康检查：各服务连通性 + 显存状态"""
    result = {"ok": True, "ts": time.time(), "services": {}}
    # GPU
    gpu = gpu_status()
    result["services"]["gpu"] = {"ok": gpu.get("ok", False), "free_mb": gpu.get("free_mb"), "total_mb": gpu.get("total_mb")}
    if not gpu.get("ok"):
        result["ok"] = False
    # Ollama
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as r:
            ollama_ok = r.status == 200
    except Exception:
        ollama_ok = False
    result["services"]["ollama"] = {"ok": ollama_ok, "port": 11434}
    if not ollama_ok:
        result["ok"] = False
    # ComfyUI
    try:
        req = urllib.request.Request("http://127.0.0.1:8188/system_stats")
        with urllib.request.urlopen(req, timeout=5) as r:
            comfy_ok = r.status == 200
    except Exception:
        comfy_ok = False
    result["services"]["comfyui"] = {"ok": comfy_ok, "port": 8188}
    # 显存阈值警告（不影响 ok）
    if gpu.get("ok") and gpu.get("free_mb", 99999) < 2048:
        result["vram_warning"] = "free VRAM < 2GB"
    return result


def load_model_api(name, ctx, keep="30m"):
    """通过 API 加载模型(keep_alive 默认 30m, 不阻塞太久)"""
    import urllib.request
    body = json.dumps({"model": name, "prompt": "hi", "stream": False, "keep_alive": keep,
                       "options": {"num_ctx": ctx, "num_predict": 1}}).encode()
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return 0, "loaded (ctx={})".format(ctx)
    except Exception as e:
        return -1, str(e)


def ollama_stop(names):
    """逐个 stop（容器化后用 docker exec 调用 ollama CLI）"""
    bad = []
    outs = []
    for n in names:
        ok, checked = _safe_model_name(n)
        if not ok:
            bad.append(n)
            outs.append("{}:SKIP({})".format(n, checked))
            continue
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "stop", checked], 60)
        outs.append("{}:rc{}".format(checked, rc))
        if rc != 0:
            bad.append(checked)
    return (0 if not bad else 1), " | ".join(outs) + ("" if not bad else "  FAILED: " + ",".join(bad))


def combo_switch(combo):
    """对话态模型组合（从 registry.json 配置驱动）
    互斥规则: 27B 独占, 换入前必须先 stop 其他大模型
    模型未安装时给出友好提示并跳过，不报错。"""
    results = []
    installed = ollama_tags()  # 动态获取已安装模型

    # 从注册表获取 combo 配置和模型元数据
    combos = REGISTRY.get("ollama", {}).get("combos", {})
    models_meta = {m["id"]: m for m in REGISTRY.get("ollama", {}).get("models", [])}

    if combo not in combos:
        return {"ok": False, "error": "unknown combo: " + combo}

    cfg = combos[combo]
    to_load = cfg.get("load", [])
    to_stop = cfg.get("stop", [])

    def _load_if_installed(name):
        if name not in installed:
            return -1, "SKIP: model not installed (ollama pull {})".format(name)
        ctx = models_meta.get(name, {}).get("ctx", 16384)
        return load_model_api(name, ctx)

    def _stop_if_installed(names):
        if names == "all":
            return ollama_stop_all()
        to_stop_list = [n for n in names if n in installed]
        if not to_stop_list:
            return 0, "all already stopped/not installed"
        return ollama_stop(to_stop_list)

    # 先 stop 再 load（避免显存叠加）
    if to_stop:
        results.append(("stop conflicting models", _stop_if_installed(to_stop)))
    for model_id in to_load:
        ctx = models_meta.get(model_id, {}).get("ctx", 16384)
        results.append(("load {} @{}".format(model_id, ctx), _load_if_installed(model_id)))

    log_event("combo_switch", combo=combo, load_count=len(to_load), stop_count=len(to_stop) if isinstance(to_stop, list) else 0)
    return {"ok": True, "combo": combo, "actions": [
        {"step": name, "rc": rc, "output": out[-300:]} for name, (rc, out) in results
    ]}


def service_action(name, action):
    if name not in ("comfyui", "fooocus"):
        return {"ok": False, "error": "unsupported service: " + name}
    rc, out = docker_action(name, action)
    return {"ok": rc == 0, "name": name, "action": action, "rc": rc, "output": out[-300:]}


def model_action(name, action):
    """模型加载/停止，name 做格式校验，命令用 shell=False 参数数组防注入。
    容器化后用 docker exec 调用 ollama CLI。"""
    if action not in ("load", "stop"):
        return {"ok": False, "error": "unknown action: " + str(action)}
    ok, checked = _safe_model_name(name)
    if not ok:
        return {"ok": False, "error": checked}
    if action == "load":
        # B2 修复：显存快满时拒绝加载，只告警不动作（防止 OOM 死机）
        gpu = gpu_status()
        if gpu.get("ok") and gpu.get("free_mb", 99999) < 4096:
            log_event("model_load_rejected", model=checked, reason="free_vram<4GB", free_mb=gpu.get("free_mb"))
            return {"ok": False, "name": checked, "action": action,
                    "error": "显存不足（空闲 %.1fGB < 4GB），已拒绝加载以防止 OOM。请先释放显存或切换场景。" % (gpu.get("free_mb", 0)/1024)}
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "run", checked, "--keepalive", "30s"], 300)
    else:  # stop
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "stop", checked], 30)
    return {"ok": rc == 0, "name": checked, "action": action, "rc": rc, "output": out[-300:]}


# === 模型登记台自动同步（2026-08-28，主公：专业用户会自己更新模型，登记台应自动跟上） ===
# registry.json 是元数据种子；运行时用实际环境（ollama /api/tags、comfyui 模型文件）对齐：
# 新装模型自动登记（auto=True），已删模型标 installed=False（保留元数据供重装恢复）。
# ComfyUI 主模型目录（与扫描器一致：checkpoints/unet/diffusion_models 是可登记模型；vae/clip/text_encoders 是配套，不单独显示/登记）
_COMFY_MODEL_DIRS = ["checkpoints", "unet", "diffusion_models"]


def _sync_ollama_models():
    """自动同步 ollama 模型：registry 元数据 × /api/tags 实际安装。"""
    tags = ollama_tags()
    reg_models = REGISTRY.get("ollama", {}).get("models", [])
    reg_by_id = {m["id"]: m for m in reg_models}
    out = []
    for name in sorted(tags):
        if name in reg_by_id:
            m = dict(reg_by_id[name])
            m["installed"] = True
        else:
            m = {"id": name, "name": name, "vram_gb": _estimate_ollama_vram(name),
                 "ctx": 8192, "exclusive": False, "category": "llm", "combo": None,
                 "installed": True, "auto": True}
        out.append(m)
    for m in reg_models:
        if m["id"] not in tags:
            mm = dict(m)
            mm["installed"] = False
            out.append(mm)
    return out


def _comfy_installed_files():
    """扫描 ComfyUI 模型目录，返回文件名集合。"""
    files = set()
    for d in _COMFY_MODEL_DIRS:
        rc, out = run_args(["docker", "exec", "comfyui", "ls", "/workspace/models/" + d], 15)
        if rc == 0:
            for f in out.splitlines():
                f = f.strip()
                if f and not f.startswith("."):
                    files.add(f)
    return files


def _match_comfy_model(file_lower, reg_models):
    """文件关键词 → registry 逻辑模型 id；无匹配返回 None。"""
    for m in reg_models:
        mid = m["id"]
        if mid == "SDXL" and ("sd_xl" in file_lower or "sdxl" in file_lower):
            return mid
        if mid == "Flux-Q5" and "flux" in file_lower:
            return mid
        if mid == "Music3" and ("music3" in file_lower or "music_3" in file_lower):
            return mid
        if mid == "Wan2.2-TI2V" and ("wan2.2" in file_lower or "ti2v" in file_lower):
            return mid
    return None


def _file_like_id(mid):
    """判断登记 id 是否为文件名型（直接对应磁盘文件，如 LTX-2.5-....gguf），区别于逻辑模型名（SDXL/Flux-Q5…）。"""
    return str(mid).lower().endswith((".safetensors", ".gguf", ".ckpt", ".sft", ".bin"))


def _sync_comfyui_models():
    """自动同步 comfyui 模型：registry 逻辑模型 × 实际模型文件。"""
    reg_models = REGISTRY.get("comfyui", {}).get("models", [])
    files = _comfy_installed_files()
    out = []
    for m in reg_models:
        mm = dict(m)
        mm["installed"] = any(_match_comfy_model(f.lower(), reg_models) == m["id"] for f in files)
        out.append(mm)
    # 已匹配 = 逻辑关键词命中 ∪ 文件名型登记直接对应磁盘文件
    reg_files = {m["id"] for m in reg_models if _file_like_id(m["id"])}
    matched = {f for f in files if _match_comfy_model(f.lower(), reg_models) or f in reg_files}
    for f in sorted(files - matched):
        out.append({"id": "auto:" + f, "name": f, "vram_gb": 0, "category": "unknown",
                    "exclusive": False, "installed": True, "auto": True, "file": f})
    return out


def registry_view():
    """模型登记台（Step 3）：registry 元数据 × 实际环境自动同步。
    registry.json 是元数据种子；运行时用 /api/tags + 模型文件扫描对齐（自动登记/标记已删）。"""
    reg = REGISTRY
    return {
        "ok": True,
        "version": reg.get("version", ""),
        "last_updated": reg.get("last_updated", ""),
        "sync": True,
        "ollama_models": _sync_ollama_models(),
        "ollama_combos": reg.get("ollama", {}).get("combos", {}),
        "comfyui_models": _sync_comfyui_models(),
        "containers": reg.get("containers", []),
        "scenes": reg.get("scenes", {}),
        "system": reg.get("system", {}),
        "gpu_guard": reg.get("gpu_guard", {}),
    }


def read_html():
    path = os.path.join(BASE_DIR, "index.html")
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return b"index.html not found"


def read_login_html():
    """读取登录页 HTML（login.html），不存在时返回内置最小登录页"""
    path = os.path.join(BASE_DIR, "login.html")
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        # 内置最小登录页（login.html 不存在时的兜底）
        return ("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GMae 登录</title>
<style>body{font-family:sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.box{background:#1e293b;padding:32px;border-radius:12px;width:320px}
h1{color:#0d9488;margin:0 0 24px;font-size:24px}
input{width:100%;padding:10px;margin:8px 0;border:1px solid #334155;border-radius:6px;background:#0f172a;color:#e2e8f0;box-sizing:border-box}
button{width:100%;padding:12px;background:#0d9488;color:#fff;border:none;border-radius:6px;cursor:pointer;margin-top:16px;font-size:16px}
button:hover{background:#0f766e}
.msg{margin-top:12px;font-size:14px;min-height:20px}
.err{color:#f87171}.ok{color:#4ade80}
a{color:#0d9488;text-decoration:none;cursor:pointer}
.tab{display:flex;margin-bottom:16px;border-bottom:1px solid #334155}
.tab div{padding:8px 16px;cursor:pointer;color:#94a3b8}
.tab div.active{color:#0d9488;border-bottom:2px solid #0d9488}
.hidden{display:none}
</style></head><body>
<div class="box">
<h1>GMae 调度中心</h1>
<div class="tab"><div class="active" onclick="showTab('login')">登录</div><div onclick="showTab('setup')">首次设置</div><div onclick="showTab('forgot')">忘记密码</div></div>
<div id="login">
<input id="login-email" placeholder="邮箱" type="email">
<input id="login-password" placeholder="密码" type="password">
<label style="font-size:14px;color:#94a3b8"><input type="checkbox" id="login-remember" style="width:auto;margin-right:6px">记住我 30 天</label>
<button onclick="doLogin()">登录</button>
</div>
<div id="setup" class="hidden">
<input id="setup-email" placeholder="管理员邮箱" type="email">
<input id="setup-password" placeholder="设置密码（至少6位）" type="password">
<input id="setup-password2" placeholder="确认密码" type="password">
<button onclick="doSetup()">创建管理员账户</button>
</div>
<div id="forgot" class="hidden">
<input id="forgot-email" placeholder="注册邮箱" type="email">
<button onclick="doForgot()">发送验证码</button>
<div id="reset-step" class="hidden" style="margin-top:16px">
<input id="reset-code" placeholder="6位验证码" maxlength="6">
<input id="reset-password" placeholder="新密码（至少6位）" type="password">
<button onclick="doReset()">重置密码</button>
</div>
</div>
<div class="msg" id="msg"></div>
</div>
<script>
function showTab(t){document.querySelectorAll('.tab div').forEach((e,i)=>e.classList.toggle('active',['login','setup','forgot'][i]===t));['login','setup','forgot'].forEach(x=>document.getElementById(x).classList.toggle('hidden',x!==t));document.getElementById('msg').textContent='';}
function msg(t,c){var e=document.getElementById('msg');e.textContent=t;e.className='msg '+(c||'');}
async function api(url,data){var r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})});return await r.json();}
async function doLogin(){var e=document.getElementById('login-email').value,p=document.getElementById('login-password').value,r=document.getElementById('login-remember').checked;if(!e||!p)return msg('请输入邮箱和密码','err');var d=await api('/api/auth/login',{email:e,password:p,remember:r});if(d.ok){msg('登录成功，正在跳转...','ok');setTimeout(()=>location.href='/',800);}else msg(d.error||'登录失败','err');}
async function doSetup(){var e=document.getElementById('setup-email').value,p=document.getElementById('setup-password').value,p2=document.getElementById('setup-password2').value;if(!e||!p)return msg('请输入邮箱和密码','err');if(p!==p2)return msg('两次密码不一致','err');var d=await api('/api/auth/setup',{email:e,password:p});if(d.ok){msg('创建成功，请登录','ok');showTab('login');}else msg(d.message||'创建失败','err');}
async function doForgot(){var e=document.getElementById('forgot-email').value;if(!e)return msg('请输入邮箱','err');var d=await api('/api/auth/forgot',{email:e});msg(d.message,d.ok?'ok':'err');if(d.ok)document.getElementById('reset-step').classList.remove('hidden');}
async function doReset(){var e=document.getElementById('forgot-email').value,c=document.getElementById('reset-code').value,p=document.getElementById('reset-password').value;var d=await api('/api/auth/reset',{email:e,code:c,password:p});if(d.ok){msg('密码重置成功，请登录','ok');showTab('login');}else msg(d.message||'重置失败','err');}
</script></body></html>""").encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _check_auth(self):
        """认证检查：Session Cookie（浏览器）优先，其次 API Token（脚本/自动化）。
        未设置管理员时所有请求放行（首次设置引导）。设置了管理员但未登录 → 401。"""
        # 未设置管理员：放行（首次设置引导）
        if not auth_mod.has_admin():
            return True
        # 1. Session Cookie 认证（浏览器）
        cookies = auth_mod.parse_cookie(self.headers.get("Cookie", ""))
        session_id = cookies.get(auth_mod.SESSION_COOKIE_NAME, "")
        if session_id and auth_mod.get_session(session_id):
            return True
        # 2. API Token 认证（脚本/自动化，向后兼容）
        if API_TOKEN:
            provided = self.headers.get("X-API-Key", "")
            if provided == API_TOKEN:
                return True
        self._json({"ok": False, "error": "unauthorized: please login first", "need_login": True}, 401)
        return False

    def _current_user(self):
        """获取当前登录用户邮箱，未登录返回 None"""
        cookies = auth_mod.parse_cookie(self.headers.get("Cookie", ""))
        session_id = cookies.get(auth_mod.SESSION_COOKIE_NAME, "")
        sess = auth_mod.get_session(session_id)
        return sess.get("user_email") if sess else None

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            # 未设置管理员或未登录 → 返回登录页；已登录 → 返回主应用
            if not auth_mod.has_admin() or not self._current_user():
                self._send(200, read_login_html(), "text/html")
            else:
                self._send(200, read_html(), "text/html")
        elif self.path == "/login":
            self._send(200, read_login_html(), "text/html")
        elif self.path == "/api/health":
            # 健康检查不需要认证，方便外部监控
            self._json(health_check())
        elif self.path == "/api/auth/status":
            # 认证状态不需要登录（登录页需要判断是否已设置管理员）
            self._json(auth_mod.auth_status())
        elif self.path == "/api/status":
            if not self._check_auth():
                return
            self._json(current_status())
        elif self.path == "/api/registry":
            if not self._check_auth():
                return
            self._json(registry_view())
        elif self.path == "/api/comfy_events":
            if not self._check_auth():
                return
            self._json(comfy_events())
        elif self.path == "/api/desktop_vram":
            if not self._check_auth():
                return
            self._json(desktop_vram_detail())
        elif self.path == "/api/desktop/helper/status":
            if not self._check_auth():
                return
            self._json(helper_status())
        elif self.path == "/api/budget":
            if not self._check_auth():
                return
            # P0-2: 支持 context_overrides（query string: ?context=model_id:ctx_size,model2:ctx2）
            context_overrides = None
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query) if "?" in self.path else {}
            # 注意：self.path 可能不包含 query string，用 self.command 中的 path
            # http.server 的 path 包含 query string
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if "context" in qs:
                context_overrides = {}
                for item in qs["context"][0].split(","):
                    if ":" in item:
                        mid, ctx = item.rsplit(":", 1)
                        try:
                            context_overrides[mid.strip()] = int(ctx.strip())
                        except ValueError:
                            pass
            self._json(budget_engine(context_overrides))
        elif self.path == "/api/scan":
            if not self._check_auth():
                return
            self._json(model_scan())
        elif self.path == "/api/queue":
            if not self._check_auth():
                return
            self._json(queue_snapshot())
        elif self.path == "/api/desktop/helper/status":
            if not self._check_auth():
                return
            self._json(helper_status())
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        # 认证相关 API 不需要登录（登录/注册/忘记密码）
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            data = {}

        if self.path == "/api/auth/setup":
            ok, msg = auth_mod.setup_admin(data.get("email", ""), data.get("password", ""))
            self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            return
        elif self.path == "/api/auth/login":
            ok, user = auth_mod.authenticate(data.get("email", ""), data.get("password", ""))
            if ok:
                session_id = auth_mod.create_session(user["email"], remember=data.get("remember", False))
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", "{}={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(
                    auth_mod.SESSION_COOKIE_NAME, session_id,
                    auth_mod.SESSION_REMEMBER_TTL if data.get("remember") else auth_mod.SESSION_DEFAULT_TTL))
                body = json.dumps({"ok": True, "message": "登录成功", "email": user["email"]}, ensure_ascii=False).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"ok": False, "error": "邮箱或密码不正确"}, 401)
            return
        elif self.path == "/api/auth/forgot":
            ok, msg = auth_mod.generate_reset_code(data.get("email", ""))
            self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            return
        elif self.path == "/api/auth/reset":
            ok, msg = auth_mod.reset_password(data.get("email", ""), data.get("code", ""), data.get("password", ""))
            self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            return

        # 以下 API 需要认证
        if not self._check_auth():
            return
        # 所有 POST 操作前失效 status 缓存，确保操作完成后前端拿到最新数据
        invalidate_status_cache()
        if self.path == "/api/scene":
            self._json(scene_switch(data.get("scene", "")))
        elif self.path == "/api/combo":
            self._json(combo_switch(data.get("combo", "")))
        elif self.path == "/api/free":
            self._json(comfy_free())
        elif self.path == "/api/guard":
            # action=kick → L2 强制驱逐单个进程（验明正身后 docker exec kill）
            # evict=true → 软驱逐（停 ollama/comfyui/fooocus）；否则只读检查
            if data.get("action") == "kick":
                self._json(gpu_guard_kick(data.get("pid", "")))
            else:
                self._json(gpu_guard_evict() if data.get("evict") else gpu_guard_check())
        elif self.path == "/api/qos/status":
            self._json(qos_status())
        elif self.path == "/api/qos/check":
            self._json(qos_check())
        elif self.path == "/api/qos/execute":
            self._json(qos_execute_suggestion(data.get("suggestion_id", "")))
        elif self.path == "/api/service":
            self._json(service_action(data.get("name", ""), data.get("action", "")))
        elif self.path == "/api/model":
            self._json(model_action(data.get("name", ""), data.get("action", "")))
        elif self.path == "/api/desktop/kill":
            self._json(desktop_kill(data.get("pid", "")))
        elif self.path == "/api/desktop/helper/start":
            self._json(helper_start())
        elif self.path == "/api/desktop/helper/stop":
            self._json(helper_stop())
        elif self.path == "/api/queue":
            self._json(queue_enqueue(data.get("model", ""), data.get("params", {})))
        elif self.path == "/api/queue/cancel":
            self._json(queue_cancel(data.get("id", "")))
        elif self.path == "/api/scan/register":
            self._json(scan_register(data.get("source", "comfyui"), data.get("name", ""),
                                     data.get("vram_gb"), data.get("category", "image")))
        elif self.path == "/api/auth/logout":
            cookies = auth_mod.parse_cookie(self.headers.get("Cookie", ""))
            session_id = cookies.get(auth_mod.SESSION_COOKIE_NAME, "")
            auth_mod.destroy_session(session_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "{}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0".format(auth_mod.SESSION_COOKIE_NAME))
            body = json.dumps({"ok": True, "message": "已登出"}, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        elif self.path == "/api/auth/change-password":
            email = self._current_user()
            ok, msg = auth_mod.change_password(email or "", data.get("old_password", ""), data.get("new_password", ""))
            self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            return
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        start_idle_reaper()   # 后台空闲回收线程（daemon，随 server 退出）
        start_comfy_ws()      # ComfyUI WebSocket 实时事件监听（daemon，断线自愈）
        start_qos()           # Step5 QoS 水位节拍线程（daemon，15s）
        start_auto_scanner()  # P0-3 自动扫描器（daemon，60s 轮询，新模型自动登记）
        auth_note = "session+token" if auth_mod.has_admin() else "setup-required"
        log_event("server_start", host=HOST, port=PORT, auth=auth_note, log_file=LOG_FILE,
                  admin_exists=auth_mod.has_admin(), smtp_configured=bool(auth_mod.SMTP_PASSWORD))
        if not auth_mod.has_admin():
            log_event("auth_setup_required", message="no admin account set - please visit / to setup first admin")
        server.serve_forever()
    except KeyboardInterrupt:
        log_event("server_stop", reason="keyboard_interrupt")
    except Exception as e:
        log_error("server_crash", error=e)
        raise

