#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
准入闸门端点（中间层重构 M3）
- POST /api/admission — 准入闸门检查（判断某个动作是否可以执行）
"""
from api.router import router
from api.request import Request
from api.response import Response
from api.route_helpers import build_gate_context
from core.config import _V031_MODULES
from core.event_bus import event_bus


@router.post("/api/admission")
def post_admission(req: Request) -> Response:
    """准入闸门检查（v0.3.1）。

    判断某个动作（加载模型/切换场景/提交任务等）是否可以在当前显存状态下执行。

    Body 参数：
        action: 动作类型（load_model / switch_scene / submit_task 等）
        args: 动作参数（模型ID/场景名/任务参数等）
    """
    if not _V031_MODULES:
        return Response.error(
            "SERVICE_UNAVAILABLE",
            "admission_gate module not available",
            http_status=503
        )
    from engine import admission_gate
    ctx = build_gate_context()
    adm_action = req.body_get("action", "")
    adm_args = req.body_get("args", {})
    result = admission_gate.check(action=adm_action, args=adm_args, ctx=ctx)
    try:
        decision = result.get("decision", result.get("allowed", "unknown")) if isinstance(result, dict) else "unknown"
        event_bus.record(
            category="system", level="info", source="api_endpoint",
            event="admission_checked",
            message="准入检查 action={} decision={}".format(adm_action, decision),
            metadata={"action": adm_action, "decision": decision, "args": str(adm_args)[:200], "result": str(result)[:200]}
        )
    except Exception:
        pass
    return Response.success(result)
