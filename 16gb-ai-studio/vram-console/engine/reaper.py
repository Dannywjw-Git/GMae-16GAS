#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae Idle Reaper 引擎
- 服务活跃度追踪
- 空闲自动回收显存
"""
import os
import time
import threading
from core.logger import log_event, log_error
from core.config import OLLAMA_CONTAINER
from core.registry import registry
from core.utils import run_args
from services.ollama import ollama_ps
from services.comfy import comfy_free, comfy_queue

# === 服务活跃度追踪 — 已迁移到 registry ===
registry.set("last_busy", {})


def _mark_busy(svc):
    busy = registry.get("last_busy", {})
    busy[svc] = int(time.time())
    registry.set("last_busy", busy)


def service_activity():
    """服务活跃度：观测式记录各服务最后忙碌时间 → 空闲时长。"""
    now = int(time.time())
    om = ollama_ps().get("models", [])
    if om:
        _mark_busy("ollama")
    cq = comfy_queue()
    busy_comfy = cq.get("ok") and (cq.get("running_count", 0) + cq.get("pending_count", 0)) > 0
    if busy_comfy:
        _mark_busy("comfyui")
    out = {}
    busy_map = registry.get("last_busy", {})
    for svc, running in (("ollama", bool(om)), ("comfyui", busy_comfy), ("fooocus", False)):
        lb = busy_map.get(svc)
        out[svc] = {"busy": running, "last_busy": lb,
                    "idle_s": (now - lb) if (lb is not None and not running) else 0}
    return {"ok": True, "services": out, "ts": now}


# === Idle Reaper 配置 ===
REAPER_CFG = {
    "enabled": os.environ.get("VRAM_REAPER_ENABLED", "1") != "0",
    "check_interval_s": int(os.environ.get("VRAM_REAPER_INTERVAL", "60")),
    "thresholds_s": {
        "ollama": int(os.environ.get("VRAM_REAPER_OLLAMA_S", "1800")),
        "comfyui": int(os.environ.get("VRAM_REAPER_COMFYUI_S", "1800")),
        "fooocus": int(os.environ.get("VRAM_REAPER_FOOOCUS_S", "1800")),
    },
}


def _reap_service(svc, idle_s):
    """执行空闲回收：ollama 卸载空闲模型；comfyui 释放显存。"""
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
    busy = registry.get("last_busy", {})
    busy.pop(svc, None)
    registry.set("last_busy", busy)


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
                    continue
                lb = x.get("last_busy")
                if lb is None:
                    continue
                if (now - lb) >= thr:
                    _reap_service(svc, now - lb)
        except Exception as e:
            log_error("idle_reaper_error", error=e)


def start_idle_reaper():
    t = threading.Thread(target=_idle_reaper_loop, daemon=True, name="idle-reaper")
    t.start()
    return t
