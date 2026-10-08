#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 显存预算引擎模块
- budget_engine: 核算每个模型能不能跑、要释放多少、差多少
- vram_advice: 高负载智能建议 + 未归因显存诊断
"""
import time
import math
from core.logger import log_event
from core.config import (REGISTRY, VRAM_BASELINE_NOISE_MB, COMFY_MODEL_RESIDENT_THRESHOLD_MB,
                         VRAM_DESKTOP_PROCESS_MIN_MB, VRAM_UNKNOWN_MIN_MB)
from gpu.monitor import gpu_status, gpu_processes, desktop_gpu_processes
from engine.reaper import service_activity
from engine.gen_stats import load_gen_stats
# 注意：本模块的 services 依赖采用函数内延迟导入，避免 engine 层模块级依赖 services 层。


def _calc_vram_breakdown(used_mb: int) -> dict:
    """计算显存占用分解（与 current_status 的 vram_ledger 口径一致）。"""
    from services.ollama import ollama_ps
    from services.comfy import comfy_loaded_models
    ollama_loaded = (ollama_ps().get("models", []) or [])
    ollama_used_mb = 0
    for m in ollama_loaded:
        try:
            ollama_used_mb += int(float(m.get("size_gb", 0) or 0) * 1024)
        except (TypeError, ValueError): pass  # 合理忽略：值解析失败，使用默认值
    comfy_torch_mb = int((comfy_loaded_models() or {}).get("torch_vram_used_mb", 0) or 0)
    comfy_used_mb = comfy_torch_mb if comfy_torch_mb > COMFY_MODEL_RESIDENT_THRESHOLD_MB else 0
    noise_mb = VRAM_BASELINE_NOISE_MB
    expected_mb = noise_mb + ollama_used_mb + comfy_used_mb
    unattributed_mb = max(0, used_mb - expected_mb)
    return {
        "ollama_loaded": ollama_loaded,
        "ollama_used_mb": ollama_used_mb,
        "comfy_used_mb": comfy_used_mb,
        "noise_mb": noise_mb,
        "unattributed_mb": unattributed_mb,
    }


def _diagnose_desktop_processes(unattributed_mb: int) -> dict:
    """未归因显存诊断：helper 逐进程显存优先，nvidia-smi 进程名兜底。"""
    from services.helper import _helper_health, _helper_req
    desktop = []
    helper_on = _helper_health()
    has_vram = False
    if helper_on:
        ok, r = _helper_req("/api/desktop_vram")
        if ok and r.get("ok"):
            for p in (r.get("processes") or []):
                try:
                    mb = int(float(p.get("MB", 0) or 0))
                except (TypeError, ValueError):
                    mb = 0
                try:
                    pid = int(p.get("Pid") or 0)
                except (TypeError, ValueError):
                    pid = 0
                name = (p.get("Name") or "").strip() or ("PID " + str(pid))
                if mb > 0 and pid > 0:
                    desktop.append({"pid": pid, "name": name, "used_mb": mb})
            has_vram = bool(desktop)
    if not desktop:
        dg = desktop_gpu_processes()
        for p in (dg.get("processes") or []):
            desktop.append({"pid": p["pid"], "name": p["name"], "used_mb": None})

    if desktop and has_vram:
        attributed_mb = sum((d.get("used_mb") or 0) for d in desktop)
        unknown_mb = max(0, unattributed_mb - attributed_mb)
    elif desktop and not has_vram:
        unknown_mb = None
    else:
        unknown_mb = unattributed_mb
    return {"desktop": desktop, "unknown_mb": unknown_mb, "helper_on": helper_on, "has_vram": has_vram}


def _generate_vram_suggestions(ollama_loaded: list, comfy_used_mb: int,
                                names: set, scene: str, desktop: list,
                                unknown_mb, helper_on: bool) -> list:
    """生成智能建议：场景活跃度感知 + 释放收益排序。"""
    activity = service_activity().get("services", {}) or {}
    comfy_busy = bool((activity.get("comfyui") or {}).get("busy"))
    suggestions = []

    # 3a. Ollama 模型逐个：对话场景最后加载的模型提示谨慎
    last_idx = len(ollama_loaded) - 1
    for i, m in enumerate(ollama_loaded):
        mname = m.get("model") or m.get("name", "")
        try:
            size_gb = float(m.get("size_gb", 0) or 0)
        except (TypeError, ValueError):
            size_gb = 0
        if not mname or size_gb <= 0:
            continue
        caution = (scene == "dialogue" and i == last_idx)
        suggestions.append({
            "id": "ollama_stop_" + mname,
            "type": "ollama_stop",
            "target": mname,
            "title": "停止对话模型 " + mname,
            "recover_mb": int(size_gb * 1024),
            "actionable": True,
            "reason": ("对话场景常用模型，若正在对话请谨慎释放" if caution
                       else "停止可释放 %.1fGB" % size_gb),
        })

    # 3b. ComfyUI：生成队列忙碌时暂不建议 /free
    if "comfyui" in names and comfy_used_mb > 0:
        suggestions.append({
            "id": "comfy_free",
            "type": "comfy_free",
            "target": "comfyui",
            "title": "ComfyUI 卸载生成模型（/free）",
            "recover_mb": comfy_used_mb,
            "actionable": not comfy_busy,
            "reason": ("生成队列正在执行，暂不建议释放" if comfy_busy
                       else "卸载后释放 %.1fGB" % (comfy_used_mb / 1024)),
        })

    # 3c. Fooocus：非出图场景才建议停容器
    if "fooocus" in names and scene != "fooocus":
        suggestions.append({
            "id": "fooocus_stop",
            "type": "fooocus_stop",
            "target": "fooocus",
            "title": "停止 Fooocus 容器",
            "recover_mb": int(6.9 * 1024),
            "actionable": True,
            "reason": "当前不在出图场景，停止可释放约 6.9GB",
        })

    # 3d. 桌面进程：非保护、占用 >100MB 的（helper 运行且有显存数据才建议）
    protected_names = {"explorer", "dwm", "csrss", "winlogon", "services", "lsass", "wininit", "taskhostw"}
    for d in desktop:
        nm = (d.get("name") or "").lower()
        if nm in protected_names:
            continue
        mb = d.get("used_mb") or 0
        if mb < VRAM_DESKTOP_PROCESS_MIN_MB:
            continue
        suggestions.append({
            "id": "desktop_kill_%s" % d.get("pid"),
            "type": "desktop_kill",
            "target": d.get("name"),
            "title": "结束桌面进程 " + (d.get("name") or ""),
            "recover_mb": mb,
            "actionable": bool(helper_on and mb > 0),
            "reason": "非受管 GPU 进程，结束可释放 %.1fGB" % (mb / 1024),
        })

    # 3e. 未归因：无法进一步定位时给出提示
    if unknown_mb is not None and unknown_mb > VRAM_UNKNOWN_MIN_MB:
        suggestions.append({
            "id": "unattributed",
            "type": "unattributed",
            "target": "other",
            "title": "其他未归因显存",
            "recover_mb": unknown_mb,
            "actionable": False,
            "reason": ("无法定位来源，可能是 CUDA context 或未识别进程；"
                       "可启动桌面 Helper 获得逐进程显存诊断" if not helper_on
                       else "剩余无法归因的占用，可能为 CUDA context 或内核预留"),
        })

    # 收益降序
    suggestions.sort(key=lambda s: -(s.get("recover_mb") or 0))
    return suggestions


def vram_advice() -> dict:
    """GMae 高负载三层应对策略·第二层：
    1) 未归因显存诊断：把 vram_ledger 中"其他/未归因"进一步分解为可识别的桌面进程
       （helper 逐进程显存 或 nvidia-smi 进程名）与仍无法归因的 unknown_mb；
    2) 智能建议：场景活跃度感知 + 释放收益排序——列出当前可释放项（停止模型 / ComfyUI /free /
       停容器 / 结束桌面进程），按可回收显存降序，供用户在显存紧张时快速决策。
    """
    from services.docker import docker_containers, infer_scene
    gpu = gpu_status()
    if not gpu.get("ok"):
        return {"ok": False, "error": "nvidia-smi unavailable"}
    used_mb = gpu.get("used_mb", 0)
    free_mb = gpu.get("free_mb", 99999)
    names = docker_containers()
    scene = infer_scene(names)

    # 1. 占用分解
    breakdown = _calc_vram_breakdown(used_mb)
    # 2. 未归因诊断
    diagnosis = _diagnose_desktop_processes(breakdown["unattributed_mb"])
    # 3. 智能建议
    suggestions = _generate_vram_suggestions(
        breakdown["ollama_loaded"], breakdown["comfy_used_mb"],
        names, scene, diagnosis["desktop"],
        diagnosis["unknown_mb"], diagnosis["helper_on"]
    )

    return {
        "ok": True,
        "ts": int(time.time()),
        "gpu": {"used_mb": used_mb, "free_mb": free_mb},
        "scene": scene,
        "breakdown": {
            "noise_mb": breakdown["noise_mb"], "ollama_mb": breakdown["ollama_used_mb"],
            "comfy_mb": breakdown["comfy_used_mb"], "unattributed_mb": breakdown["unattributed_mb"],
        },
        "desktop": diagnosis["desktop"],
        "unknown_mb": diagnosis["unknown_mb"],
        "helper_on": diagnosis["helper_on"],
        "suggestions": suggestions,
    }


def _profile_peak_gb(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else 0
    except (TypeError, ValueError):
        return 0


def budget_engine(context_overrides: dict | None = None, *, force_refresh: bool = False,
                  peak_overrides: dict | None = None) -> dict:
    """Step 4 显存预算引擎（蓝图 §6）：核算每个已知模型「能不能跑、要释放多少、差多少」。
    context_overrides: {model_id: context_size} — 用户在预演模式指定的 context 大小，
                       只接受已校准 context，找不到则拒绝准入。
    公式（蓝图 6.1）：avail = total − 底噪 − 保留 − 其他进程占用(非受管)
         能跑 = 请求模型标称 + 不可释放占用 ≤ total − reserve
    决策四选一（6.2）：ok / free_L1 / free_L2 / reject（连释放都不够 → 差多少 GB）
    独占硬约束（6.4）：exclusive 模型加载前须释放所有其他受管模型（L1/L2 可释放）。"""
    from services.ollama import ollama_ps
    from services.comfy import comfy_loaded_models
    sys_cfg = REGISTRY.get("system", {})
    try:
        noise_mb = int(float(sys_cfg.get("gpu_base_noise_gb", 1.0)) * 1024)
        reserve_mb = int(float(sys_cfg.get("vram_reserve_gb", 2.5)) * 1024)
        if noise_mb < 0 or reserve_mb < 0:
            raise ValueError("negative memory allowance")
    except (TypeError, ValueError, OverflowError):
        return {"ok": False, "error": "显存噪声或安全余量配置无效", "models": [], "loaded_models": []}
    gpu = gpu_status(force_refresh=force_refresh)
    if not gpu.get("ok") or gpu.get("stale"):
        return {"ok": False, "error": "新鲜 GPU 遥测不可用，暂停新任务准入", "models": [], "loaded_models": []}
    try:
        total_mb = int(gpu["total_mb"])
        used_mb = int(gpu["used_mb"])
        free_mb = int(gpu["free_mb"])
        if total_mb <= 0 or not 0 <= used_mb <= total_mb or not 0 <= free_mb <= total_mb:
            raise ValueError("invalid GPU memory counters")
        # Use the more conservative counter if telemetry does not conserve memory.
        used_mb = max(used_mb, total_mb - free_mb)
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"ok": False, "error": "GPU 显存计数无效，暂停新任务准入", "models": [], "loaded_models": []}
    safe_ceiling_mb = total_mb - reserve_mb
    procs = gpu_processes()
    gen_stats = load_gen_stats()
    unreleasable_mb = (procs.get("unknown_mb") or 0) + (procs.get("desktop_used_mb") or 0)
    # Attributed memory is an estimate, never an extra pool on top of capacity.
    releasable_mb = min(max(0, procs.get("known_total_mb") or 0), max(0, used_mb - noise_mb))
    retained_mb = max(noise_mb + unreleasable_mb, used_mb - releasable_mb)
    ol_loaded = set()
    for m in ollama_ps().get("models", []):
        ol_loaded.add(m.get("model") or m.get("name"))
    cf_loaded = set()
    for m in comfy_loaded_models().get("models", []):
        if isinstance(m, dict):
            cf_loaded.add(m.get("id") or m.get("name"))
        elif isinstance(m, str):
            cf_loaded.add(m)

    models = []
    for src_key, loaded_set in (("ollama", ol_loaded), ("comfyui", cf_loaded)):
        for m in REGISTRY.get(src_key, {}).get("models", []):
            mid = m["id"]
            default_vram = _profile_peak_gb(m.get("vram_gb", 0))
            context_vram_map = {k: _profile_peak_gb(v) for k, v in (m.get("context_vram", {}) or {}).items()
                                if _profile_peak_gb(v) > 0}
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
            measured_peak = (peak_overrides or {}).get((src_key, mid))
            if measured_peak is not None:
                vram = _profile_peak_gb(measured_peak)
            excl = bool(m.get("exclusive", False))
            loaded = mid in loaded_set
            uncalibrated_ctx = bool(measured_peak is None and specified_ctx and str(specified_ctx) not in context_vram_map
                                    and specified_ctx not in context_vram_map)
            invalid_estimate = not math.isfinite(vram) or vram <= 0
            if invalid_estimate:
                vram = 0  # Keep the rejected result JSON-safe; never convert NaN/inf to time.
            # vram_gb represents the task's peak estimate, not a zero-cost cache hit.
            # Until phase-aware profiles exist, loaded targets keep the conservative estimate.
            direct_peak_mb = used_mb + int(vram * 1024) if not invalid_estimate else 0
            after_release_peak_mb = retained_mb + int(vram * 1024) if not invalid_estimate else 0
            other_loaded = (ol_loaded | cf_loaded) - {mid}
            exclusive_conflict = excl and bool(other_loaded)
            if invalid_estimate or uncalibrated_ctx:
                decision, need_free, gap = "reject", 0, 0
                note = "显存估计无效或 context 未校准，请先评测"
            elif loaded:
                decision = "ok" if direct_peak_mb <= safe_ceiling_mb and not exclusive_conflict else "reject"
                need_free, gap = 0, round(max(0, direct_peak_mb - safe_ceiling_mb) / 1024, 1)
                note = "已加载；仍保留任务峰值预算" if decision == "ok" else "已加载但任务峰值预算不足或存在独占冲突"
                if measured_peak is not None and decision == 'reject' and after_release_peak_mb <= safe_ceiling_mb:
                    decision, gap = ('free_L2' if src_key == 'comfyui' else 'free_L1'), 0
                    need_free = round(max(0, direct_peak_mb - safe_ceiling_mb) / 1024, 1)
                    note = '保守测量包络需释放驻留占用，释放后重新核验'
            elif direct_peak_mb <= safe_ceiling_mb and not exclusive_conflict:
                decision, need_free, gap = "ok", 0, 0
                note = "可直接加载（含当前驻留占用）"
            elif after_release_peak_mb <= safe_ceiling_mb:
                decision = "free_L2" if src_key == "comfyui" else "free_L1"
                need_free = round(max(0, direct_peak_mb - safe_ceiling_mb) / 1024, 1)
                gap = 0
                note = "需释放受管负载并重新核验实时显存"
            else:
                decision = "reject"
                need_free = round(max(0, direct_peak_mb - safe_ceiling_mb) / 1024, 1)
                gap = round((after_release_peak_mb - safe_ceiling_mb) / 1024, 1)
                note = "释放后仍差 %s GB" % gap
            gs = gen_stats.get(mid, {})
            avg_sec = gs.get("avg_seconds")
            if invalid_estimate:
                est_text = "峰值未校准，无法估算"
            elif avg_sec:
                est_text = "基于 %d 次历史生成，平均约 %s" % (
                    gs.get("count", 0),
                    ("%d分%d秒" % (avg_sec // 60, avg_sec % 60)) if avg_sec >= 60 else ("%d秒" % avg_sec))
            else:
                est_sec = int(vram * 30)
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
    loaded_models = []
    for mid in ol_loaded:
        rm = next((x for x in REGISTRY.get("ollama", {}).get("models", []) if x["id"] == mid), None)
        loaded_models.append({"source": "ollama", "id": mid,
                              "name": rm.get("name", mid) if rm else mid,
                              "vram_gb": _profile_peak_gb(rm.get("vram_gb", 0)) if rm else 0,
                              "exclusive": bool(rm.get("exclusive", False)) if rm else False})
    for mid in cf_loaded:
        rm = next((x for x in REGISTRY.get("comfyui", {}).get("models", []) if x["id"] == mid), None)
        loaded_models.append({"source": "comfyui", "id": mid,
                              "name": rm.get("name", mid) if rm else mid,
                              "vram_gb": _profile_peak_gb(rm.get("vram_gb", 0)) if rm else 0,
                              "exclusive": bool(rm.get("exclusive", False)) if rm else False})
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
        "avail_gb": round(max(0, safe_ceiling_mb - used_mb) / 1024, 1),
        "after_release_avail_gb": round(max(0, safe_ceiling_mb - retained_mb) / 1024, 1),
        "models": models,
        "loaded_models": loaded_models,
        "ts": int(time.time()),
    }
