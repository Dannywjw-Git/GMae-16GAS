#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae HTTP Request 封装（中间层重构 M1）
- 包装 BaseHTTPRequestHandler，提供统一的请求对象
- 端点函数签名：def handler(req: Request) -> Response
- 业务逻辑不直接操作 handler，通过 req 访问请求数据
"""
import json
from urllib.parse import urlparse, parse_qs
from typing import Any, Optional


class Request:
    """HTTP 请求封装。包装 BaseHTTPRequestHandler，提供便捷属性访问。"""

    def __init__(self, handler):
        self._handler = handler
        self._parsed_url = urlparse(handler.path)
        self._body: Optional[dict] = None
        self._query: Optional[dict] = None
        self._cookies: Optional[dict] = None

    @property
    def method(self) -> str:
        """HTTP 方法（GET/POST）。"""
        return self._handler.command

    @property
    def path(self) -> str:
        """请求路径（不含 query string）。"""
        return self._parsed_url.path

    @property
    def full_path(self) -> str:
        """完整请求路径（含 query string）。"""
        return self._handler.path

    @property
    def query(self) -> dict:
        """URL query 参数（dict，每个值是 list 的第一个元素）。"""
        if self._query is None:
            raw = parse_qs(self._parsed_url.query)
            self._query = {k: v[0] if len(v) == 1 else v for k, v in raw.items()}
        return self._query

    def query_list(self, key: str) -> list:
        """获取 query 参数的全部值（列表）。"""
        raw = parse_qs(self._parsed_url.query)
        return raw.get(key, [])

    def query_int(self, key: str, default: int = 0) -> int:
        """获取 query 参数并转为 int，失败返回 default。"""
        try:
            return int(self.query.get(key, default))
        except (TypeError, ValueError):
            return default

    @property
    def body(self) -> dict:
        """POST 请求体（JSON 解析为 dict）。"""
        if self._body is None:
            self._body = self._read_body()
        return self._body

    def _read_body(self) -> dict:
        """读取 POST 请求体 JSON。"""
        try:
            length = int(self._handler.headers.get("Content-Length", 0) or 0)
            if length <= 0:
                return {}
            raw = self._handler.rfile.read(length)
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def body_get(self, key: str, default: Any = None) -> Any:
        """获取 body 参数，不存在返回 default。"""
        return self.body.get(key, default)

    @property
    def headers(self):
        """请求头（http.client.HTTPMessage 对象，支持 .get()）。"""
        return self._handler.headers

    def header(self, key: str, default: str = "") -> str:
        """获取请求头。"""
        return self._handler.headers.get(key, default)

    @property
    def cookies(self) -> dict:
        """Cookie 解析为 dict。"""
        if self._cookies is None:
            self._cookies = self._parse_cookies()
        return self._cookies

    def _parse_cookies(self) -> dict:
        """解析 Cookie 头。"""
        raw = self._handler.headers.get("Cookie", "")
        result = {}
        if not raw:
            return result
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                result[k.strip()] = v.strip()
        return result

    def cookie(self, key: str, default: str = "") -> str:
        """获取 Cookie 值。"""
        return self.cookies.get(key, default)

    @property
    def client_ip(self) -> str:
        """客户端 IP。"""
        return self._handler.client_address[0] if self._handler.client_address else ""

    @property
    def raw_handler(self):
        """原始 BaseHTTPRequestHandler（必要时访问，尽量不用）。"""
        return self._handler
