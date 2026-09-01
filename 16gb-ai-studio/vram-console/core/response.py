#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae API 统一响应包装（v1格式）
所有端点必须使用本模块的函数构造响应，确保格式统一。

成功响应：
    {
        "ok": true,
        "data": { ...业务数据... },
        "meta": {
            "timestamp": 1788229046.123,
            "api_version": "v1",
            "request_id": "abc123",
            "cached": false
        }
    }

失败响应：
    {
        "ok": false,
        "data": null,
        "error": {
            "code": "ERROR_CODE",
            "message": "人类可读的错误说明",
            "details": { ...可选详情... }
        },
        "meta": { ... }
    }
"""
import time
import uuid
from typing import Any, Optional

API_VERSION = "v1"


def _build_meta(cached: bool = False, extra: Optional[dict] = None) -> dict:
    """构建 meta 字段。"""
    meta = {
        "timestamp": time.time(),
        "api_version": API_VERSION,
        "request_id": uuid.uuid4().hex[:12],
        "cached": cached,
    }
    if extra:
        meta.update(extra)
    return meta


def api_success(data: Any = None, meta: Optional[dict] = None, cached: bool = False) -> dict:
    """构造成功响应。

    Args:
        data: 业务数据
        meta: 额外的 meta 字段
        cached: 是否来自缓存
    """
    return {
        "ok": True,
        "data": data if data is not None else {},
        "error": None,
        "meta": _build_meta(cached=cached, extra=meta),
    }


def api_error(code: str, message: str, details: Optional[dict] = None,
              http_status: int = 400) -> tuple:
    """构造失败响应。

    Args:
        code: 错误码（机器可读）
        message: 错误说明（人类可读）
        details: 额外详情
        http_status: HTTP 状态码

    Returns:
        (response_dict, http_status)
    """
    resp = {
        "ok": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "meta": _build_meta(),
    }
    return resp, http_status


# 常用错误码
ERROR_CODES = {
    "UNAUTHORIZED": "未认证或认证失败",
    "FORBIDDEN": "无权限",
    "NOT_FOUND": "资源不存在",
    "BAD_REQUEST": "请求参数错误",
    "INTERNAL_ERROR": "服务器内部错误",
    "SERVICE_UNAVAILABLE": "服务不可用",
    "VALIDATION_ERROR": "参数校验失败",
    "SCENE_SWITCH_BUSY": "场景切换进行中",
    "VRAM_INSUFFICIENT": "显存不足",
    "MODEL_NOT_FOUND": "模型不存在",
    "QUEUE_FULL": "队列已满",
}


def api_error_404(message: str = "资源不存在") -> tuple:
    """404 错误快捷方式。"""
    return api_error("NOT_FOUND", message, http_status=404)


def api_error_401(message: str = "未认证，请先登录") -> tuple:
    """401 错误快捷方式。"""
    return api_error("UNAUTHORIZED", message, http_status=401)


def api_error_400(message: str = "请求参数错误", details: Optional[dict] = None) -> tuple:
    """400 错误快捷方式。"""
    return api_error("BAD_REQUEST", message, details=details, http_status=400)


def api_error_500(message: str = "服务器内部错误", details: Optional[dict] = None) -> tuple:
    """500 错误快捷方式。"""
    return api_error("INTERNAL_ERROR", message, details=details, http_status=500)


def api_error_503(message: str = "服务不可用", details: Optional[dict] = None) -> tuple:
    """503 错误快捷方式。"""
    return api_error("SERVICE_UNAVAILABLE", message, details=details, http_status=503)
