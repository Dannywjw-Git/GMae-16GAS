#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务与模型控制端点（中间层重构 M3）
- POST /api/service — 服务操作（start/stop/restart/status）
- POST /api/model — 模型操作（load/unload/info）
- POST /api/container/stop — 停止容器
"""
from api.router import router
from api.request import Request
from api.response import Response
from services.scene import service_action, model_action
from services.docker import container_stop
from core.status_cache import status_cache
from core.event_bus import event_bus


@router.post("/api/service")
def post_service(req: Request) -> Response:
    """服务操作。

    Body 参数：
        name: 服务名称（ollama / comfyui / fooocus / immich 等）
        action: 操作（start / stop / restart / status）
    """
    svc_name = req.body_get("name", "")
    svc_action = req.body_get("action", "")
    result = service_action(name=svc_name, action=svc_action)
    status_cache.invalidate()
    try:
        ok = result.get("ok", False) if isinstance(result, dict) else False
        event_bus.record(
            category="user_action", level="info", source="api_endpoint",
            event="service_action",
            message="服务操作 {} {}（{}）".format(svc_name, svc_action, "成功" if ok else "失败"),
            metadata={"service": svc_name, "action": svc_action, "success": ok, "result": str(result)[:200]}
        )
    except Exception:
        pass
    return Response.success(result)


@router.post("/api/model")
def post_model(req: Request) -> Response:
    """模型操作。

    Body 参数：
        name: 模型名称
        action: 操作（load / unload / info / list）
    """
    model_name = req.body_get("name", "")
    model_action_type = req.body_get("action", "")
    result = model_action(name=model_name, action=model_action_type)
    status_cache.invalidate()
    try:
        ok = result.get("ok", False) if isinstance(result, dict) else False
        if model_action_type == "load":
            event_bus.record(
                category="model", level="info", source="api_endpoint",
                event="model_loaded",
                message="加载模型 {}（{}）".format(model_name, "成功" if ok else "失败"),
                metadata={"model_name": model_name, "success": ok, "result": str(result)[:200]}
            )
        elif model_action_type == "unload":
            event_bus.record(
                category="model", level="info", source="api_endpoint",
                event="model_unloaded",
                message="卸载模型 {}（{}）".format(model_name, "成功" if ok else "失败"),
                metadata={"model_name": model_name, "success": ok, "result": str(result)[:200]}
            )
    except Exception:
        pass
    return Response.success(result)


@router.post("/api/container/stop")
def post_container_stop(req: Request) -> Response:
    """停止 Docker 容器。

    Body 参数：
        name: 容器名称
    """
    container_name = req.body_get("name", "")
    result = container_stop(container_name)
    status_cache.invalidate()
    try:
        ok = result.get("ok", False) if isinstance(result, dict) else False
        event_bus.record(
            category="container", level="warning", source="api_endpoint",
            event="container_stopped",
            message="停止容器 {}（{}）".format(container_name, "成功" if ok else "失败"),
            metadata={"container_name": container_name, "success": ok, "result": str(result)[:200]}
        )
    except Exception:
        pass
    return Response.success(result)
