#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae HTTP 路由模块
- Handler: BaseHTTPRequestHandler 子类，处理所有 GET/POST 请求
- 辅助函数已迁移到 api.route_helpers
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from core.logger import log_event, log_error
from core.config import API_TOKEN, _V031_MODULES
from services.status import current_status, invalidate_status_cache
from core.utils import _hardware_info
from gpu.monitor import gpu_status
from gpu.process_guard import gpu_guard_kick
from engine.eviction_guard import gpu_guard_check, gpu_guard_evict
from engine.qos import qos_status, qos_check, qos_execute_suggestion, auto_protect_status, auto_protect_config
from engine.budget import budget_engine, vram_advice
from engine.scanner import model_scan, scan_register
from engine.queue import queue_snapshot, queue_enqueue, queue_cancel
from services.helper import helper_status, helper_start, helper_stop, desktop_vram_detail, desktop_kill
from services.docker import free_all, container_stop
from services.comfy_ws import comfy_events
from services.scene import scene_switch, combo_switch, service_action, model_action
from api import auth as auth_mod
from api.route_helpers import (
    serve_static_file, health_check, read_logs, registry_view,
    read_html, read_login_html, build_gate_context
)
from core.response import api_success, api_error


class Handler(BaseHTTPRequestHandler):
    """GMae HTTP 请求处理器。"""

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
    # GET 请求分发
    # ============================================================

    def do_GET(self) -> None:
        # 静态文件优先
        if self.path.startswith("/web/"):
            serve_static_file(self, self.path)
            return
        # 页面路由
        if self._handle_get_pages():
            return
        # 公开 API（无需认证）
        if self.path == "/api/health":
            self._success(health_check())
            return
        if self.path == "/api/auth/status":
            self._success(auth_mod.auth_status())
            return
        # 需认证 API
        if not self._check_auth():
            return
        self._handle_get_authenticated()

    def _handle_get_pages(self) -> bool:
        """处理页面路由，返回 True 表示已处理。"""
        if self.path == "/" or self.path == "/index.html":
            if not auth_mod.has_admin() or not self._current_user():
                html = read_login_html()
                # 首次安装：自动显示"首次设置"tab（注入 data-setup 属性）
                if not auth_mod.has_admin():
                    html = html.replace(b"<body>", b'<body data-setup="1">', 1)
                self._send(200, html, "text/html")
            else:
                self._send(200, read_html(), "text/html")
            return True
        if self.path == "/login":
            html = read_login_html()
            if not auth_mod.has_admin():
                html = html.replace(b"<body>", b'<body data-setup="1">', 1)
            self._send(200, html, "text/html")
            return True
        return False

    def _handle_get_authenticated(self) -> None:
        """处理需认证的 GET 请求。"""
        path = self.path.split("?")[0]
        # 状态查询组
        if path == "/api/status":
            self._success(current_status())
        elif path == "/api/logs":
            qs = parse_qs(urlparse(self.path).query)
            limit = qs.get("limit", ["150"])[0]
            try:
                limit = int(limit)
            except ValueError:
                limit = 150
            self._success(read_logs(limit))
        elif path == "/api/registry":
            self._success(registry_view())
        elif path == "/api/comfy_events":
            self._success(comfy_events())
        elif path == "/api/advice":
            self._success(vram_advice())
        elif path == "/api/hardware":
            self._success(_hardware_info())
        # 显存/桌面组
        elif path == "/api/desktop_vram":
            self._success(desktop_vram_detail())
        elif path == "/api/desktop/helper/status":
            self._success(helper_status())
        # 预算组
        elif path == "/api/budget":
            self._handle_get_budget()
        # 队列/扫描组
        elif path == "/api/scan":
            self._success(model_scan())
        elif path == "/api/queue":
            self._success(queue_snapshot())
        # QoS/自动保护组
        elif path == "/api/auto-protect/status":
            self._success(auto_protect_status())
        else:
            self._error("NOT_FOUND", "endpoint not found", 404)

    def _handle_get_budget(self) -> None:
        """处理 /api/budget，支持 context 查询参数。"""
        context_overrides = None
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if "context" in qs:
            context_overrides = {}
            for item in qs["context"][0].split(","):
                if ":" in item:
                    mid, ctx = item.rsplit(":", 1)
                    try:
                        context_overrides[mid.strip()] = int(ctx.strip())
                    except ValueError:
                        pass
        self._success(budget_engine(context_overrides))

    # ============================================================
    # POST 请求分发
    # ============================================================

    def do_POST(self) -> None:
        data = self._read_body()
        # 认证相关（公开）
        if self._handle_post_auth(data):
            return
        # 需认证
        if not self._check_auth():
            return
        invalidate_status_cache()
        self._handle_post_authenticated(data)

    def _handle_post_auth(self, data: dict) -> bool:
        """处理认证相关 POST，返回 True 表示已处理。"""
        if self.path == "/api/auth/setup":
            ok, msg = auth_mod.setup_admin(data.get("email", ""), data.get("password", ""))
            if ok:
                self._success({"message": msg})
            else:
                self._error("BAD_REQUEST", msg, 400)
            return True
        if self.path == "/api/auth/login":
            self._handle_login(data)
            return True
        if self.path == "/api/auth/forgot":
            ok, msg = auth_mod.generate_reset_code(data.get("email", ""))
            if ok:
                self._success({"message": msg})
            else:
                self._error("BAD_REQUEST", msg, 400)
            return True
        if self.path == "/api/auth/reset":
            ok, msg = auth_mod.reset_password(data.get("email", ""), data.get("code", ""), data.get("password", ""))
            if ok:
                self._success({"message": msg})
            else:
                self._error("BAD_REQUEST", msg, 400)
            return True
        return False

    def _handle_login(self, data: dict) -> None:
        """处理登录，设置 Session Cookie。"""
        ok, user = auth_mod.authenticate(data.get("email", ""), data.get("password", ""))
        if ok:
            session_id = auth_mod.create_session(user["email"], remember=data.get("remember", False))
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "{}={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(
                auth_mod.SESSION_COOKIE_NAME, session_id,
                auth_mod.SESSION_REMEMBER_TTL if data.get("remember") else auth_mod.SESSION_DEFAULT_TTL))
            resp = api_success({"message": "登录成功", "email": user["email"]})
            body = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._error("UNAUTHORIZED", "邮箱或密码不正确", 401)

    def _handle_post_authenticated(self, data: dict) -> None:
        """处理需认证的 POST 请求。"""
        # 场景/组合控制
        if self.path == "/api/scene":
            self._success(scene_switch(data.get("scene", "")))
        elif self.path == "/api/combo":
            self._success(combo_switch(data.get("combo", "")))
        # 显存释放/门卫
        elif self.path == "/api/free":
            result = free_all()
            invalidate_status_cache()
            self._success(result)
        elif self.path == "/api/guard":
            if data.get("action") == "kick":
                self._success(gpu_guard_kick(data.get("pid", "")))
            else:
                self._success(gpu_guard_evict() if data.get("evict") else gpu_guard_check())
        # QoS 组
        elif self.path == "/api/qos/status":
            self._success(qos_status())
        elif self.path == "/api/qos/check":
            self._success(qos_check())
        elif self.path == "/api/qos/execute":
            self._success(qos_execute_suggestion(data.get("suggestion_id", "")))
        elif self.path == "/api/auto-protect/config":
            self._success(auto_protect_config(data))
        # 服务/模型控制
        elif self.path == "/api/service":
            self._success(service_action(data.get("name", ""), data.get("action", "")))
        elif self.path == "/api/model":
            self._success(model_action(data.get("name", ""), data.get("action", "")))
        # 桌面/容器控制
        elif self.path == "/api/desktop/kill":
            self._success(desktop_kill(data.get("pid", "")))
        elif self.path == "/api/container/stop":
            self._success(container_stop(data.get("name", "")))
        elif self.path == "/api/desktop/helper/start":
            self._success(helper_start())
        elif self.path == "/api/desktop/helper/stop":
            self._success(helper_stop())
        # 队列组
        elif self.path == "/api/queue":
            self._success(queue_enqueue(data.get("model", ""), data.get("params", {})))
        elif self.path == "/api/queue/cancel":
            self._success(queue_cancel(data.get("id", "")))
        # 准入闸门
        elif self.path == "/api/admission":
            self._handle_admission(data)
        # 扫描登记
        elif self.path == "/api/scan/register":
            self._success(scan_register(data.get("source", "comfyui"), data.get("name", ""),
                                     data.get("vram_gb"), data.get("category", "image")))
        # 登出/改密
        elif self.path == "/api/auth/logout":
            self._handle_logout()
        elif self.path == "/api/auth/change-password":
            email = self._current_user()
            ok, msg = auth_mod.change_password(email or "", data.get("old_password", ""), data.get("new_password", ""))
            if ok:
                self._success({"message": msg})
            else:
                self._error("BAD_REQUEST", msg, 400)
        else:
            self._error("NOT_FOUND", "endpoint not found", 404)

    def _handle_admission(self, data: dict) -> None:
        """处理准入闸门检查。"""
        if not _V031_MODULES:
            self._error("SERVICE_UNAVAILABLE", "admission_gate module not available", 503)
            return
        from engine import admission_gate
        ctx = build_gate_context()
        result = admission_gate.check(
            action=data.get("action", ""),
            args=data.get("args", {}),
            ctx=ctx
        )
        self._success(result)

    def _handle_logout(self) -> None:
        """处理登出，清除 Session Cookie。"""
        cookies = auth_mod.parse_cookie(self.headers.get("Cookie", ""))
        session_id = cookies.get(auth_mod.SESSION_COOKIE_NAME, "")
        auth_mod.destroy_session(session_id)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", "{}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0".format(auth_mod.SESSION_COOKIE_NAME))
        resp = api_success({"message": "已登出"})
        body = json.dumps(resp, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass
