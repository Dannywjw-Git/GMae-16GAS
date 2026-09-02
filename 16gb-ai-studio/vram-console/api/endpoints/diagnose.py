#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根因诊断端点（S2.5）
- POST /api/diagnose — 执行根因诊断，返回 Top3 根因候选
- GET  /api/diagnose/rules — 获取所有诊断规则元信息
"""
from api.router import router
from api.request import Request
from api.response import Response
from engine.diagnose import rule_engine
from engine.event_bus import event_bus


@router.post("/api/diagnose")
def post_diagnose(req: Request) -> Response:
    """执行根因诊断。

    Body 参数：
        alert_type: 告警类型，如 "vram_critical"
        alert_time: 告警时间（ISO 8601），可选
        window_seconds: 回溯时间窗（秒），默认 300
        current_status: 当前系统状态（/api/status 的数据），可选，不传则用空状态
    """
    alert_type = req.body_get("alert_type", "unknown")
    alert_time = req.body_get("alert_time", None)
    window_seconds = int(req.body_get("window_seconds", 300))
    current_status = req.body_get("current_status", None)

    # window_seconds 下限保护
    if window_seconds < 10:
        window_seconds = 10

    result = rule_engine.diagnose(
        alert_type=alert_type,
        alert_time=alert_time,
        window_seconds=window_seconds,
        current_status=current_status
    )

    try:
        event_bus.record(
            category="user_action", level="info", source="api_endpoint",
            event="diagnose_execute",
            message="执行根因诊断（{}，匹配{}条规则）".format(
                alert_type, len(getattr(result, 'matched_rules', []))
            ),
            metadata={"alert_type": alert_type, "window_seconds": window_seconds,
                      "matched_rules": len(getattr(result, 'matched_rules', [])),
                      "total_events": getattr(result, 'total_events', 0)}
        )
    except Exception:
        pass

    return Response.success({
        "alert_type": result.alert_type,
        "alert_time": result.alert_time,
        "window_seconds": result.window_seconds,
        "matched_rules": result.matched_rules,
        "matched_failure_scenarios": result.matched_failure_scenarios,
        "total_events": result.total_events,
        "default_diagnosis": result.default_diagnosis,
    })


@router.get("/api/diagnose/rules")
def get_diagnose_rules(req: Request) -> Response:
    """获取所有诊断规则元信息。"""
    rules = rule_engine.get_all_rules()
    return Response.success({
        "rules": rules,
        "count": len(rules),
    })
