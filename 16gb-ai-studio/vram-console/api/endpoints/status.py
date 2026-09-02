#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
状态查询端点（S1.1 接入指标缓存层）

- GET /api/status — 全景状态（接入 StatusCache，TTL 10秒，危险状态2秒）
- GET /api/health — 健康检查（免认证，直接返回原始 dict，修复 watchdog 兼容）
- GET /api/hardware — 硬件档案

缓存设计（详见 core/status_cache.py）：
- 首次请求：同步执行 current_status()（慢路径，可能 5-15 秒），返回实时数据
- 缓存命中（10秒内）：直接返回缓存（<500ms），meta.cached=true, stale=false
- 缓存过期有旧数据：后台异步刷新，返回旧数据，meta.cached=true, stale=true
- 写操作后：调用 status_cache.invalidate()，下次请求同步刷新

注意：/api/health 不包装 v1 格式，直接返回 health_check() 原始 dict。
原因：watchdog 的 _health_ok() 检查响应体顶层是否包含 "services" 字段，
若包装成 v1 格式 {ok, data, error, meta}，顶层无 services，watchdog 会
误判服务"半死"而不断重启（2026-09-01 发现的已存在 bug）。
"""
import json
from api.router import router
from api.request import Request
from api.response import Response
from api.route_helpers import health_check
from services.status import current_status
from core.utils import _hardware_info
from core.status_cache import status_cache


def _build_status() -> dict:
    """构建完整 status 响应 data（慢路径，执行所有 docker exec 调用）。

    作为 StatusCache 的 refresh_func。
    返回原始 data（不含 v1 包装的 ok/data/error/meta）。
    """
    return current_status()


@router.get("/api/status")
def get_status(req: Request) -> Response:
    """全景状态查询（接入 StatusCache）。

    响应 meta 增加缓存相关字段（接口契约 §2.1）：
    - meta.cached: 是否来自缓存
    - meta.cached_at: 缓存时间（epoch 秒），实时数据时为 null
    - meta.stale: 缓存是否已过期（后台刷新中返回旧数据时为 true）
    """
    result = status_cache.try_background_refresh(_build_status)
    if result is None:
        return Response.internal_error("status build failed", details={"reason": "current_status returned None"})

    # 从 result 中提取缓存元信息（try_background_refresh 附加在 data 顶层）
    cached = result.pop("cached", False)
    cached_at = result.pop("cached_at", None)
    stale = result.pop("stale", False)

    # 构造 meta（接口契约要求 cached/cached_at/stale 始终存在）
    meta = {
        "cached": cached,
        "cached_at": cached_at,
        "stale": stale,
    }

    return Response.success(result, meta=meta, cached=cached)


@router.get("/api/health")
def get_health(req: Request) -> Response:
    """健康检查（免认证）。

    直接返回 health_check() 原始 dict（不包装 v1 格式），
    确保 watchdog 能在顶层找到 "services" 字段。
    """
    result = health_check()
    body = json.dumps(result, ensure_ascii=False).encode("utf-8")
    return Response.static(body, content_type="application/json; charset=utf-8")


@router.get("/api/hardware")
def get_hardware(req: Request) -> Response:
    """硬件档案查询（使用 core.utils._hardware_info）。"""
    return Response.success(_hardware_info())
