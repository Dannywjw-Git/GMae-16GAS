#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
观测中心端点（中间层重构 M3）
- GET  /api/comfy_events — ComfyUI WebSocket 事件
- GET  /api/v1/health/services — 观测服务状态
- POST /api/v1/health/services — 添加观测服务
- POST /api/v1/health/services/remove — 移除观测服务
- POST /api/v1/health/probe — 立即探测
- GET  /api/v1/events — 事件查询（支持 service/level/event_type/keyword/limit/offset）
- GET  /api/v1/events/stats — 事件统计
- GET  /api/v1/events/alerts — 事件告警
"""
from api.router import router
from api.request import Request
from api.response import Response
from services.comfy_ws import comfy_events


@router.get("/api/comfy_events")
def get_comfy_events(req: Request) -> Response:
    """ComfyUI WebSocket 事件（最近事件列表）。"""
    return Response.success(comfy_events())


@router.get("/api/v1/health/services")
def get_health_services(req: Request) -> Response:
    """观测中心：已注册服务的健康状态。"""
    from observability.health_probe import health_probe
    return Response.success(health_probe.get_status())


@router.post("/api/v1/health/services")
def post_health_services(req: Request) -> Response:
    """观测中心：添加服务到观测列表。

    Body 参数：
        id / name: 服务标识
        url: 健康检查 URL
        type: 服务类型（http / tcp / docker）
        interval: 探测间隔（秒）
    """
    from observability.health_probe import health_probe
    data = req.body
    ok = health_probe.add_service(data)
    if ok:
        sid = data.get("id") or data.get("name")
        return Response.success({"message": "服务已添加", "id": sid})
    return Response.error("BAD_REQUEST", "缺少服务 id 或 name", http_status=400)


@router.post("/api/v1/health/services/remove")
def post_health_services_remove(req: Request) -> Response:
    """观测中心：从观测列表移除服务。

    Body 参数：
        id: 服务标识
    """
    from observability.health_probe import health_probe
    sid = req.body_get("id", "")
    ok = health_probe.remove_service(sid)
    if ok:
        return Response.success({"message": "服务已移除", "id": sid})
    return Response.error("NOT_FOUND", f"服务 {sid} 不存在", http_status=404)


@router.post("/api/v1/health/probe")
def post_health_probe(req: Request) -> Response:
    """观测中心：立即执行一次探测。

    Body 参数：
        id: 服务标识（可选，不传则探测全部）
    """
    from observability.health_probe import health_probe
    sid = req.body_get("id")
    result = health_probe.probe_now(sid)
    return Response.success(result)


@router.get("/api/v1/events")
def get_events(req: Request) -> Response:
    """事件查询（结构化事件日志，支持多条件过滤）。

    Query 参数：
        service: 服务过滤
        level: 级别过滤（INFO/WARNING/ERROR）
        event_type: 事件类型过滤
        keyword: 关键词搜索
        limit: 返回条数（默认 100）
        offset: 偏移量（默认 0）
    """
    from core.events import events
    result = events.query(
        service=req.query.get("service"),
        level=req.query.get("level"),
        event_type=req.query.get("event_type"),
        keyword=req.query.get("keyword"),
        limit=req.query_int("limit", 100),
        offset=req.query_int("offset", 0),
    )
    return Response.success(result)


@router.get("/api/v1/events/stats")
def get_events_stats(req: Request) -> Response:
    """事件统计（按级别/类型/服务聚合）。"""
    from core.events import events
    return Response.success(events.get_stats())


@router.get("/api/v1/events/alerts")
def get_events_alerts(req: Request) -> Response:
    """事件告警（最近的高优先级事件）。

    Query 参数：
        limit: 返回条数（默认 10）
    """
    from core.events import events
    result = events.get_alerts(limit=req.query_int("limit", 10))
    return Response.success(result)
