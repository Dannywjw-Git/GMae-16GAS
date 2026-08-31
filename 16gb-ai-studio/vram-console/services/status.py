#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 状态汇总模块（应用服务层）
- current_status: 并行采集所有子系统状态，带 2.5s 缓存
- comfy_loaded_models: 从 ComfyUI /history 推断当前加载的模型
- invalidate_status_cache: 操作后强制刷新缓存

注意：本模块属于应用服务层，依赖 gpu/engine/services 层，不属于 core 核心层。
"""
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from core.logger import log_error, log_event
from core.config import (REGISTRY, get_threshold_value, VRAM_BASELINE_NOISE_MB,
                         COMFY_MODEL_RESIDENT_THRESHOLD_MB, VRAM_DIFF_THRESHOLD_MB,
                         VRAM_LOADING_SPEED_MB_PER_S, VRAM_LOADING_OVERHEAD_MB)
from core.registry import registry
from gpu.monitor import gpu_status, gpu_processes
from engine.eviction_guard import gpu_guard_check
from services.docker import docker_containers, infer_scene
from services.ollama import ollama_ps, ollama_tags
from services.comfy import comfy_system_stats, comfy_queue
from services.helper import _helper_health
from engine.reaper import service_activity

# 状态缓存（2.5s TTL）— 已迁移到 registry
_STATUS_CACHE_TTL = 2.5
registry.set("status_cache", {"data": None, "ts": 0, "last_danger_critical": False})


def comfy_loaded_models() -> dict:
    """从 ComfyUI /history 推断当前加载的模型（方案 A：工作流推断）。
    ComfyUI 无公开的 '当前加载模型' API，模型执行后会保留在显存中。
    取最近一次成功执行的工作流，解析其模型加载节点，映射到 registry.json。"""
    try:
        _cstat = comfy_system_stats()
        torch_used = _cstat.get("torch_vram_used_mb") or 0
    except Exception:
        torch_used = 0
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/history", timeout=5) as r:
            history = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {"ok": False, "models": [], "total_vram_gb": 0, "note": "ComfyUI offline", "torch_vram_used_mb": torch_used}

    if not history:
        return {"ok": True, "models": [], "total_vram_gb": 0, "note": "no history", "torch_vram_used_mb": torch_used}

    # 找最近一次成功的 prompt
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
            latest_prompt = prompt_data[2]

    if not latest_prompt:
        return {"ok": True, "models": [], "total_vram_gb": 0, "note": "no successful prompt", "torch_vram_used_mb": torch_used}

    # 解析模型加载节点
    comfy_models = REGISTRY.get("comfyui", {}).get("models", [])
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
        model_file = None
        if class_type == "CheckpointLoaderSimple":
            model_file = inputs.get("ckpt_name", "")
        elif class_type == "UNETLoader":
            model_file = inputs.get("unet_name", "")
        if not model_file:
            continue
        loaded_files.append(model_file)
        model_lower = model_file.lower()
        for kw, mid in keyword_map.items():
            if kw in model_lower:
                loaded_ids.add(mid)
                break

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
    likely_loaded = False
    if models and torch_used > 1024:
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


def invalidate_status_cache() -> None:
    """POST 操作（切换场景/释放/驱逐）成功后调用，强制下次 status 重新采集。"""
    cache = registry.get("status_cache", {})
    cache["ts"] = 0
    registry.set("status_cache", cache)


def _safe_call(fn, default=None):
    """并行采集时单个调用失败不影响整体，返回 default。"""
    try:
        return fn()
    except Exception as e:
        log_error("status_parallel_fetch_error", func=fn.__name__, error=e)
        return default


def _fetch_parallel_status() -> dict:
    """并行采集所有子系统状态。"""
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
    return results


def _infer_scene_from_containers(names: set) -> str:
    """根据运行中的容器和 LAST_SCENE 推断当前场景。"""
    scene = infer_scene(names)
    last = registry.get("last_scene", {}).get("scene")
    if last:
        if last in ("comfy", "music", "h3") and "comfyui" in names:
            scene = last
        elif last == "fooocus" and "fooocus" in names:
            scene = last
        elif last == "game" and "comfyui" not in names and "fooocus" not in names:
            scene = last
        elif last == "dialogue" and scene == "dialogue":
            scene = last
    return scene


def _build_vram_ledger(gpu: dict, ops: dict, comfy_models: dict) -> dict:
    """构建显存账本：双源一致性检查 + 危险等级 + 加载/释放进度。"""
    ollama_models_list = ops.get("models", []) if ops else []
    ollama_loaded_mb = sum(int(float(m.get("size_gb", 0)) * 1024) for m in ollama_models_list)
    comfy_torch_mb = int((comfy_models or {}).get("torch_vram_used_mb", 0) or 0)
    comfy_loaded_mb = comfy_torch_mb if comfy_torch_mb > COMFY_MODEL_RESIDENT_THRESHOLD_MB else 0
    noise_mb = VRAM_BASELINE_NOISE_MB
    actual_used_mb = gpu.get("used_mb", 0) if gpu else 0
    expected_used_mb = noise_mb + ollama_loaded_mb + comfy_loaded_mb
    diff_mb = actual_used_mb - expected_used_mb

    if diff_mb > VRAM_DIFF_THRESHOLD_MB:
        ledger_state = "loading"
        ledger_note = "显存高于模型明细 %.1fGB，可能有模型正在加载（ollama ps 延迟约15秒）" % (diff_mb / 1024)
    elif diff_mb < -VRAM_DIFF_THRESHOLD_MB:
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

    # 显存危险等级
    free_mb = gpu.get("free_mb", 99999) if gpu else 99999
    _crit = get_threshold_value("emergency_free_mb", 2048) // 2
    _danger = get_threshold_value("emergency_free_mb", 2048)
    _warn = get_threshold_value("warning_free_mb", 4096)
    if free_mb < _crit:
        danger_level = "critical"
    elif free_mb < _danger:
        danger_level = "danger"
    elif free_mb < _warn:
        danger_level = "warning"
    else:
        danger_level = "safe"
    vram_ledger["danger_level"] = danger_level
    vram_ledger["free_mb"] = free_mb

    if danger_level == "critical" and not registry.get("status_cache", {}).get("last_danger_critical"):
        log_event("vram_danger_critical", free_mb=free_mb, used_mb=actual_used_mb,
                  ollama_mb=ollama_loaded_mb, comfy_mb=comfy_loaded_mb, note="显存低于1GB，随时可能死机")
    cache = registry.get("status_cache", {})
    cache["last_danger_critical"] = (danger_level == "critical")
    registry.set("status_cache", cache)

    # 加载/释放进度估算
    if ledger_state == "loading":
        loading_mb = diff_mb
        eta_s = max(3, int(loading_mb / VRAM_LOADING_SPEED_MB_PER_S))
        vram_ledger["loading_progress"] = {
            "loaded_mb": loading_mb,
            "estimated_total_mb": loading_mb + VRAM_LOADING_OVERHEAD_MB,
            "percent": min(95, int(loading_mb / (loading_mb + VRAM_LOADING_OVERHEAD_MB) * 100)),
            "eta_seconds": eta_s,
            "message": "模型加载中，已占用 %.1fGB，预计还需 %d 秒（ollama ps 延迟约15秒）" % (loading_mb / 1024, eta_s),
        }
    elif ledger_state == "releasing":
        releasing_mb = abs(diff_mb)
        vram_ledger["releasing_progress"] = {
            "releasing_mb": releasing_mb,
            "eta_seconds": max(2, int(releasing_mb / 1000)),
            "message": "模型释放中，还有 %.1fGB 待释放，预计 %d 秒" % (releasing_mb / 1024, max(2, int(releasing_mb / 1000))),
        }
    return vram_ledger


def _assemble_status_data(results: dict, scene: str, vram_ledger: dict) -> dict:
    """组装最终状态数据。"""
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

    return {
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
        "qos": {"level": registry.get("qos_state", {}).get("level"),
                "degraded": registry.get("qos_state", {}).get("last_action") is not None,
                "used_gb": None,
                "msg": registry.get("qos_state", {}).get("last_action", {}).get("message", "") if registry.get("qos_state", {}).get("last_action") else ""},
        "vram_ledger": vram_ledger,
        "ts": int(time.time()),
        "cached": False,
    }


def current_status() -> dict:
    """并行采集所有子系统状态，带 2.5s 缓存。"""
    # 1. 缓存命中
    now = time.time()
    cache = registry.get("status_cache", {})
    if cache.get("data") is not None and (now - cache.get("ts", 0)) < _STATUS_CACHE_TTL:
        cached = cache["data"].copy()
        cached["ts"] = int(now)
        cached["cached"] = True
        return cached

    # 2. 缓存未命中：并行采集 + 场景推断 + 显存账本
    results = _fetch_parallel_status()
    names = results["names"] or set()
    scene = _infer_scene_from_containers(names)
    vram_ledger = _build_vram_ledger(results["gpu"] or {}, results["ops"] or {}, results["comfy_models"])
    data = _assemble_status_data(results, scene, vram_ledger)

    # 3. 存入缓存
    cache["data"] = data
    cache["ts"] = time.time()
    registry.set("status_cache", cache)
    return data
