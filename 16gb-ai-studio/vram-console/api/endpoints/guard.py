#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
显存门卫端点（中间层重构 M3）
- POST /api/guard — 门卫操作（check / evict / kick）
"""
from api.router import router
from api.request import Request
from api.response import Response
from gpu.process_guard import gpu_guard_kick
from engine.eviction_guard import gpu_guard_check, gpu_guard_evict
from core.status_cache import status_cache
from engine.event_bus import event_bus


@router.post("/api/guard")
def post_guard(req: Request) -> Response:
    """显存门卫操作。

    Body 参数：
        action: 操作类型
            - "check"（默认）：检查未登记进程
            - "evict"：驱逐未登记进程
            - "kick"：强制结束指定进程（需 pid 参数）
        pid: 进程 PID（action=kick 时必填）
        evict: bool（兼容旧参数，action 未指定时 evict=true 等同于 evict）
    """
    action = req.body_get("action", "")
    if action == "kick":
        pid = req.body_get("pid", "")
        result = gpu_guard_kick(pid)
        status_cache.invalidate()
        try:
            event_bus.record(
                category="guard", level="warning", source="api_endpoint",
                event="process_kicked",
                message="门卫强制结束进程 PID={}".format(pid),
                metadata={"pid": pid, "result": str(result)[:200]}
            )
        except Exception:
            pass
    elif action == "evict" or req.body_get("evict"):
        result = gpu_guard_evict()
        status_cache.invalidate()
        try:
            evicted = result.get("evicted", []) if isinstance(result, dict) else []
            event_bus.record(
                category="guard", level="warning", source="api_endpoint",
                event="process_evicted",
                message="门卫驱逐未登记进程，驱逐 {} 个".format(len(evicted)),
                metadata={"evicted_count": len(evicted), "result": str(result)[:200]}
            )
        except Exception:
            pass
    else:
        result = gpu_guard_check()
    return Response.success(result)
