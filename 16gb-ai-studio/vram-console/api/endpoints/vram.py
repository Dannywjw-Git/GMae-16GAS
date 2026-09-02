#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
显存管理与桌面进程端点（中间层重构 M3）
- POST /api/free — 一键释放显存
- GET  /api/budget — 预算引擎检查（支持 ?context=mid:gb,mid:gb）
- GET  /api/advice — 显存优化建议
- GET  /api/desktop_vram — 桌面进程显存详情
- POST /api/desktop/kill — 结束桌面进程
- GET  /api/desktop/helper/status — Helper 状态
- POST /api/desktop/helper/start — 启动 Helper
- POST /api/desktop/helper/stop — 停止 Helper
"""
from api.router import router
from api.request import Request
from api.response import Response
from services.status import invalidate_status_cache
from engine.budget import budget_engine, vram_advice
from services.docker import free_all
from core.status_cache import status_cache
from services.helper import (
    helper_status, helper_start, helper_stop,
    desktop_vram_detail, desktop_kill
)
from core.event_bus import event_bus


@router.post("/api/free")
def post_free(req: Request) -> Response:
    """一键释放显存（L1-L4 分级释放）。"""
    result = free_all()
    invalidate_status_cache()
    status_cache.invalidate()
    try:
        freed = result.get("freed_mb", result.get("freed", 0)) if isinstance(result, dict) else 0
        event_bus.record(
            category="user_action", level="info", source="api_endpoint",
            event="vram_free_executed",
            message="显存释放执行，释放约 {}MB".format(freed),
            metadata={"freed_mb": freed, "result": str(result)[:200]}
        )
    except Exception as e:
        log_error("exception_suppressed", error=e, context="vram.py:42")
    return Response.success(result)


@router.get("/api/budget")
def get_budget(req: Request) -> Response:
    """预算引擎检查。

    Query 参数：
        context: 上下文覆盖，格式 "model_id:vram_gb,model_id2:vram_gb2"
    """
    context_overrides = None
    context_str = req.query.get("context", "")
    if context_str:
        context_overrides = {}
        for item in context_str.split(","):
            if ":" in item:
                mid, ctx = item.rsplit(":", 1)
                try:
                    context_overrides[mid.strip()] = int(ctx.strip())
                except ValueError: pass  # 合理忽略：值解析失败，使用默认值
    return Response.success(budget_engine(context_overrides))


@router.get("/api/advice")
def get_advice(req: Request) -> Response:
    """显存优化建议。"""
    return Response.success(vram_advice())


@router.get("/api/desktop_vram")
def get_desktop_vram(req: Request) -> Response:
    """桌面进程显存详情（需 Helper 运行）。"""
    return Response.success(desktop_vram_detail())


@router.post("/api/desktop/kill")
def post_desktop_kill(req: Request) -> Response:
    """结束桌面进程。

    Body 参数：
        pid: 进程 PID
    """
    result = desktop_kill(req.body_get("pid", ""))
    status_cache.invalidate()
    return Response.success(result)


@router.get("/api/desktop/helper/status")
def get_helper_status(req: Request) -> Response:
    """Helper 状态（UAC 提权桌面进程管理助手）。"""
    return Response.success(helper_status())


@router.post("/api/desktop/helper/start")
def post_helper_start(req: Request) -> Response:
    """启动 Helper（需 UAC 提权）。"""
    result = helper_start()
    status_cache.invalidate()
    return Response.success(result)


@router.post("/api/desktop/helper/stop")
def post_helper_stop(req: Request) -> Response:
    """停止 Helper。"""
    result = helper_stop()
    status_cache.invalidate()
    return Response.success(result)
