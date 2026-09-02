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
    """服务 web/ 目录下的静态文件（CSS/JS/图片/字体）。支持 /web/ /css/ /js/ /assets/ 前缀。"""
    rel_path = path
    if rel_path.startswith("/web/"):
        rel_path = rel_path[5:]
    elif rel_path.startswith("/css/") or rel_path.startswith("/js/") or rel_path.startswith("/assets/"):
        rel_path = rel_path.lstrip("/")
    rel_path = rel_path.replace("..", "").lstrip("/")
    full_path = os.path.join(WEB_DIR, rel_path)
    if not os.path.isfile(full_path):
        handler._json({"ok": False, "error": "file not found (frontend archived)"}, 404)
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
    # 获取已加载模型（含实际显存占用）
    loaded_models = []
    try:
        from services.ollama import ollama_ps
        ps_result = ollama_ps()
        if ps_result.get("ok"):
            loaded_models = ps_result.get("models", [])
    except Exception as e:
        log_error("exception_suppressed", error=e, context="route_helpers.py:130")
    return {
        "ok": True,
        "version": reg.get("version", ""),
        "last_updated": reg.get("last_updated", ""),
        "sync": True,
        "ollama_models": _sync_ollama_models(),
        "ollama_combos": reg.get("ollama", {}).get("combos", {}),
        "comfyui_models": _sync_comfyui_models(),
        "loaded_models": loaded_models,
        "loaded_models_count": len(loaded_models),
        "loaded_vram_gb": round(sum(m.get("size_gb", 0) for m in loaded_models), 1),
        "containers": reg.get("containers", []),
        "scenes": reg.get("scenes", {}),
        "system": reg.get("system", {}),
        "gpu_guard": reg.get("gpu_guard", {}),
    }


# === 前端重构中占位页（2026-09-01：v1/v2 前端全部存档停用，后续重做）===
PLACEHOLDER_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GMae 指挥家 — API 服务运行中</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
  .card{background:#1e293b;border-radius:16px;padding:40px;max-width:680px;width:100%;
        box-shadow:0 4px 24px rgba(0,0,0,0.3)}
  .brand{display:flex;align-items:center;gap:12px;margin-bottom:8px}
  .logo{width:40px;height:40px;background:linear-gradient(135deg,#0d9488,#0891b2);
        border-radius:10px;display:flex;align-items:center;justify-content:center;
        font-weight:700;font-size:18px;color:#fff}
  h1{font-size:22px;color:#f1f5f9}
  .subtitle{color:#94a3b8;font-size:14px;margin-bottom:24px}
  .status{display:inline-flex;align-items:center;gap:8px;background:#0f2e22;color:#4ade80;
          padding:6px 14px;border-radius:20px;font-size:13px;font-weight:500;margin-bottom:24px}
  .status-dot{width:8px;height:8px;background:#4ade80;border-radius:50%;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
  .notice{background:#1e293b;border-left:3px solid #0d9488;padding:14px 18px;
          border-radius:0 8px 8px 0;margin-bottom:24px;font-size:14px;color:#cbd5e1;line-height:1.6}
  .notice strong{color:#0d9488}
  .notice code{background:#0f172a;padding:1px 5px;border-radius:3px;font-family:monospace;font-size:12px}
  h2{font-size:13px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px;margin-top:8px;font-weight:600}
  .api-list{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:20px}
  .api-item{display:flex;align-items:center;gap:8px;font-size:12px;padding:6px 10px;
            background:#0f172a;border-radius:6px;font-family:monospace}
  .method{font-weight:700;font-size:10px;padding:2px 6px;border-radius:4px;min-width:40px;text-align:center}
  .method.get{background:#1e3a5f;color:#60a5fa}
  .method.post{background:#3b1f3f;color:#c084fc}
  .api-path{color:#cbd5e1}
  .cli-hint{background:#0f172a;border-radius:8px;padding:14px 18px;font-size:13px;
            color:#94a3b8;line-height:1.9;margin-bottom:20px}
  .cli-hint code{background:#1e293b;padding:2px 6px;border-radius:4px;color:#0d9488;font-family:monospace}
  .footer{text-align:center;color:#475569;font-size:12px;margin-top:24px;padding-top:16px;border-top:1px solid #334155}
  .footer a{color:#0d9488;text-decoration:none}
  .footer span{margin:0 6px}
</style>
</head>
<body>
<div class="card">
  <div class="brand">
    <div class="logo">G</div>
    <div>
      <h1>GPU Maestro · 显存指挥家</h1>
      <div class="subtitle">Prism Engine (P-Eng) · 16G-AI-Studio 调度中心</div>
    </div>
  </div>
  <div class="status"><span class="status-dot"></span>API 服务运行中 · 端口 8787</div>
  <div class="notice">
    <strong>前端重构中</strong> — Web UI 已全部存档停用（v1 单文件版 + v2 模块化版均已移入 <code>legacy/</code>）。
    全新前端正在规划中，后续将以更清晰的信息架构和组件化体系重做。
    在此期间，所有 API 端点和 <code>gmae-cli</code> 命令行工具正常可用。
  </div>
  <h2>常用 API 端点</h2>
  <div class="api-list">
    <div class="api-item"><span class="method get">GET</span><span class="api-path">/api/health</span></div>
    <div class="api-item"><span class="method get">GET</span><span class="api-path">/api/status</span></div>
    <div class="api-item"><span class="method get">GET</span><span class="api-path">/api/registry</span></div>
    <div class="api-item"><span class="method get">GET</span><span class="api-path">/api/budget</span></div>
    <div class="api-item"><span class="method get">GET</span><span class="api-path">/api/queue</span></div>
    <div class="api-item"><span class="method get">GET</span><span class="api-path">/api/logs</span></div>
    <div class="api-item"><span class="method get">GET</span><span class="api-path">/api/scan</span></div>
    <div class="api-item"><span class="method get">GET</span><span class="api-path">/api/advice</span></div>
    <div class="api-item"><span class="method post">POST</span><span class="api-path">/api/scene</span></div>
    <div class="api-item"><span class="method post">POST</span><span class="api-path">/api/free</span></div>
    <div class="api-item"><span class="method post">POST</span><span class="api-path">/api/queue</span></div>
    <div class="api-item"><span class="method post">POST</span><span class="api-path">/api/guard</span></div>
  </div>
  <h2>命令行工具（gmae-cli）</h2>
  <div class="cli-hint">
    <code>gmae status</code> — 全景状态（显存/场景/模型/QoS）<br>
    <code>gmae vram free</code> — 一键释放显存<br>
    <code>gmae scene switch comfyui</code> — 切换场景<br>
    <code>gmae model list</code> — 模型登记台<br>
    <code>gmae queue submit sdxl --prompt "a cat"</code> — 提交生成任务<br>
    <code>gmae logs -n 20</code> — 最近日志<br>
    共 10 个命令组，覆盖全部 30+ API。安装：<code>pip install -e .</code>
  </div>
  <div class="footer">
    GMae-16GAS · vram-console API · 前端存档日期 2026-09-01
    <span>·</span>
    <a href="/api/health">健康检查</a>
    <span>·</span>
    <a href="/api/status">状态查询</a>
  </div>
</div>
</body>
</html>""".encode("utf-8")


def read_html() -> bytes:
    """返回新前端 SPA 入口（web/index.html）。S4 前端重做。"""
    index_path = os.path.join(WEB_DIR, "index.html")
    try:
        with open(index_path, "rb") as f:
            return f.read()
    except Exception:
        return PLACEHOLDER_HTML


def read_login_html() -> bytes:
    """登录页返回新前端 SPA（登录功能由前端 JS 处理）。"""
    return read_html()


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
