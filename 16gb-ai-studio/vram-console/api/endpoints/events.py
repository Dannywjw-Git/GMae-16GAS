#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件相关 API 端点（S2.1 事件标准化 + EventBus）

- GET /api/events/timeline — 事件时间线，支持多维度过滤
- GET /api/events/stats — 事件统计（最近时间窗内各类别数量）

认证：需要（X-API-Key 或 Session）
响应格式：v1 统一格式 {ok, data, error, meta}
"""
from api.router import router
from api.request import Request
from api.response import Response
from engine.event_bus import event_bus


@router.get("/api/events/timeline")
def get_events_timeline(req: Request) -> Response:
    """获取事件时间线，支持多维度过滤。

    Query 参数（接口契约 §3.1）：
    - start_time: ISO 8601 起始时间（可选）
    - end_time: ISO 8601 结束时间（可选）
    - category: 事件类别过滤（vram/container/model/task/user_action/system/guard）
    - level: 事件级别过滤（debug/info/warning/error/critical）
    - source: 事件来源模块名（可选）
    - event: 事件类型名（可选，精确匹配）
    - limit: 返回数量，默认 100，最大 500
    """
    start_time = req.query.get("start_time")
    end_time = req.query.get("end_time")
    category = req.query.get("category")
    level = req.query.get("level")
    source = req.query.get("source")
    event_name = req.query.get("event")

    try:
        limit = min(int(req.query.get("limit", 100)), 500)
    except (ValueError, TypeError):
        limit = 100

    events = event_bus.query(
        start_time=start_time,
        end_time=end_time,
        category=category,
        level=level,
        source=source,
        event=event_name,
        limit=limit,
    )

    return Response.success({
        "events": events,
        "count": len(events),
    })


@router.get("/api/events/stats")
def get_events_stats(req: Request) -> Response:
    """获取事件统计（最近时间窗内各类别数量）。

    Query 参数（接口契约 §3.2）：
    - seconds: 统计时间窗（秒），默认 300（5 分钟）
    """
    try:
        seconds = int(req.query.get("seconds", 300))
    except (ValueError, TypeError):
        seconds = 300

    # 时间窗下限保护（至少 10 秒，避免过频繁查询）
    seconds = max(seconds, 10)

    stats = event_bus.count_by_category(seconds=seconds)
    total = sum(stats.values())

    return Response.success({
        "stats": stats,
        "window_seconds": seconds,
        "total": total,
    })
