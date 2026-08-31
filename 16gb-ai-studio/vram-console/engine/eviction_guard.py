#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 显存门卫模块
- gpu_guard_check: 只读检查（水位 + 场景违规 + 未登记占用）
- gpu_guard_evict: 用户触发的驱逐（L2，按优先级）
"""
import time
from core.logger import log_event
from gpu.monitor import gpu_status, gpu_processes
from services.docker import docker_containers, docker_action
from services.ollama import ollama_stop_all
from services.comfy import comfy_free

# 门卫配置
GUARD_UNKNOWN_POLICY = "warn"      # unknown 进程策略：warn（默认）/ evict
GUARD_WARN_THRESHOLD = 1024        # 显存差量告警阈值（MB）


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
