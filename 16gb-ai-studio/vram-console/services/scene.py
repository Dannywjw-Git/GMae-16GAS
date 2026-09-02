#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 场景切换与模型同步模块（配置驱动版 v2.0）
- scene_switch: 配置驱动的场景切换（steps 在 registry.json 中定义）
- combo_switch: 对话态模型组合切换（修复返回值）
- 通用步骤执行器：pre_release_vram / ollama_stop_all / docker_start / docker_stop / vram_release / game_on / wait_ready
- 并发锁保护 + 显存预算预检 + 场景状态持久化
"""
import json
import os
import time
import threading
import urllib.request
from core.logger import log_event, log_error
from core.config import (REGISTRY, OLLAMA_CONTAINER, GPU_RELEASE_PS1, GAME_ON_PS1,
                         get_threshold_value)
from core.registry import registry
from core.utils import run_ps1, run_args, _safe_model_name
from gpu.monitor import gpu_status
from services.docker import docker_action, wait_ready
from services.ollama import ollama_stop_all, ollama_tags
from engine.scanner import _estimate_ollama_vram

# === 并发锁：场景切换互斥，防止并发执行导致容器状态混乱 ===
_scene_lock = threading.Lock()

# 当前场景状态 — 已迁移到 registry
registry.set("last_scene", {"scene": None})

# ComfyUI 主模型目录
_COMFY_MODEL_DIRS = ["checkpoints", "unet", "diffusion_models"]

# 场景状态持久化文件
_SCENE_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "scene_state.json")


def _load_last_scene():
    """从持久化文件加载上次场景（服务重启后恢复）"""
    try:
        if os.path.exists(_SCENE_STATE_FILE):
            with open(_SCENE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("scene")
    except Exception as e:
        log_error("scene_state_load_failed", error=e)
    return None


def _save_last_scene(scene: str):
    """持久化当前场景"""
    try:
        os.makedirs(os.path.dirname(_SCENE_STATE_FILE), exist_ok=True)
        with open(_SCENE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"scene": scene, "updated_at": time.time()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("scene_state_save_failed", error=e)


# 启动时恢复上次场景
_last = _load_last_scene()
if _last:
    registry.set("last_scene", {"scene": _last})


# ============================================================
# 通用步骤执行器
# ============================================================

def _step_pre_release_vram(step: dict, context: dict) -> tuple:
    """预释放显存：当 free_mb < threshold 时执行 gpu_release.ps1"""
    threshold = step.get("threshold_mb", 4096)
    gpu = gpu_status()
    if gpu.get("ok") and gpu.get("free_mb", 99999) < threshold:
        log_event("vram_pre_release", reason="free<%dMB" % threshold, free_mb=gpu.get("free_mb"))
        return run_ps1(GPU_RELEASE_PS1)
    return 0, "skipped: free_mb=%d >= %d" % (gpu.get("free_mb", 0), threshold)


def _step_ollama_stop_all(step: dict, context: dict) -> tuple:
    """停止所有 Ollama 模型"""
    return ollama_stop_all()


def _step_docker_start(step: dict, context: dict) -> tuple:
    """启动 Docker 容器"""
    target = step.get("target", "")
    rc, out = docker_action(target, "start")
    context["started_%s" % target] = (rc == 0)
    return rc, out


def _step_docker_stop(step: dict, context: dict) -> tuple:
    """停止 Docker 容器"""
    target = step.get("target", "")
    return docker_action(target, "stop")


def _step_vram_release(step: dict, context: dict) -> tuple:
    """释放显存（gpu_release.ps1）"""
    return run_ps1(GPU_RELEASE_PS1)


def _step_game_on(step: dict, context: dict) -> tuple:
    """游戏模式优化（game-on.ps1）"""
    return run_ps1(GAME_ON_PS1)


def _step_wait_ready(step: dict, context: dict) -> tuple:
    """等待端口就绪（仅当前置启动步骤成功时执行）"""
    port = step.get("port", 8188)
    timeout = step.get("timeout_s", 120)
    requires = step.get("requires", "")
    # 检查依赖的启动步骤是否成功
    if requires:
        # requires 格式: "docker_start:comfyui"
        key = "started_%s" % requires.split(":")[-1] if ":" in requires else None
        if key and not context.get(key, False):
            return -2, "skipped: %s failed" % requires
    ok, waited = wait_ready(port, timeout=timeout)
    return (0 if ok else -1), "waited %ds" % waited


# 动作处理器映射
_STEP_HANDLERS = {
    "pre_release_vram": _step_pre_release_vram,
    "ollama_stop_all": _step_ollama_stop_all,
    "docker_start": _step_docker_start,
    "docker_stop": _step_docker_stop,
    "vram_release": _step_vram_release,
    "game_on": _step_game_on,
    "wait_ready": _step_wait_ready,
}


def _execute_step(step: dict, context: dict) -> dict:
    """执行单个步骤，返回 {step, rc, output, critical, label}"""
    action = step.get("action", "")
    label = step.get("label", action)
    critical = step.get("critical", False)
    handler = _STEP_HANDLERS.get(action)
    if not handler:
        return {"step": label, "action": action, "rc": -99, "output": "unknown action: %s" % action,
                "critical": critical, "skipped": False}
    try:
        rc, out = handler(step, context)
        skipped = isinstance(out, str) and out.startswith("skipped")
        return {"step": label, "action": action, "rc": rc, "output": out[-300:],
                "critical": critical, "skipped": skipped}
    except Exception as e:
        log_error("scene_step_exception", error=e, action=action)
        return {"step": label, "action": action, "rc": -1, "output": "exception: %s" % str(e),
                "critical": critical, "skipped": False}


# ============================================================
# 显存预算预检
# ============================================================

def _check_vram_budget(scene_config: dict) -> dict:
    """检查目标场景的显存预算是否可达。
    返回 {ok, required_mb, current_free_mb, releasable_mb, message}"""
    budget_gb = scene_config.get("vram_budget_gb", 0)
    if not budget_gb:
        return {"ok": True, "message": "无预算限制"}
    required_mb = budget_gb * 1024
    gpu = gpu_status()
    current_free = gpu.get("free_mb", 0)
    # 估算可释放显存：已加载模型 + 可停止容器
    releasable = 0
    try:
        from services.status import comfy_loaded_models
        loaded = comfy_loaded_models()
        for m in loaded.get("models", []):
            releasable += m.get("vram_mb", 0)
    except Exception:
        pass
    total_available = current_free + releasable
    ok = total_available >= required_mb * 0.9  # 允许10%余量
    return {
        "ok": ok,
        "required_mb": required_mb,
        "current_free_mb": current_free,
        "releasable_mb": releasable,
        "total_available_mb": total_available,
        "message": "需要 %.1fGB，可用 %.1fGB（当前 %.1fG + 可释放 %.1fG）" % (
            required_mb / 1024, total_available / 1024, current_free / 1024, releasable / 1024)
    }


# ============================================================
# 场景切换（配置驱动）
# ============================================================

def scene_switch(scene: str) -> dict:
    """场景切换：配置驱动，步骤定义在 registry.json 的 scenes[scene].steps 中。

    流程：
    1. 白名单校验
    2. 并发锁（非阻塞，失败立即返回）
    3. 显存预算预检
    4. 顺序执行 steps
    5. 关键步骤失败判定
    6. 状态持久化
    """
    # 1. 白名单校验
    scenes_config = REGISTRY.get("scenes", {})
    if scene not in scenes_config:
        log_error("scene_switch_invalid", "invalid scene name", scene=scene,
                  valid=list(scenes_config.keys()))
        return {"ok": False, "error": "unknown scene: " + str(scene),
                "valid_scenes": list(scenes_config.keys())}

    # 2. 并发锁（非阻塞）
    if not _scene_lock.acquire(blocking=False):
        return {"ok": False, "error": "场景切换进行中，请稍候再试", "busy": True}

    try:
        scene_config = scenes_config[scene]
        start_time = time.time()
        gpu_before = gpu_status()
        log_event("scene_switch_start", scene=scene, vram_free_before=gpu_before.get("free_mb"))

        # 3. 显存预算预检
        budget_check = _check_vram_budget(scene_config)
        if not budget_check["ok"]:
            log_error("scene_switch_vram_insufficient", scene=scene,
                      required=budget_check["required_mb"],
                      available=budget_check["total_available_mb"])
            return {"ok": False, "error": "显存预算不足：" + budget_check["message"],
                    "budget": budget_check, "actions": []}

        # 4. 顺序执行 steps
        steps = scene_config.get("steps", [])
        context = {}
        results = []
        for step in steps:
            result = _execute_step(step, context)
            results.append(result)
            # 关键步骤失败时，继续执行后续步骤（如停止容器），但标记整体失败
            if result["critical"] and result["rc"] != 0 and not result["skipped"]:
                log_error("scene_switch_critical_failed", scene=scene,
                          step=result["step"], rc=result["rc"])

        # 5. 关键步骤失败判定
        failed_critical = [r["step"] for r in results
                           if r["critical"] and r["rc"] != 0 and not r["skipped"]]
        overall_ok = len(failed_critical) == 0

        # 6. 状态持久化
        duration_ms = int((time.time() - start_time) * 1000)
        gpu_after = gpu_status()
        if overall_ok:
            scene_state = registry.get("last_scene", {})
            scene_state["scene"] = scene
            registry.set("last_scene", scene_state)
            _save_last_scene(scene)

        log_event("scene_switch_done", scene=scene, duration_ms=duration_ms,
                  vram_free_after=gpu_after.get("free_mb"), actions_count=len(results),
                  ok=overall_ok, failed_critical=failed_critical)

        return {
            "ok": overall_ok,
            "scene": scene,
            "error": "关键步骤失败: " + ", ".join(failed_critical) if failed_critical else None,
            "budget_check": budget_check,
            "duration_ms": duration_ms,
            "vram_free_before": gpu_before.get("free_mb"),
            "vram_free_after": gpu_after.get("free_mb"),
            "actions": [
                {"step": r["step"], "action": r["action"], "rc": r["rc"],
                 "output": r["output"], "critical": r["critical"], "skipped": r["skipped"]}
                for r in results
            ]
        }
    finally:
        _scene_lock.release()


# ============================================================
# 模型加载/停止（保留原有功能）
# ============================================================

def load_model_api(name, ctx, keep="30m"):
    """通过 API 加载模型(keep_alive 默认 30m, 不阻塞太久)"""
    body = json.dumps({"model": name, "prompt": "hi", "stream": False, "keep_alive": keep,
                       "options": {"num_ctx": ctx, "num_predict": 1}}).encode()
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return 0, "loaded (ctx=%d)" % ctx
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
            outs.append("%s:SKIP(%s)" % (n, checked))
            continue
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "stop", checked], 60)
        outs.append("%s:rc%d" % (checked, rc))
        if rc != 0:
            bad.append(checked)
    return (0 if not bad else 1), " | ".join(outs) + ("" if not bad else "  FAILED: " + ",".join(bad))


# ============================================================
# 组合切换（修复返回值）
# ============================================================

def combo_switch(combo: str) -> dict:
    """对话态模型组合（从 registry.json 配置驱动）。
    互斥规则: 27B 独占, 换入前必须先 stop 其他大模型。
    修复：根据实际执行结果返回 ok，而不是永远 True。"""
    results = []
    installed = ollama_tags()
    combos = REGISTRY.get("ollama", {}).get("combos", {})
    models_meta = {m["id"]: m for m in REGISTRY.get("ollama", {}).get("models", [])}
    if combo not in combos:
        return {"ok": False, "error": "unknown combo: " + combo, "actions": []}
    cfg = combos[combo]
    to_load = cfg.get("load", [])
    to_stop = cfg.get("stop", [])

    def _load_if_installed(name):
        if name not in installed:
            return -1, "SKIP: model not installed (ollama pull %s)" % name
        ctx = models_meta.get(name, {}).get("ctx", 16384)
        return load_model_api(name, ctx)

    def _stop_if_installed(names):
        if names == "all":
            return ollama_stop_all()
        to_stop_list = [n for n in names if n in installed]
        if not to_stop_list:
            return 0, "all already stopped/not installed"
        return ollama_stop(to_stop_list)

    all_ok = True
    if to_stop:
        rc, out = _stop_if_installed(to_stop)
        results.append(("stop conflicting models", rc, out))
        if rc != 0:
            all_ok = False
    for model_id in to_load:
        ctx = models_meta.get(model_id, {}).get("ctx", 16384)
        rc, out = _load_if_installed(model_id)
        results.append(("load %s @%d" % (model_id, ctx), rc, out))
        if rc != 0 and not out.startswith("SKIP"):
            all_ok = False

    log_event("combo_switch", combo=combo, load_count=len(to_load),
              stop_count=len(to_stop) if isinstance(to_stop, list) else 0, ok=all_ok)
    return {"ok": all_ok, "combo": combo, "actions": [
        {"step": name, "rc": rc, "output": out[-300:]} for name, rc, out in results
    ]}


# ============================================================
# 服务/模型操作（保留原有功能）
# ============================================================

def service_action(name: str, action: str) -> dict:
    """服务启停（comfyui/fooocus）。"""
    if name not in ("comfyui", "fooocus"):
        return {"ok": False, "error": "unsupported service: " + name}
    rc, out = docker_action(name, action)
    return {"ok": rc == 0, "name": name, "action": action, "rc": rc, "output": out[-300:]}


def model_action(name: str, action: str) -> dict:
    """模型加载/卸载/查询，name 做格式校验，命令用 shell=False 参数数组防注入。

    支持的 action:
    - load: 加载模型（ollama run）
    - stop / unload: 卸载模型（ollama stop）
    - list / ps: 查询已加载模型列表（含显存占用）
    - info: 查询单个模型信息
    """
    # list/ps 不需要 name
    if action in ("list", "ps"):
        try:
            from services.ollama import ollama_ps
            result = ollama_ps()
            return {"ok": result.get("ok", False), "action": action,
                    "models": result.get("models", []),
                    "count": len(result.get("models", [])),
                    "total_vram_gb": round(sum(m.get("size_gb", 0) for m in result.get("models", [])), 1)}
        except Exception as e:
            return {"ok": False, "action": action, "error": str(e)}
    # 其他操作需要 name
    if action not in ("load", "stop", "unload", "info"):
        return {"ok": False, "error": "unknown action: " + str(action)}
    ok, checked = _safe_model_name(name)
    if not ok:
        return {"ok": False, "error": checked}
    if action == "load":
        gpu = gpu_status()
        _free_target = get_threshold_value("free_target_mb", 4096)
        if gpu.get("ok") and gpu.get("free_mb", 99999) < _free_target:
            log_event("model_load_rejected", model=checked, reason="free_vram<%dMB" % _free_target,
                      free_mb=gpu.get("free_mb"))
            return {"ok": False, "name": checked, "action": action,
                    "error": "显存不足（空闲 %.1fGB < %.1fGB），已拒绝加载以防止 OOM。请先释放显存或切换场景。" % (
                        gpu.get("free_mb", 0) / 1024, _free_target / 1024)}
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "run", checked,
                            "--keepalive", "30s"], 300)
    elif action in ("stop", "unload"):
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "stop", checked], 30)
    else:  # info
        try:
            from services.ollama import ollama_ps
            result = ollama_ps()
            models = result.get("models", [])
            matched = [m for m in models if m.get("name", "") == checked]
            if matched:
                return {"ok": True, "name": checked, "action": action,
                        "loaded": True, "vram_gb": matched[0].get("size_gb", 0),
                        "until": matched[0].get("until", "")}
            else:
                return {"ok": True, "name": checked, "action": action, "loaded": False}
        except Exception as e:
            return {"ok": False, "name": checked, "action": action, "error": str(e)}
    return {"ok": rc == 0, "name": checked, "action": action, "rc": rc, "output": out[-300:]}


# ============================================================
# 模型同步（保留原有功能）
# ============================================================

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
    """判断登记 id 是否为文件名型（直接对应磁盘文件）。"""
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
    reg_files = {m["id"] for m in reg_models if _file_like_id(m["id"])}
    matched = {f for f in files if _match_comfy_model(f.lower(), reg_models) or f in reg_files}
    for f in sorted(files - matched):
        out.append({"id": "auto:" + f, "name": f, "vram_gb": 0, "category": "unknown",
                    "exclusive": False, "installed": True, "auto": True, "file": f})
    return out
