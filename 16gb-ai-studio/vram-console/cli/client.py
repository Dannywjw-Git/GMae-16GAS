#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae HTTP 客户端
封装调度中心全部 REST API，统一认证、错误处理、超时控制。
"""
import json
import urllib.request
import urllib.error
from typing import Optional

from .config import load_config, get_server_url


class GMaeClient:
    """GMae 调度中心 API 客户端。"""

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or load_config()
        self.timeout = self.cfg.get("timeout", 30)
        self.token = self.cfg.get("token", "")
        self.server = self.cfg.get("server", "http://127.0.0.1:8787")

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["X-API-Key"] = self.token
        return h

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        """发送 HTTP 请求，返回解析后的 JSON。"""
        url = get_server_url(self.cfg, path)
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {"ok": True}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except Exception:
                return {"ok": False, "error": f"HTTP {e.code}: {e.reason}", "raw": raw}
        except urllib.error.URLError as e:
            return {"ok": False, "error": f"连接失败: {e.reason}（server={self.server}）"}
        except Exception as e:
            return {"ok": False, "error": f"请求异常: {e}"}

    # ---- GET ----
    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body)

    # ============================================================
    # 健康与认证（公开）
    # ============================================================
    def health(self) -> dict:
        return self.get("/api/health")

    def auth_status(self) -> dict:
        return self.get("/api/auth/status")

    def login(self, email: str, password: str, remember: bool = False) -> dict:
        return self.post("/api/auth/login", {"email": email, "password": password, "remember": remember})

    # ============================================================
    # 状态查询
    # ============================================================
    def status(self) -> dict:
        return self.get("/api/status")

    def logs(self, limit: int = 150) -> dict:
        return self.get(f"/api/logs?limit={limit}")

    def registry(self) -> dict:
        return self.get("/api/registry")

    def hardware(self) -> dict:
        return self.get("/api/hardware")

    def advice(self) -> dict:
        return self.get("/api/advice")

    def comfy_events(self) -> dict:
        return self.get("/api/comfy_events")

    # ============================================================
    # 显存管理
    # ============================================================
    def free(self) -> dict:
        return self.post("/api/free", {})

    def budget(self, context_overrides: Optional[str] = None) -> dict:
        path = "/api/budget"
        if context_overrides:
            path += f"?context={context_overrides}"
        return self.get(path)

    def desktop_vram(self) -> dict:
        return self.get("/api/desktop_vram")

    # ============================================================
    # 场景与组合
    # ============================================================
    def scene_switch(self, scene: str) -> dict:
        return self.post("/api/scene", {"scene": scene})

    def combo_switch(self, combo: str) -> dict:
        return self.post("/api/combo", {"combo": combo})

    # ============================================================
    # 模型管理
    # ============================================================
    def model_action(self, name: str, action: str) -> dict:
        return self.post("/api/model", {"name": name, "action": action})

    def model_scan(self) -> dict:
        return self.get("/api/scan")

    def model_register(self, source: str, name: str, vram_gb: float = 0, category: str = "image") -> dict:
        return self.post("/api/scan/register", {
            "source": source, "name": name, "vram_gb": vram_gb, "category": category
        })

    # ============================================================
    # 任务队列
    # ============================================================
    def queue_list(self) -> dict:
        return self.get("/api/queue")

    def queue_submit(self, model: str, params: Optional[dict] = None) -> dict:
        return self.post("/api/queue", {"model": model, "params": params or {}})

    def queue_cancel(self, task_id: str) -> dict:
        return self.post("/api/queue/cancel", {"id": task_id})

    # ============================================================
    # 门卫
    # ============================================================
    def guard_check(self) -> dict:
        return self.post("/api/guard", {})

    def guard_evict(self) -> dict:
        return self.post("/api/guard", {"evict": True})

    def guard_kick(self, pid: str) -> dict:
        return self.post("/api/guard", {"action": "kick", "pid": pid})

    # ============================================================
    # 服务控制
    # ============================================================
    def service_action(self, name: str, action: str) -> dict:
        return self.post("/api/service", {"name": name, "action": action})

    def container_stop(self, name: str) -> dict:
        return self.post("/api/container/stop", {"name": name})

    # ============================================================
    # 桌面 Helper
    # ============================================================
    def helper_status(self) -> dict:
        return self.get("/api/desktop/helper/status")

    def helper_start(self) -> dict:
        return self.post("/api/desktop/helper/start", {})

    def helper_stop(self) -> dict:
        return self.post("/api/desktop/helper/stop", {})

    def desktop_kill(self, pid: str) -> dict:
        return self.post("/api/desktop/kill", {"pid": pid})

    # ============================================================
    # QoS 与自动保护
    # ============================================================
    def qos_status(self) -> dict:
        return self.get("/api/qos/status")

    def qos_check(self) -> dict:
        return self.post("/api/qos/check", {})

    def qos_execute(self, suggestion_id: str) -> dict:
        return self.post("/api/qos/execute", {"suggestion_id": suggestion_id})

    def auto_protect_status(self) -> dict:
        return self.get("/api/auto-protect/status")

    def auto_protect_config(self, config: dict) -> dict:
        return self.post("/api/auto-protect/config", config)

    # ============================================================
    # 准入闸门
    # ============================================================
    def admission(self, action: str, args: Optional[dict] = None) -> dict:
        return self.post("/api/admission", {"action": action, "args": args or {}})
