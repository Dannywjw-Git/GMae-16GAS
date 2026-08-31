#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 场景切换与模型同步模块
- scene_switch: 场景切换（dialogue/comfy/h3/fooocus/music/game）
- combo_switch: 对话态模型组合切换
- service_action / model_action: 服务/模型操作
- 模型登记台自动同步（ollama + comfyui）
"""
import json
import time
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

# 当前场景状态 — 已迁移到 registry
registry.set("last_scene", {"scene": None})

# ComfyUI 主模型目录
_COMFY_MODEL_DIRS = ["checkpoints", "unet", "diffusion_models"]


def scene_switch(scene: str) -> dict:
    """场景切换：dialogue/comfy/h3/fooocus/music/game。
    M1 铁律：切换前必须先释放显存到 free_target 以下，防止打满死机。"""
    start_time = time.time()
    results = []
    gpu_before = gpu_status()
    log_event("scene_switch_start", scene=scene, vram_free_before=gpu_before.get("free_mb"))
    gpu = gpu_status()
    _free_target = get_threshold_value("free_target_mb", 4096)
    if gpu.get("ok") and gpu.get("free_mb", 99999) < _free_target:
        log_event("vram_pre_release", reason=f"free<{_free_target}MB", free_mb=gpu.get("free_mb"))
        results.append(("pre-release VRAM (<4G detected, gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
    if scene == "dialogue":
        results.append(("stop fooocus", docker_action("fooocus", "stop")))
        results.append(("stop comfyui (回对话态停文生图容器, 释放 WSL RAM)", docker_action("comfyui", "stop")))
    elif scene == "comfy":
        results.append(("stop ollama models (free VRAM for image gen)", ollama_stop_all()))
        start_rc, start_out = docker_action("comfyui", "start")
        results.append(("start comfyui", (start_rc, start_out)))
        results.append(("stop fooocus", docker_action("fooocus", "stop")))
        results.append(("release VRAM (gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
        if start_rc == 0:
            ok, w = wait_ready(8188)
            results.append(("wait comfyui ready (:8188)", (0 if ok else -1, "waited {}s".format(w))))
        else:
            results.append(("wait comfyui ready (:8188)", (-2, "skipped: start failed")))
    elif scene == "h3":
        results.append(("stop ollama models (H3 needs full VRAM)", ollama_stop_all()))
        start_rc, start_out = docker_action("comfyui", "start")
        results.append(("start comfyui", (start_rc, start_out)))
        results.append(("stop fooocus (防叠加)", docker_action("fooocus", "stop")))
        results.append(("release VRAM (gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
        if start_rc == 0:
            ok, w = wait_ready(8188)
            results.append(("wait comfyui ready (:8188)", (0 if ok else -1, "waited {}s".format(w))))
        else:
            results.append(("wait comfyui ready (:8188)", (-2, "skipped: start failed")))
    elif scene == "fooocus":
        results.append(("stop ollama models (free VRAM for Flux)", ollama_stop_all()))
        start_rc, start_out = docker_action("fooocus", "start")
        results.append(("start fooocus", (start_rc, start_out)))
        results.append(("stop comfyui (防 SDXL 驻留叠加)", docker_action("comfyui", "stop")))
        results.append(("release VRAM (gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
        if start_rc == 0:
            ok, w = wait_ready(7865)
            results.append(("wait fooocus ready (:7865)", (0 if ok else -1, "waited {}s".format(w))))
        else:
            results.append(("wait fooocus ready (:7865)", (-2, "skipped: start failed")))
    elif scene == "music":
        results.append(("stop ollama models (Music3 needs full VRAM)", ollama_stop_all()))
        start_rc, start_out = docker_action("comfyui", "start")
        results.append(("start comfyui", (start_rc, start_out)))
        results.append(("stop fooocus", docker_action("fooocus", "stop")))
        results.append(("release VRAM (gpu_release.ps1)", run_ps1(GPU_RELEASE_PS1)))
        if start_rc == 0:
            ok, w = wait_ready(8188)
            results.append(("wait comfyui ready (:8188)", (0 if ok else -1, "waited {}s".format(w))))
        else:
            results.append(("wait comfyui ready (:8188)", (-2, "skipped: start failed")))
    elif scene == "game":
        results.append(("stop comfyui", docker_action("comfyui", "stop")))
        results.append(("stop fooocus", docker_action("fooocus", "stop")))
        results.append(("release for game (game-on.ps1)", run_ps1(GAME_ON_PS1)))
    else:
        log_error("scene_switch_unknown", scene=scene)
        return {"ok": False, "error": "unknown scene: " + scene}
    scene_state = registry.get("last_scene", {})
    scene_state["scene"] = scene
    registry.set("last_scene", scene_state)
    duration_ms = int((time.time() - start_time) * 1000)
    gpu_after = gpu_status()
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


def load_model_api(name, ctx, keep="30m"):
    """通过 API 加载模型(keep_alive 默认 30m, 不阻塞太久)"""
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


def combo_switch(combo: str) -> dict:
    """对话态模型组合（从 registry.json 配置驱动）。
    互斥规则: 27B 独占, 换入前必须先 stop 其他大模型。"""
    results = []
    installed = ollama_tags()
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

    if to_stop:
        results.append(("stop conflicting models", _stop_if_installed(to_stop)))
    for model_id in to_load:
        ctx = models_meta.get(model_id, {}).get("ctx", 16384)
        results.append(("load {} @{}".format(model_id, ctx), _load_if_installed(model_id)))
    log_event("combo_switch", combo=combo, load_count=len(to_load),
              stop_count=len(to_stop) if isinstance(to_stop, list) else 0)
    return {"ok": True, "combo": combo, "actions": [
        {"step": name, "rc": rc, "output": out[-300:]} for name, (rc, out) in results
    ]}


def service_action(name: str, action: str) -> dict:
    """服务启停（comfyui/fooocus）。"""
    if name not in ("comfyui", "fooocus"):
        return {"ok": False, "error": "unsupported service: " + name}
    rc, out = docker_action(name, action)
    return {"ok": rc == 0, "name": name, "action": action, "rc": rc, "output": out[-300:]}


def model_action(name: str, action: str) -> dict:
    """模型加载/停止，name 做格式校验，命令用 shell=False 参数数组防注入。"""
    if action not in ("load", "stop"):
        return {"ok": False, "error": "unknown action: " + str(action)}
    ok, checked = _safe_model_name(name)
    if not ok:
        return {"ok": False, "error": checked}
    if action == "load":
        gpu = gpu_status()
        _free_target = get_threshold_value("free_target_mb", 4096)
        if gpu.get("ok") and gpu.get("free_mb", 99999) < _free_target:
            log_event("model_load_rejected", model=checked, reason=f"free_vram<{_free_target}MB",
                      free_mb=gpu.get("free_mb"))
            return {"ok": False, "name": checked, "action": action,
                    "error": "显存不足（空闲 %.1fGB < %.1fGB），已拒绝加载以防止 OOM。请先释放显存或切换场景。" % (
                        gpu.get("free_mb", 0)/1024, _free_target/1024)}
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "run", checked,
                            "--keepalive", "30s"], 300)
    else:
        rc, out = run_args(["docker", "exec", OLLAMA_CONTAINER, "ollama", "stop", checked], 30)
    return {"ok": rc == 0, "name": checked, "action": action, "rc": rc, "output": out[-300:]}


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
