#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务队列端点（中间层重构 M3）
- GET  /api/queue — 队列快照
- POST /api/queue — 提交任务
- POST /api/queue/cancel — 取消任务
"""
from api.router import router
from api.request import Request
from api.response import Response
from engine.queue import queue_snapshot, queue_enqueue, queue_cancel
from core.status_cache import status_cache
from core.event_bus import event_bus


@router.get("/api/queue")
def get_queue(req: Request) -> Response:
    """任务队列快照（当前队列状态 + 历史任务）。"""
    return Response.success(queue_snapshot())


@router.post("/api/queue")
def post_queue(req: Request) -> Response:
    """提交生成任务到队列。

    Body 参数：
        model: 模型标识（sdxl / flux / music3 / wan2.2 等）
        params: 模型参数（prompt / steps / size 等）
    """
    task_model = req.body_get("model", "")
    task_params = req.body_get("params", {})
    result = queue_enqueue(model=task_model, params=task_params)
    status_cache.invalidate()
    try:
        task_id = result.get("task_id", result.get("id", "")) if isinstance(result, dict) else ""
        event_bus.record(
            category="task", level="info", source="api_endpoint",
            event="task_submitted",
            message="提交任务 model={} id={}".format(task_model, task_id),
            metadata={"model": task_model, "task_id": task_id, "params_keys": list(task_params.keys()) if isinstance(task_params, dict) else [], "result": str(result)[:200]}
        )
    except Exception:
        pass
    return Response.success(result)


@router.post("/api/queue/cancel")
def post_queue_cancel(req: Request) -> Response:
    """取消队列中的任务。

    Body 参数：
        id: 任务 ID
    """
    task_id = req.body_get("id", "")
    result = queue_cancel(task_id)
    status_cache.invalidate()
    try:
        ok = result.get("ok", False) if isinstance(result, dict) else False
        event_bus.record(
            category="task", level="warning", source="api_endpoint",
            event="task_canceled",
            message="取消任务 id={}（{}）".format(task_id, "成功" if ok else "失败"),
            metadata={"task_id": task_id, "success": ok, "result": str(result)[:200]}
        )
    except Exception:
        pass
    return Response.success(result)
