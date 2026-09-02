#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警相关 API 端点（S3.4）
- GET  /api/alerts — 获取活跃告警列表
- GET  /api/alerts/history — 获取告警历史
- GET  /api/alerts/silenced — 获取静默中的告警
- POST /api/alerts/silence — 静默某类告警
- POST /api/alerts/resolve — 手动解决（移除）活跃告警
- POST /api/alerts/submit — 提交告警（测试/集成用）
"""
from api.router import router
from api.request import Request
from api.response import Response
from engine.alert_manager import alert_manager
from core.event_bus import event_bus


@router.get("/api/alerts")
def get_alerts(req: Request) -> Response:
    """获取活跃告警列表。"""
    alerts = alert_manager.get_active()
    return Response.success({
        "alerts": alerts,
        "count": len(alerts),
    })


@router.get("/api/alerts/history")
def get_alerts_history(req: Request) -> Response:
    """获取告警历史。

    Query 参数：
        limit: 返回条数，默认 50，最大 100
    """
    try:
        limit = min(int(req.query.get("limit", 50)), 100)
    except ValueError:
        limit = 50
    history = alert_manager.get_history(limit=limit)
    return Response.success({
        "history": history,
        "count": len(history),
    })


@router.get("/api/alerts/silenced")
def get_alerts_silenced(req: Request) -> Response:
    """获取静默中的告警列表。"""
    silenced = alert_manager.get_silenced()
    return Response.success({
        "silenced": silenced,
        "count": len(silenced),
    })


@router.post("/api/alerts/silence")
def post_alert_silence(req: Request) -> Response:
    """静默某类告警。

    Body 参数：
        alert_type: 告警类型（必填）
        duration_minutes: 静默时长（分钟），默认 30
    """
    alert_type = req.body_get("alert_type", "")
    if not alert_type:
        return Response.error("INVALID_PARAM", "alert_type is required", http_status=400)
    try:
        duration = int(req.body_get("duration_minutes", 30))
    except ValueError:
        duration = 30
    if duration < 1:
        duration = 1
    if duration > 1440:  # 最大 24 小时
        duration = 1440
    result = alert_manager.silence(alert_type, duration_minutes=duration)
    try:
        event_bus.record(
            category="user_action", level="info", source="api_endpoint",
            event="alert_silence",
            message="静默告警 {}（{}分钟）".format(alert_type, duration),
            metadata={"alert_type": alert_type, "duration_minutes": duration, "result": str(result)[:200]}
        )
    except Exception as e:
        log_error("exception_suppressed", error=e, context="alerts.py:84")
    return Response.success(result)


@router.post("/api/alerts/resolve")
def post_alert_resolve(req: Request) -> Response:
    """手动解决（移除）一个活跃告警。

    Body 参数：
        alert_type: 告警类型（必填）
    """
    alert_type = req.body_get("alert_type", "")
    if not alert_type:
        return Response.error("INVALID_PARAM", "alert_type is required", http_status=400)
    resolved = alert_manager.resolve(alert_type)
    try:
        event_bus.record(
            category="user_action", level="info", source="api_endpoint",
            event="alert_resolve",
            message="解决告警 {}（{}）".format(alert_type, "成功" if resolved else "未找到"),
            metadata={"alert_type": alert_type, "resolved": resolved}
        )
    except Exception as e:
        log_error("exception_suppressed", error=e, context="alerts.py:107")
    return Response.success({
        "alert_type": alert_type,
        "resolved": resolved,
    })


@router.post("/api/alerts/submit")
def post_alert_submit(req: Request) -> Response:
    """提交告警（测试/集成用，正常应由内部模块自动提交）。

    Body 参数：
        alert_type: 告警类型（必填）
        level: 告警级别（info/warning/danger/critical），默认 warning
        message: 告警消息（必填）
        metadata: 附加元数据（可选）
    """
    alert_type = req.body_get("alert_type", "")
    if not alert_type:
        return Response.error("INVALID_PARAM", "alert_type is required", http_status=400)
    level = req.body_get("level", "warning")
    message = req.body_get("message", "")
    if not message:
        return Response.error("INVALID_PARAM", "message is required", http_status=400)
    metadata = req.body_get("metadata", {})
    result = alert_manager.submit(alert_type, level, message, metadata)
    return Response.success(result)
