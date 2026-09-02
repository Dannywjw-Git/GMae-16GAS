#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae HTTP Response 封装（中间层重构 M1）
- 包装 core/response.py 的统一 v1 格式
- 提供 Response 对象，端点函数返回 Response，由框架写入 handler
- 支持 JSON / HTML / 静态文件 / 重定向
"""
import json
from typing import Any, Optional, Dict
from core.response import api_success, api_error


class Response:
    """HTTP 响应对象。端点函数返回此对象，由框架写入 handler。

    用法：
        return Response.success({"status": "ok"})
        return Response.error("NOT_FOUND", "资源不存在", http_status=404)
        return Response.html("<html>...</html>")
        return Response.redirect("/login")
    """

    def __init__(self, body: bytes = b"", status_code: int = 200,
                 content_type: str = "application/json; charset=utf-8",
                 headers: Optional[Dict[str, str]] = None):
        self.body = body
        self.status_code = status_code
        self.content_type = content_type
        self.headers = headers or {}

    # ---- 工厂方法 ----

    @classmethod
    def success(cls, data: Any = None, meta: Optional[dict] = None,
                cached: bool = False) -> "Response":
        """成功响应（v1 格式 JSON）。"""
        payload = api_success(data=data, meta=meta, cached=cached)
        return cls(
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            status_code=200,
            content_type="application/json; charset=utf-8",
        )

    @classmethod
    def error(cls, code: str, message: str, details: Optional[dict] = None,
              http_status: int = 400) -> "Response":
        """错误响应（v1 格式 JSON）。"""
        payload, status = api_error(code, message, details=details, http_status=http_status)
        return cls(
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            status_code=status,
            content_type="application/json; charset=utf-8",
        )

    @classmethod
    def html(cls, content: str, status_code: int = 200) -> "Response":
        """HTML 响应。"""
        return cls(
            body=content.encode("utf-8") if isinstance(content, str) else content,
            status_code=status_code,
            content_type="text/html; charset=utf-8",
        )

    @classmethod
    def static(cls, data: bytes, content_type: str = "application/octet-stream",
               status_code: int = 200) -> "Response":
        """静态文件响应。"""
        return cls(body=data, status_code=status_code, content_type=content_type)

    @classmethod
    def redirect(cls, location: str, status_code: int = 302) -> "Response":
        """重定向响应。"""
        resp = cls(body=b"", status_code=status_code, content_type="text/plain")
        resp.headers["Location"] = location
        return resp

    @classmethod
    def not_found(cls, message: str = "Not Found") -> "Response":
        """404 响应。"""
        return cls.error("NOT_FOUND", message, http_status=404)

    @classmethod
    def unauthorized(cls, message: str = "未认证，请先登录") -> "Response":
        """401 响应。"""
        return cls.error("UNAUTHORIZED", message, http_status=401)

    @classmethod
    def bad_request(cls, message: str = "请求参数错误", details: Optional[dict] = None) -> "Response":
        """400 响应。"""
        return cls.error("BAD_REQUEST", message, details=details, http_status=400)

    @classmethod
    def internal_error(cls, message: str = "服务器内部错误", details: Optional[dict] = None) -> "Response":
        """500 响应。"""
        return cls.error("INTERNAL_ERROR", message, details=details, http_status=500)

    # ---- 写入 handler ----

    def write_to(self, handler) -> None:
        """将响应写入 BaseHTTPRequestHandler。"""
        handler.send_response(self.status_code)
        handler.send_header("Content-Type", self.content_type)
        handler.send_header("Content-Length", str(len(self.body)))
        for key, value in self.headers.items():
            handler.send_header(key, value)
        handler.end_headers()
        if self.body:
            handler.wfile.write(self.body)
