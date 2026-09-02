#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
场景与组合控制端点（中间层重构 M3）
- POST /api/scene — 切换场景
- POST /api/combo — 切换组合
"""
from api.router import router
from api.request import Request
from api.response import Response
from services.scene import scene_switch, combo_switch
from core.status_cache import status_cache
from engine.event_bus import event_bus


@router.post("/api/scene")
def post_scene(req: Request) -> Response:
    """切换场景。

    Body 参数：
        scene: 场景名称（dialogue / comfyui / fooocus / game / idle / maintenance）
    """
    scene_name = req.body_get("scene", "")
    result = scene_switch(scene_name)
    status_cache.invalidate()
    try:
        ok = result.get("ok", False) if isinstance(result, dict) else False
        event_bus.record(
            category="user_action", level="info", source="api_endpoint",
            event="scene_switched",
            message="切换场景到 {}（{}）".format(scene_name, "成功" if ok else "失败"),
            metadata={"to_scene": scene_name, "success": ok, "result": str(result)[:200]}
        )
    except Exception:
        pass
    return Response.success(result)


@router.post("/api/combo")
def post_combo(req: Request) -> Response:
    """切换组合（多模型组合）。

    Body 参数：
        combo: 组合名称
    """
    combo_name = req.body_get("combo", "")
    result = combo_switch(combo_name)
    status_cache.invalidate()
    try:
        ok = result.get("ok", False) if isinstance(result, dict) else False
        event_bus.record(
            category="user_action", level="info", source="api_endpoint",
            event="combo_switched",
            message="切换组合到 {}（{}）".format(combo_name, "成功" if ok else "失败"),
            metadata={"combo_name": combo_name, "success": ok, "result": str(result)[:200]}
        )
    except Exception:
        pass
    return Response.success(result)
