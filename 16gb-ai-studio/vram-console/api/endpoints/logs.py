#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志查询端点（中间层重构 M2 试点）
- GET /api/logs — 读取结构化事件日志尾部，支持 ?limit=N
"""
from api.router import router
from api.request import Request
from api.response import Response
from api.route_helpers import read_logs


@router.get("/api/logs")
def get_logs(req: Request) -> Response:
    """读取结构化事件日志尾部。

    Query 参数：
        limit: 返回条数（1-500，默认 150）
    """
    limit = req.query_int("limit", 150)
    result = read_logs(limit)
    return Response.success(result)
