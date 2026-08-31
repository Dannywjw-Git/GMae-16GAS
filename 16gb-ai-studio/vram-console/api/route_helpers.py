#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae HTTP 路由辅助函数
- 静态文件服务、健康检查、日志读取、registry 视图、HTML 读取、准入闸门上下文构建
"""
import json
import os
import time
import urllib.request
from core.logger import log_event, log_error, LOG_FILE
from core.config import (WEB_DIR, LEGACY_HTML, FRONTEND_VERSION, BASE_DIR, REGISTRY)
from services.status import current_status
from gpu.monitor import gpu_status
from services.scene import _sync_ollama_models, _sync_comfyui_models

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


def serve_static_file(handler, path: str) -> None:
    """服务 web/ 目录下的静态文件（CSS/JS/图片/字体）"""
    rel_path = path[5:] if path.startswith("/web/") else path
    rel_path = rel_path.replace("..", "").lstrip("/")
    full_path = os.path.join(WEB_DIR, rel_path)
    if not os.path.isfile(full_path):
        handler._json({"ok": False, "error": "file not found"}, 404)
        return
    ext = os.path.splitext(full_path)[1].lower()
    content_type = MIME_TYPES.get(ext, "application/octet-stream")
    try:
        with open(full_path, "rb") as f:
            data = f.read()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        handler.wfile.write(data)
    except Exception as e:
        handler._json({"ok": False, "error": str(e)}, 500)


def health_check() -> dict:
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


def read_logs(limit: int = 150) -> dict:
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


def registry_view() -> dict:
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


def read_html() -> bytes:
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


def read_login_html() -> bytes:
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


def build_gate_context():
    """构建准入闸门上下文（v0.3.1），返回 GateContext 对象。"""
    from engine.admission_gate import GateContext
    gpu = gpu_status()
    status = current_status()
    # 提取已加载模型
    ollama_loaded = []
    ollama_data = status.get("ollama", {})
    if isinstance(ollama_data, dict):
        for m in ollama_data.get("loaded", []) or ollama_data.get("models", []):
            if isinstance(m, dict):
                ollama_loaded.append({"name": m.get("name", ""), "size_gb": m.get("size_gb", 0)})
    comfy_loaded = []
    comfy_data = status.get("comfyui_models", [])
    if isinstance(comfy_data, list):
        for m in comfy_data:
            if isinstance(m, dict):
                comfy_loaded.append({
                    "id": m.get("id", m.get("name", "")),
                    "name": m.get("name", ""),
                    "vram_gb": m.get("vram_gb", 0),
                    "exclusive": m.get("exclusive", False)
                })
    # 容器运行状态
    containers = status.get("containers", {})
    comfyui_running = any(c.get("name") == "comfyui" and c.get("running") for c in containers) if isinstance(containers, list) else False
    fooocus_running = any("fooocus" in str(c.get("name", "")).lower() and c.get("running") for c in containers) if isinstance(containers, list) else False
    return GateContext(
        vram_total_mb=gpu.get("total_mb", 16384),
        vram_used_mb=gpu.get("used_mb", 0),
        vram_free_mb=gpu.get("free_mb", 16384),
        base_noise_mb=3480,  # 从硬件档案缓存
        current_scene=status.get("scene", "dialogue"),
        loaded_ollama_models=ollama_loaded,
        loaded_comfy_models=comfy_loaded,
        comfyui_running=comfyui_running,
        fooocus_running=fooocus_running,
        ollama_serve_count=1,
        registry_models=REGISTRY.get("models", {}) if isinstance(REGISTRY, dict) else {},
        danger_thresholds={}
    )
