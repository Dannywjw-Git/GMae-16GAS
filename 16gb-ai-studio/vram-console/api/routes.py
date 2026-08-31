#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae HTTP 路由模块
- Handler: BaseHTTPRequestHandler 子类，处理所有 GET/POST 请求
- 辅助函数：serve_static_file, health_check, read_logs, registry_view, read_html, read_login_html
"""
import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from core.logger import log_event, log_error, LOG_FILE
from core.config import (PORT, HOST, WEB_DIR, LEGACY_HTML, FRONTEND_VERSION, BASE_DIR,
                         API_TOKEN, REGISTRY, _V031_MODULES)
from services.status import current_status, invalidate_status_cache
from core.utils import _hardware_info
from gpu.monitor import gpu_status
from gpu.guard import gpu_guard_kick
from engine.guard import gpu_guard_check, gpu_guard_evict
from engine.qos import qos_status, qos_check, qos_execute_suggestion, auto_protect_status, auto_protect_config
from engine.budget import budget_engine, vram_advice
from engine.scanner import model_scan, scan_register
from engine.queue import queue_snapshot, queue_enqueue, queue_cancel
from services.helper import helper_status, helper_start, helper_stop, desktop_vram_detail, desktop_kill
from services.docker import free_all, container_stop
from services.comfy_ws import comfy_events
from services.scene import (scene_switch, combo_switch, service_action, model_action,
                            _sync_ollama_models, _sync_comfyui_models)
import auth as auth_mod

# MIME 类型映射
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".map": "application/json",
}


def serve_static_file(self, path):
    """服务 web/ 目录下的静态文件（CSS/JS/图片/字体）"""
    rel_path = path[5:] if path.startswith("/web/") else path
    rel_path = rel_path.replace("..", "").lstrip("/")
    full_path = os.path.join(WEB_DIR, rel_path)
    if not os.path.isfile(full_path):
        self._json({"ok": False, "error": "file not found"}, 404)
        return
    ext = os.path.splitext(full_path)[1].lower()
    content_type = MIME_TYPES.get(ext, "application/octet-stream")
    try:
        with open(full_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)
    except Exception as e:
        self._json({"ok": False, "error": str(e)}, 500)


def health_check():
    """健康检查：各服务连通性 + 显存状态"""
    result = {"ok": True, "ts": time.time(), "services": {}}
    gpu = gpu_status()
    result["services"]["gpu"] = {"ok": gpu.get("ok", False), "free_mb": gpu.get("free_mb"), "total_mb": gpu.get("total_mb")}
    if not gpu.get("ok"):
        result["ok"] = False
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as r:
            ollama_ok = r.status == 200
    except Exception:
        ollama_ok = False
    result["services"]["ollama"] = {"ok": ollama_ok, "port": 11434}
    if not ollama_ok:
        result["ok"] = False
    try:
        req = urllib.request.Request("http://127.0.0.1:8188/system_stats")
        with urllib.request.urlopen(req, timeout=5) as r:
            comfy_ok = r.status == 200
    except Exception:
        comfy_ok = False
    result["services"]["comfyui"] = {"ok": comfy_ok, "port": 8188}
    if gpu.get("ok") and gpu.get("free_mb", 99999) < 2048:
        result["vram_warning"] = "free VRAM < 2GB"
    return result


def read_logs(limit=150):
    """读取结构化事件日志尾部（最后 N 条）。"""
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 150
    entries = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(" | ", 2)
        if len(parts) < 3:
            continue
        ts_raw, level, payload = parts
        try:
            obj = json.loads(payload)
        except Exception:
            obj = {"raw": payload[:300]}
        entries.append({"time": ts_raw, "level": level, **obj})
    entries.reverse()
    return {"ok": True, "entries": entries, "count": len(entries)}


def registry_view():
    """模型登记台：registry 元数据 × 实际环境自动同步。"""
    reg = REGISTRY
    return {
        "ok": True,
        "version": reg.get("version", ""),
        "last_updated": reg.get("last_updated", ""),
        "sync": True,
        "ollama_models": _sync_ollama_models(),
        "ollama_combos": reg.get("ollama", {}).get("combos", {}),
        "comfyui_models": _sync_comfyui_models(),
        "containers": reg.get("containers", []),
        "scenes": reg.get("scenes", {}),
        "system": reg.get("system", {}),
        "gpu_guard": reg.get("gpu_guard", {}),
    }


def read_html():
    """根据 FRONTEND_VERSION 返回对应版本的前端 HTML。"""
    if FRONTEND_VERSION == "v1":
        path = LEGACY_HTML
    else:
        path = os.path.join(WEB_DIR, "index.html")
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        try:
            with open(LEGACY_HTML, "rb") as f:
                return f.read()
        except Exception:
            return b"index.html not found"


def read_login_html():
    """读取登录页 HTML，不存在时返回内置最小登录页。"""
    path = os.path.join(BASE_DIR, "login.html")
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return ("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GMae 登录</title>
<style>body{font-family:sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.box{background:#1e293b;padding:32px;border-radius:12px;width:320px}
h1{color:#0d9488;margin:0 0 24px;font-size:24px}
input{width:100%;padding:10px;margin:8px 0;border:1px solid #334155;border-radius:6px;background:#0f172a;color:#e2e8f0;box-sizing:border-box}
button{width:100%;padding:12px;background:#0d9488;color:#fff;border:none;border-radius:6px;cursor:pointer;margin-top:16px;font-size:16px}
button:hover{background:#0f766e}
.msg{margin-top:12px;font-size:14px;min-height:20px}
.err{color:#f87171}.ok{color:#4ade80}
a{color:#0d9488;text-decoration:none;cursor:pointer}
.tab{display:flex;margin-bottom:16px;border-bottom:1px solid #334155}
.tab div{padding:8px 16px;cursor:pointer;color:#94a3b8}
.tab div.active{color:#0d9488;border-bottom:2px solid #0d9488}
.hidden{display:none}
</style></head><body>
<div class="box">
<h1>GMae 调度中心</h1>
<div class="tab"><div class="active" onclick="showTab('login')">登录</div><div onclick="showTab('setup')">首次设置</div><div onclick="showTab('forgot')">忘记密码</div></div>
<div id="login">
<input id="login-email" placeholder="邮箱" type="email">
<input id="login-password" placeholder="密码" type="password">
<label style="font-size:14px;color:#94a3b8"><input type="checkbox" id="login-remember" style="width:auto;margin-right:6px">记住我 30 天</label>
<button onclick="doLogin()">登录</button>
</div>
<div id="setup" class="hidden">
<input id="setup-email" placeholder="管理员邮箱" type="email">
<input id="setup-password" placeholder="设置密码（至少6位）" type="password">
<input id="setup-password2" placeholder="确认密码" type="password">
<button onclick="doSetup()">创建管理员账户</button>
</div>
<div id="forgot" class="hidden">
<input id="forgot-email" placeholder="注册邮箱" type="email">
<button onclick="doForgot()">发送验证码</button>
<div id="reset-step" class="hidden" style="margin-top:16px">
<input id="reset-code" placeholder="6位验证码" maxlength="6">
<input id="reset-password" placeholder="新密码（至少6位）" type="password">
<button onclick="doReset()">重置密码</button>
</div>
</div>
<div class="msg" id="msg"></div>
</div>
<script>
function showTab(t){document.querySelectorAll('.tab div').forEach((e,i)=>e.classList.toggle('active',['login','setup','forgot'][i]===t));['login','setup','forgot'].forEach(x=>document.getElementById(x).classList.toggle('hidden',x!==t));document.getElementById('msg').textContent='';}
function msg(t,c){var e=document.getElementById('msg');e.textContent=t;e.className='msg '+(c||'');}
async function api(url,data){var r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})});return await r.json();}
async function doLogin(){var e=document.getElementById('login-email').value,p=document.getElementById('login-password').value,r=document.getElementById('login-remember').checked;if(!e||!p)return msg('请输入邮箱和密码','err');var d=await api('/api/auth/login',{email:e,password:p,remember:r});if(d.ok){msg('登录成功，正在跳转...','ok');setTimeout(()=>location.href='/',800);}else msg(d.error||'登录失败','err');}
window.addEventListener('DOMContentLoaded',function(){var ei=document.getElementById('login-email');if(ei){ei.focus();}['login-email','login-password'].forEach(function(id){var el=document.getElementById(id);if(el){el.addEventListener('keydown',function(ev){if(ev.key==='Enter'){ev.preventDefault();doLogin();}});}});});
async function doSetup(){var e=document.getElementById('setup-email').value,p=document.getElementById('setup-password').value,p2=document.getElementById('setup-password2').value;if(!e||!p)return msg('请输入邮箱和密码','err');if(p!==p2)return msg('两次密码不一致','err');var d=await api('/api/auth/setup',{email:e,password:p});if(d.ok){msg('创建成功，请登录','ok');showTab('login');}else msg(d.message||'创建失败','err');}
async function doForgot(){var e=document.getElementById('forgot-email').value;if(!e)return msg('请输入邮箱','err');var d=await api('/api/auth/forgot',{email:e});msg(d.message,d.ok?'ok':'err');if(d.ok)document.getElementById('reset-step').classList.remove('hidden');}
async function doReset(){var e=document.getElementById('forgot-email').value,c=document.getElementById('reset-code').value,p=document.getElementById('reset-password').value;var d=await api('/api/auth/reset',{email:e,code:c,password:p});if(d.ok){msg('密码重置成功，请登录','ok');showTab('login');}else msg(d.message||'重置失败','err');}
</script></body></html>""").encode("utf-8")


def _build_gate_context():
    """构建准入闸门上下文（v0.3.1）。"""
    return {
        "gpu": gpu_status(),
        "status": current_status(),
        "registry": REGISTRY,
    }


class Handler(BaseHTTPRequestHandler):
    """GMae HTTP 请求处理器。"""

    def _check_auth(self):
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
        self._json({"ok": False, "error": "unauthorized: please login first", "need_login": True}, 401)
        return False

    def _current_user(self):
        """获取当前登录用户邮箱。"""
        cookies = auth_mod.parse_cookie(self.headers.get("Cookie", ""))
        session_id = cookies.get(auth_mod.SESSION_COOKIE_NAME, "")
        sess = auth_mod.get_session(session_id)
        return sess.get("user_email") if sess else None

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path.startswith("/web/"):
            serve_static_file(self, self.path)
            return
        if self.path == "/" or self.path == "/index.html":
            if not auth_mod.has_admin() or not self._current_user():
                self._send(200, read_login_html(), "text/html")
            else:
                self._send(200, read_html(), "text/html")
        elif self.path == "/login":
            self._send(200, read_login_html(), "text/html")
        elif self.path == "/api/health":
            self._json(health_check())
        elif self.path == "/api/auth/status":
            self._json(auth_mod.auth_status())
        elif self.path == "/api/status":
            if not self._check_auth():
                return
            self._json(current_status())
        elif self.path.startswith("/api/logs"):
            if not self._check_auth():
                return
            qs = parse_qs(urlparse(self.path).query)
            limit = qs.get("limit", ["150"])[0]
            try:
                limit = int(limit)
            except ValueError:
                limit = 150
            self._json(read_logs(limit))
        elif self.path == "/api/registry":
            if not self._check_auth():
                return
            self._json(registry_view())
        elif self.path == "/api/comfy_events":
            if not self._check_auth():
                return
            self._json(comfy_events())
        elif self.path == "/api/desktop_vram":
            if not self._check_auth():
                return
            self._json(desktop_vram_detail())
        elif self.path == "/api/desktop/helper/status":
            if not self._check_auth():
                return
            self._json(helper_status())
        elif self.path.split("?")[0] == "/api/budget":
            if not self._check_auth():
                return
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
            self._json(budget_engine(context_overrides))
        elif self.path == "/api/scan":
            if not self._check_auth():
                return
            self._json(model_scan())
        elif self.path == "/api/queue":
            if not self._check_auth():
                return
            self._json(queue_snapshot())
        elif self.path == "/api/advice":
            if not self._check_auth():
                return
            self._json(vram_advice())
        elif self.path == "/api/hardware":
            if not self._check_auth():
                return
            self._json(_hardware_info())
        elif self.path == "/api/auto-protect/status":
            if not self._check_auth():
                return
            self._json(auto_protect_status())
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            data = {}

        if self.path == "/api/auth/setup":
            ok, msg = auth_mod.setup_admin(data.get("email", ""), data.get("password", ""))
            self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            return
        elif self.path == "/api/auth/login":
            ok, user = auth_mod.authenticate(data.get("email", ""), data.get("password", ""))
            if ok:
                session_id = auth_mod.create_session(user["email"], remember=data.get("remember", False))
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", "{}={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(
                    auth_mod.SESSION_COOKIE_NAME, session_id,
                    auth_mod.SESSION_REMEMBER_TTL if data.get("remember") else auth_mod.SESSION_DEFAULT_TTL))
                body = json.dumps({"ok": True, "message": "登录成功", "email": user["email"]}, ensure_ascii=False).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"ok": False, "error": "邮箱或密码不正确"}, 401)
            return
        elif self.path == "/api/auth/forgot":
            ok, msg = auth_mod.generate_reset_code(data.get("email", ""))
            self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            return
        elif self.path == "/api/auth/reset":
            ok, msg = auth_mod.reset_password(data.get("email", ""), data.get("code", ""), data.get("password", ""))
            self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            return

        if not self._check_auth():
            return
        invalidate_status_cache()
        if self.path == "/api/scene":
            self._json(scene_switch(data.get("scene", "")))
        elif self.path == "/api/combo":
            self._json(combo_switch(data.get("combo", "")))
        elif self.path == "/api/free":
            result = free_all()
            invalidate_status_cache()
            self._json(result)
        elif self.path == "/api/guard":
            if data.get("action") == "kick":
                self._json(gpu_guard_kick(data.get("pid", "")))
            else:
                self._json(gpu_guard_evict() if data.get("evict") else gpu_guard_check())
        elif self.path == "/api/qos/status":
            self._json(qos_status())
        elif self.path == "/api/qos/check":
            self._json(qos_check())
        elif self.path == "/api/qos/execute":
            self._json(qos_execute_suggestion(data.get("suggestion_id", "")))
        elif self.path == "/api/auto-protect/config":
            self._json(auto_protect_config(data))
        elif self.path == "/api/service":
            self._json(service_action(data.get("name", ""), data.get("action", "")))
        elif self.path == "/api/model":
            self._json(model_action(data.get("name", ""), data.get("action", "")))
        elif self.path == "/api/desktop/kill":
            self._json(desktop_kill(data.get("pid", "")))
        elif self.path == "/api/container/stop":
            self._json(container_stop(data.get("name", "")))
        elif self.path == "/api/desktop/helper/start":
            self._json(helper_start())
        elif self.path == "/api/desktop/helper/stop":
            self._json(helper_stop())
        elif self.path == "/api/queue":
            self._json(queue_enqueue(data.get("model", ""), data.get("params", {})))
        elif self.path == "/api/queue/cancel":
            self._json(queue_cancel(data.get("id", "")))
        elif self.path == "/api/admission":
            if not _V031_MODULES:
                self._json({"ok": False, "error": "admission_gate module not available"}, 503)
            else:
                import admission_gate
                ctx = _build_gate_context()
                result = admission_gate.check(
                    action=data.get("action", ""),
                    args=data.get("args", {}),
                    ctx=ctx
                )
                self._json(result)
        elif self.path == "/api/scan/register":
            self._json(scan_register(data.get("source", "comfyui"), data.get("name", ""),
                                     data.get("vram_gb"), data.get("category", "image")))
        elif self.path == "/api/auth/logout":
            cookies = auth_mod.parse_cookie(self.headers.get("Cookie", ""))
            session_id = cookies.get(auth_mod.SESSION_COOKIE_NAME, "")
            auth_mod.destroy_session(session_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "{}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0".format(auth_mod.SESSION_COOKIE_NAME))
            body = json.dumps({"ok": True, "message": "已登出"}, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        elif self.path == "/api/auth/change-password":
            email = self._current_user()
            ok, msg = auth_mod.change_password(email or "", data.get("old_password", ""), data.get("new_password", ""))
            self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            return
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass
