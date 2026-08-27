#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Maestro-显存指挥家 调度中心 - 后端 (Python 标准库, 零依赖)
GET  /              前端页面
GET  /api/status    显存/模型/容器/场景 实时状态
GET  /api/health    健康检查（各服务连通性）
POST /api/scene     切换场景 {scene: dialogue|comfy|h3|fooocus|music|game}
POST /api/service   启停服务 {name: comfyui|fooocus, action: start|stop}
POST /api/model     模型加载/停止 {name, action: load|stop}
启动: python server.py   (默认端口 8787, 带结构化日志)
"""
import json
import os
import re
import subprocess
import time
import datetime
import logging
import urllib.request
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

PORT = int(os.environ.get("VRAM_CONSOLE_PORT", "8787"))
HOST = os.environ.get("VRAM_CONSOLE_HOST", "0.0.0.0")
# 可选 Token 认证：设置环境变量后，所有 POST 和 /api/status 需带 X-API-Key 请求头
API_TOKEN = os.environ.get("VRAM_CONSOLE_TOKEN", "")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
              if m.get("category") == "llm"] or ["qwen3.5:9b", "qwen3:0.6b", "qwen3.8:27b-rvn-q3km", "qwen3.8:27b-iq3xxs"]
LAST_SCENE = {"scene": None}  # 记录最近一次手动切换(区分 comfy/music/h3 共用容器)

log_event("registry_loaded", models_count=len(BIG_MODELS), container=OLLAMA_CONTAINER)

# Ollama 模型名安全格式：字母/数字/点/冒号/破折号/斜杠，禁止分号、管道、空格等 shell 元字符
_MODEL_NAME_RE = re.compile(r'^[A-Za-z0-9._:/\-]+$')


def _safe_model_name(name):
    """校验模型名是否安全，返回 (ok, name_or_error)"""
    if not name or not isinstance(name, str):
        return False, "empty model name"
    if len(name) > 128:
        return False, "model name too long"
    if not _MODEL_NAME_RE.match(name):
        return False, "invalid model name (only letters, digits, . : / - allowed)"
    return True, name


def run(cmd, timeout=30):
    """执行固定命令（shell=True），仅用于内部硬编码命令，不可传入用户输入"""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -2, str(e)


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
    return run('powershell -NoProfile -ExecutionPolicy Bypass -File "{}"'.format(path), timeout)


def gpu_status():
    rc, out = run("nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv,noheader,nounits", 10)
    if rc != 0:
        return {"ok": False, "error": out[:200]}
    parts = [int(x.strip()) for x in out.strip().split(",")]
    return {"ok": True, "total_mb": parts[0], "used_mb": parts[1], "free_mb": parts[2]}


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
    rc, out = run("docker ps --format {{.Names}}", 10)
    if rc != 0:
        return []
    return [x.strip() for x in out.splitlines() if x.strip()]


def infer_scene(containers):
    if "fooocus" in containers:
        return "fooocus"
    if "comfyui" in containers:
        return "comfy"
    return "dialogue"


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
        elif mid == "MiniMax-H3":
            keyword_map["h3"] = mid
            keyword_map["minimax_h3"] = mid
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
    # 结合实际显存判断模型是否可能还在显存中
    # ComfyUI 生成完成后会自动卸载大模型，所以需要验证
    gpu = gpu_status()
    likely_loaded = False
    if models and gpu.get("ok"):
        baseline_mb = 1536  # 系统底噪上限
        actual_comfy_mb = max(0, gpu.get("used_mb", 0) - baseline_mb)
        inferred_mb = total_vram * 1024
        # 如果实际占用超过推断显存的 40%，认为模型可能还在
        if actual_comfy_mb > inferred_mb * 0.4 and actual_comfy_mb > 2048:
            likely_loaded = True
            note = "inferred from last workflow (likely still in VRAM)"
        else:
            note = "last workflow used this model, but likely unloaded (VRAM freed)"
    return {
        "ok": True,
        "models": models,
        "total_vram_gb": round(total_vram, 1),
        "source_files": loaded_files,
        "note": note,
        "likely_loaded": likely_loaded,
    }


def current_status():
    gpu = gpu_status()
    ops = ollama_ps()
    names = docker_containers()
    comfy_models = comfy_loaded_models()
    scene = infer_scene(names)
    last = LAST_SCENE["scene"]
    if last:
        # LAST_SCENE = 最近一次手动切换，是权威状态；容器推断仅兜底。
        # 复用同一容器/无容器的场景按 LAST_SCENE 区分（comfy/music/h3 共用 comfyui；
        # game/dialogue 都是"无文生图容器"，只能靠 LAST_SCENE 区分）
        if last in ("comfy", "music", "h3") and "comfyui" in names:
            scene = last
        elif last == "fooocus" and "fooocus" in names:
            scene = last
        elif last == "game" and "comfyui" not in names and "fooocus" not in names:
            scene = last
        elif last == "dialogue" and scene == "dialogue":
            scene = last
    return {
        "gpu": gpu,
        "ollama": ops,
        "comfyui_models": comfy_models,
        "containers": {
            "comfyui": "comfyui" in names,
            "fooocus": "fooocus" in names,
            "all": sorted(names),
        },
        "scene": scene,
        "ts": int(time.time()),
    }


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
        # MiniMax H3 文生/图生视频：走 ComfyUI，独占全卡（同 Flux），需桌面程序尽量关
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
    log_event("scene_switch_done", scene=scene, duration_ms=duration_ms,
              vram_free_after=gpu_after.get("free_mb"), actions_count=len(results))
    return {"ok": True, "scene": scene, "actions": [
        {"step": name, "rc": rc, "output": out[-300:]} for name, (rc, out) in results
    ]}


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
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "run", checked, "--keepalive", "30s"], 300)
    else:  # stop
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "stop", checked], 30)
    return {"ok": rc == 0, "name": checked, "action": action, "rc": rc, "output": out[-300:]}


def read_html():
    path = os.path.join(BASE_DIR, "index.html")
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return b"index.html not found"


class Handler(BaseHTTPRequestHandler):
    def _check_auth(self):
        """Token 认证：设置了 VRAM_CONSOLE_TOKEN 时需匹配 X-API-Key 请求头"""
        if not API_TOKEN:
            return True
        provided = self.headers.get("X-API-Key", "")
        if provided == API_TOKEN:
            return True
        self._json({"ok": False, "error": "unauthorized: missing or invalid X-API-Key"}, 401)
        return False

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
            self._send(200, read_html(), "text/html")
        elif self.path == "/api/health":
            # 健康检查不需要认证，方便外部监控
            self._json(health_check())
        elif self.path == "/api/status":
            if not self._check_auth():
                return
            self._json(current_status())
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if not self._check_auth():
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._json({"ok": False, "error": "invalid JSON body"}, 400)
            return
        if self.path == "/api/scene":
            self._json(scene_switch(data.get("scene", "")))
        elif self.path == "/api/combo":
            self._json(combo_switch(data.get("combo", "")))
        elif self.path == "/api/service":
            self._json(service_action(data.get("name", ""), data.get("action", "")))
        elif self.path == "/api/model":
            self._json(model_action(data.get("name", ""), data.get("action", "")))
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        auth_note = "token" if API_TOKEN else "no-auth"
        log_event("server_start", host=HOST, port=PORT, auth=auth_note, log_file=LOG_FILE)
        if not API_TOKEN:
            log_event("security_warning", message="no API_TOKEN set - any device can control AI environment")
        server.serve_forever()
    except KeyboardInterrupt:
        log_event("server_stop", reason="keyboard_interrupt")
    except Exception as e:
        log_error("server_crash", error=e)
        raise
