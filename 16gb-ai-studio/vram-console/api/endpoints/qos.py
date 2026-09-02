#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QoS 与自动保护端点（中间层重构 M3）
- GET  /api/qos/status — QoS 状态
- GET  /api/qos/check — QoS 检查
- POST /api/qos/execute — 执行 QoS 建议
- GET  /api/auto-protect/status — 自动保护状态
- POST /api/auto-protect/config — 自动保护配置
"""
from api.router import router
from engine.event_bus import event_bus
from api.request import Request
from api.response import Response
from engine.qos import (
    qos_status, qos_check, qos_execute_suggestion,
    auto_protect_status, auto_protect_config
)


@router.get("/api/qos/status")
def get_qos_status(req: Request) -> Response:
    """QoS 状态（当前水位 GREEN/YELLOW/RED + 自动保护配置）。"""
    return Response.success(qos_status())


@router.get("/api/qos/check")
def get_qos_check(req: Request) -> Response:
    """执行一次 QoS 检查，返回建议动作。"""
    return Response.success(qos_check())


@router.post("/api/qos/execute")
def post_qos_execute(req: Request) -> Response:
    """执行指定的 QoS 建议。

    Body 参数：
        suggestion_id: 建议 ID
    """
    result = qos_execute_suggestion(req.body_get("suggestion_id", ""))
    try:
        event_bus.record(
            category="user_action", level="info", source="api_endpoint",
            event="qos_execute",
            message="执行QoS建议",
            metadata={"endpoint": "/api/qos/execute"}
        )
    except Exception:
        pass

    return Response.success(result)


@router.get("/api/auto-protect/status")
def get_auto_protect_status(req: Request) -> Response:
    """自动保护状态（三级自动释放配置 + 当前触发状态）。"""
    return Response.success(auto_protect_status())


@router.post("/api/auto-protect/config")
def post_auto_protect_config(req: Request) -> Response:
    """更新自动保护配置。

    Body 参数：
        各级阈值和开关（详见 engine.qos.auto_protect_config）
    """
    result = auto_protect_config(req.body)
    return Response.success(result)
