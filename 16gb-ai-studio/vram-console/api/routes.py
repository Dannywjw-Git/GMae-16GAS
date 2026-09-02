#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae HTTP 路由模块（中间层重构 M4 精简版）
- Handler: BaseHTTPRequestHandler 子类
- 所有 API 端点已迁移到 api/endpoints/，通过新路由系统（Router + 中间件链）分发
- 本模块只负责：静态文件、页面路由、新路由适配层、基础响应方法
"""
import json
from http.server import BaseHTTPRequestHandler
from core.logger import log_error
from core.config import API_TOKEN
from api import auth as auth_mod
from api.route_helpers import serve_static_file, read_html, read_login_html
from core.response import api_success, api_error

# === 新路由系统 ===
from api.endpoints import router as new_router  # noqa: E402
from api.request import Request  # noqa: E402
from api.middleware import build_default_chain  # noqa: E402

# 公开路径（无需认证，与端点模块一致）
_PUBLIC_PATHS = {"/api/health", "/api/auth/status", "/api/auth/setup",
                  "/api/auth/login", "/api/auth/forgot", "/api/auth/reset"}

# 新中间件链
_middleware_chain = build_default_chain()


class Handler(BaseHTTPRequestHandler):
    """GMae HTTP 请求处理器（精简版）。

    所有 API 端点通过新路由系统（api/endpoints/）分发，
    本类只负责静态文件、页面路由和适配层。
    """

    # ============================================================
    # 基础辅助方法
    # ============================================================

    def _check_auth(self) -> bool:
        """认证检查：Session Cookie 优先，其次 API Token。"""
        if not auth_mod.has_admin():
            return True
        cookies = auth_mod.parse_cookie(self.headers.get("Cookie", ""))
        session_id = cookies.get(auth_mod.SESSION_COOKIE_NAME, "")
        if session_id and auth_mod.get_session(session_id):
            return True
        if API_TOKEN:
            provided = self.headers.get("X-API-Key", "")
            if provided == API_TOKEN:
                return True
        self._error("UNAUTHORIZED", "unauthorized: please login first", 401,
                    details={"need_login": True})
        return False

    def _current_user(self):
        """获取当前登录用户邮箱。"""
        cookies = auth_mod.parse_cookie(self.headers.get("Cookie", ""))
        session_id = cookies.get(auth_mod.SESSION_COOKIE_NAME, "")
        sess = auth_mod.get_session(session_id)
        return sess.get("user_email") if sess else None

    def _try_new_router(self, method: str) -> bool:
        """新路由系统适配层。匹配到端点则用新系统处理，返回 True；未匹配返回 False。"""
        path = self.path.split("?")[0]
        handler_fn, _params = new_router.match(method, path)
        if handler_fn is None:
            return False
        # 认证检查（公开路径跳过）
        if path not in _PUBLIC_PATHS:
            if not self._check_auth():
                return True
        # 用新系统处理
        try:
            req = Request(self)
            response = _middleware_chain.execute(req, handler_fn)
            response.write_to(self)
        except Exception as e:
            log_error("new_router_exception", error=str(e), path=path, method=method)
            self._error("INTERNAL_ERROR", str(e), 500)
        return True

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _success(self, data=None, meta=None, cached=False) -> None:
        """v1格式成功响应：{ok, data, error:null, meta}"""
        self._json(api_success(data, meta=meta, cached=cached))

    def _error(self, code: str, message: str, http_status: int = 400, details=None) -> None:
        """v1格式失败响应：{ok:false, data:null, error:{code,message,details}, meta}"""
        resp, status = api_error(code, message, details=details, http_status=http_status)
        self._json(resp, status)

    def _read_body(self) -> dict:
        """读取 POST 请求体 JSON。"""
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            return {}

    # ============================================================
    # 请求分发
    # ============================================================

    def do_GET(self) -> None:
        # 静态文件优先（/web/ /css/ /js/ /assets/ 均从 web/ 目录服务）
        _p = self.path.split("?")[0]
        if _p.startswith("/web/") or _p.startswith("/css/") or _p.startswith("/js/") or _p.startswith("/assets/"):
            serve_static_file(self, _p)
            return
        # 页面路由
        if self._handle_get_pages():
            return
        # 新路由系统
        if self._try_new_router("GET"):
            return
        # 404
        self._error("NOT_FOUND", "endpoint not found", 404)

    def do_POST(self) -> None:
        # 新路由系统
        if self._try_new_router("POST"):
            return
        # 404
        self._error("NOT_FOUND", "endpoint not found", 404)

    def _handle_get_pages(self) -> bool:
        """处理页面路由，返回 True 表示已处理。"""
        _path = self.path.split("?")[0]  # 去掉查询参数
        if _path == "/" or _path == "/index.html":
            if not auth_mod.has_admin() or not self._current_user():
                html = read_login_html()
                # 首次安装：自动显示"首次设置"tab
                if not auth_mod.has_admin():
                    html = html.replace(b"<body>", b'<body data-setup="1">', 1)
                self._send(200, html, "text/html")
            else:
                self._send(200, read_html(), "text/html")
            return True
        if _path == "/login":
            html = read_login_html()
            if not auth_mod.has_admin():
                html = html.replace(b"<body>", b'<body data-setup="1">', 1)
            self._send(200, html, "text/html")
            return True
        return False

    def log_message(self, fmt, *args):
        pass
