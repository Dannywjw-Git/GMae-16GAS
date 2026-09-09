#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统信息端点
- GET /api/system/info — 获取宿主机硬件和平台软件信息
"""
from api.router import router
from api.request import Request
from api.response import Response
from core.system_info import system_info


@router.get("/api/system/info")
def get_system_info(req: Request) -> Response:
    """获取系统信息。

    返回 CPU、内存、磁盘、网络、OS、WSL、Docker、Python 等信息。
    探测失败的字段返回 null，前端显示"—"。
    """
    info = system_info.collect()
    return Response.success(info)
