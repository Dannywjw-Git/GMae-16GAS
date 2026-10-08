#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae Idle Reaper 引擎
- 服务活跃度追踪
- 空闲自动回收显存
"""
from engine.coordinator import OperationSpec, coordinated
import os
import time
import threading
from core.logger import log_event, log_error
from core.registry import registry
# 注意：本模块的 services 依赖（ollama_ps / comfy_free / comfy_queue）采用函数内延迟导入，
# 避免 engine 层模块级依赖 services 层，保证模块可独立导入和测试。

# === 服务活跃度追踪 — 已迁移到 registry ===
registry.set("last_busy", {})


def _mark_busy(svc):
    busy = registry.get("last_busy", {})
    busy[svc] = int(time.time())
    registry.set("last_busy", busy)


def service_activity():
    """服务活跃度：观测式记录各服务最后忙碌时间 → 空闲时长。"""
    from services.ollama import ollama_ps
    from services.comfy import comfy_queue
    now = int(time.time())
    om = ollama_ps().get("models", [])
    from engine.coordinator import get_coordinator
    active = get_coordinator().snapshot().get("active") or {}
    busy_ollama = (active.get("service") == "ollama" and active.get("operation") == "load"
                   and active.get("phase") in ("running", "uncertain"))
    if busy_ollama:
        _mark_busy("ollama")
    cq = comfy_queue()
    busy_comfy = cq.get("ok") and (cq.get("running_count", 0) + cq.get("pending_count", 0)) > 0
    if busy_comfy:
        _mark_busy("comfyui")
    out = {}
    busy_map = registry.get("last_busy", {})
    for svc, running in (("ollama", busy_ollama), ("comfyui", busy_comfy), ("fooocus", False)):
        lb = busy_map.get(svc)
        out[svc] = {"busy": running, "last_busy": lb,
                    "idle_s": (now - lb) if (lb is not None and not running) else 0}
        if svc == "ollama":
            out[svc].update(resident=bool(om), activity_scope="coordinator_requests",
                            external_activity_known=False)
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


@coordinated(lambda a: OperationSpec("release", a["svc"], owner="reaper:" + str(a["svc"])), shape="dict")
def _reap_service(svc, idle_s):
    """Return actual release outcome and preserve idle bookkeeping on failure."""
    from services.ollama import ollama_stop_all
    from services.comfy import comfy_free
    log_event("idle_reaper_reap", service=svc, idle_s=idle_s)
    if svc == "ollama":
        rc, output = ollama_stop_all()
        result = {"ok": rc == 0, "error": output if rc else None}
    elif svc == "comfyui":
        result = comfy_free()
    else:
        return {"ok": False, "error": "unsupported idle service: " + svc}
    if result.get("ok"):
        busy = registry.get("last_busy", {})
        busy.pop(svc, None)
        registry.set("last_busy", busy)
    return result


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
