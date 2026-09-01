#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 服务健康探测引擎
- 动态服务清单（从 registry.json 的 monitored_services 读取）
- 4种探测类型：docker / http / tcp / custom
- 后台线程定期探测，记录状态/延迟/错误率
- 状态变化时触发结构化事件
"""
import json
import os
import time
import socket
import threading
import subprocess
import datetime
from typing import Optional, Dict, Any, List
from core.config import REGISTRY
from core.events import events, LEVEL_WARNING, LEVEL_ERROR, LEVEL_INFO

# === 探测状态 ===
STATUS_RUNNING = "running"
STATUS_STOPPED = "stopped"
STATUS_UNREACHABLE = "unreachable"
STATUS_TIMEOUT = "timeout"
STATUS_UNKNOWN = "unknown"

# 默认探测间隔（秒）
DEFAULT_PROBE_INTERVAL = 10
DEFAULT_TIMEOUT = 5


class HealthProbe:
    """服务健康探测引擎（单例）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._services: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._load_services()

    def _load_services(self):
        """从 registry.json 加载监控服务配置"""
        monitored = REGISTRY.get("monitored_services", [])
        if not monitored:
            # 默认服务清单（从 containers 配置推断）
            monitored = self._auto_discover()
            # 持久化到 registry.json
            self._save_monitored_services(monitored)

        for svc in monitored:
            sid = svc.get("id", svc.get("name", "unknown"))
            self._services[sid] = {
                "id": sid,
                "name": svc.get("name", sid),
                "type": svc.get("type", "http"),
                "container": svc.get("container"),
                "url": svc.get("url"),
                "port": svc.get("port"),
                "host": svc.get("host", "127.0.0.1"),
                "probe_interval": svc.get("probe_interval", DEFAULT_PROBE_INTERVAL),
                "timeout": svc.get("timeout", DEFAULT_TIMEOUT),
                "category": svc.get("category", "general"),
                "enabled": svc.get("enabled", True),
            }
            # 初始化结果
            if sid not in self._results:
                self._results[sid] = {
                    "status": STATUS_UNKNOWN,
                    "latency_ms": None,
                    "error_rate": 0.0,
                    "last_check": None,
                    "last_error": None,
                    "history": [],
                    "consecutive_failures": 0,
                    "total_checks": 0,
                    "total_failures": 0,
                }

    def _save_monitored_services(self, services: List[Dict[str, Any]]):
        """保存监控服务配置到 registry.json"""
        try:
            reg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "registry.json")
            with open(reg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["monitored_services"] = services
            with open(reg_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[health-probe] save config error: {e}")

    def _auto_discover(self) -> List[Dict[str, Any]]:
        """自动发现服务（从 registry.json 的 containers 配置，支持字典和列表两种格式）"""
        containers = REGISTRY.get("containers", {})
        services = []
        defaults = {
            "comfyui": {"type": "docker", "container": "comfyui", "port": 8188, "url": "http://127.0.0.1:8188/system_stats", "category": "generation"},
            "ollama": {"type": "docker", "container": "ollama", "port": 11434, "url": "http://127.0.0.1:11434/api/tags", "category": "llm"},
            "fooocus": {"type": "docker", "container": "fooocus", "port": 7865, "url": "http://127.0.0.1:7865/", "category": "generation"},
            "open-webui": {"type": "docker", "container": "open-webui-open-webui-1", "port": 3000, "url": "http://127.0.0.1:3000/health", "category": "ui"},
            "immich": {"type": "docker", "container": "immich_server", "port": 2283, "url": "http://127.0.0.1:2283/api/server/ping", "category": "media"},
            "searxng": {"type": "docker", "container": "searxng", "port": 8888, "url": "http://127.0.0.1:8888/healthz", "category": "search"},
        }
        # 兼容字典和列表两种格式
        if isinstance(containers, dict):
            names = list(containers.keys())
        elif isinstance(containers, list):
            names = [c.get("name") for c in containers if isinstance(c, dict) and c.get("name")]
        else:
            names = []
        for name in names:
            if name in defaults:
                d = defaults[name]
                services.append({
                    "id": name,
                    "name": name,
                    "type": d["type"],
                    "container": d["container"],
                    "port": d["port"],
                    "url": d["url"],
                    "category": d["category"],
                    "enabled": True,
                })
        return services

    def start(self):
        """启动探测线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._probe_loop, daemon=True, name="health-probe")
        self._thread.start()
        events.log("health_probe_started", service="health_probe", message=f"服务健康探测启动，监控 {len(self._services)} 个服务")

    def stop(self):
        """停止探测线程"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _probe_loop(self):
        """探测主循环"""
        while self._running:
            try:
                for sid, svc in self._services.items():
                    if not svc.get("enabled", True):
                        continue
                    # 检查是否到探测时间
                    result = self._results.get(sid, {})
                    last_check = result.get("last_check")
                    interval = svc.get("probe_interval", DEFAULT_PROBE_INTERVAL)
                    if last_check and (time.time() - last_check) < interval:
                        continue
                    # 执行探测
                    self._probe_service(sid, svc)
            except Exception as e:
                print(f"[health-probe] loop error: {e}")
            time.sleep(1)

    def _probe_service(self, sid: str, svc: Dict[str, Any]):
        """探测单个服务"""
        probe_type = svc.get("type", "http")
        timeout = svc.get("timeout", DEFAULT_TIMEOUT)
        start = time.time()

        try:
            if probe_type == "docker":
                status, error = self._probe_docker(svc, timeout)
            elif probe_type == "http":
                status, error = self._probe_http(svc, timeout)
            elif probe_type == "tcp":
                status, error = self._probe_tcp(svc, timeout)
            elif probe_type == "custom":
                status, error = self._probe_custom(svc, timeout)
            else:
                status, error = STATUS_UNKNOWN, f"未知探测类型: {probe_type}"
        except Exception as e:
            status, error = STATUS_UNREACHABLE, str(e)

        latency_ms = int((time.time() - start) * 1000)
        self._update_result(sid, status, latency_ms, error)

    def _probe_docker(self, svc: Dict[str, Any], timeout: int) -> tuple:
        """Docker 容器探测"""
        container = svc.get("container")
        if not container:
            return STATUS_UNKNOWN, "未配置容器名"
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container],
                capture_output=True, text=True, timeout=timeout
            )
            if result.returncode != 0:
                return STATUS_STOPPED, result.stderr.strip() or "容器不存在"
            running = result.stdout.strip() == "true"
            if not running:
                return STATUS_STOPPED, "容器未运行"
            # 容器运行中，再探测端口
            port = svc.get("port")
            if port:
                tcp_ok, tcp_err = self._probe_tcp(svc, timeout)
                if tcp_ok != STATUS_RUNNING:
                    return STATUS_UNREACHABLE, f"容器运行但端口不可达: {tcp_err}"
            return STATUS_RUNNING, None
        except subprocess.TimeoutExpired:
            return STATUS_TIMEOUT, "docker inspect 超时"
        except Exception as e:
            return STATUS_UNREACHABLE, str(e)

    def _probe_http(self, svc: Dict[str, Any], timeout: int) -> tuple:
        """HTTP 探测"""
        url = svc.get("url")
        if not url:
            return STATUS_UNKNOWN, "未配置 URL"
        try:
            import urllib.request
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status in (200, 301, 302, 304):
                    return STATUS_RUNNING, None
                return STATUS_UNREACHABLE, f"HTTP {resp.status}"
        except Exception as e:
            return STATUS_UNREACHABLE, str(e)

    def _probe_tcp(self, svc: Dict[str, Any], timeout: int) -> tuple:
        """TCP 端口探测"""
        host = svc.get("host", "127.0.0.1")
        port = svc.get("port")
        if not port:
            return STATUS_UNKNOWN, "未配置端口"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return STATUS_RUNNING, None
            return STATUS_UNREACHABLE, f"端口 {port} 不可达"
        except socket.timeout:
            return STATUS_TIMEOUT, "连接超时"
        except Exception as e:
            return STATUS_UNREACHABLE, str(e)

    def _probe_custom(self, svc: Dict[str, Any], timeout: int) -> tuple:
        """自定义脚本探测"""
        script = svc.get("script")
        if not script:
            return STATUS_UNKNOWN, "未配置脚本"
        try:
            result = subprocess.run(script, shell=True, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                return STATUS_RUNNING, None
            return STATUS_UNREACHABLE, result.stderr.strip() or f"退出码 {result.returncode}"
        except subprocess.TimeoutExpired:
            return STATUS_TIMEOUT, "脚本执行超时"
        except Exception as e:
            return STATUS_UNREACHABLE, str(e)

    def _update_result(self, sid: str, status: str, latency_ms: int, error: Optional[str]):
        """更新探测结果"""
        result = self._results.setdefault(sid, {
            "status": STATUS_UNKNOWN, "latency_ms": None, "error_rate": 0.0,
            "last_check": None, "last_error": None, "history": [],
            "consecutive_failures": 0, "total_checks": 0, "total_failures": 0,
        })

        old_status = result.get("status")
        result["status"] = status
        result["latency_ms"] = latency_ms
        result["last_check"] = time.time()
        result["last_error"] = error
        result["total_checks"] = result.get("total_checks", 0) + 1

        is_failure = status not in (STATUS_RUNNING,)
        if is_failure:
            result["consecutive_failures"] = result.get("consecutive_failures", 0) + 1
            result["total_failures"] = result.get("total_failures", 0) + 1
        else:
            result["consecutive_failures"] = 0

        # 计算错误率（最近10次）
        history = result.get("history", [])
        history.append({"ts": time.time(), "status": status, "latency_ms": latency_ms})
        if len(history) > 10:
            history = history[-10:]
        result["history"] = history
        failures = sum(1 for h in history if h["status"] != STATUS_RUNNING)
        result["error_rate"] = failures / len(history) if history else 0.0

        # 状态变化时记录事件
        if old_status != status and old_status != STATUS_UNKNOWN:
            svc_name = self._services.get(sid, {}).get("name", sid)
            if status == STATUS_RUNNING:
                events.log(
                    "service_recovered", level=LEVEL_INFO, service=sid,
                    message=f"服务 {svc_name} 恢复正常",
                    related_metrics={"latency_ms": latency_ms}
                )
            elif status in (STATUS_STOPPED, STATUS_UNREACHABLE, STATUS_TIMEOUT):
                events.log(
                    "service_down", level=LEVEL_ERROR, service=sid,
                    message=f"服务 {svc_name} 不可用: {error or status}",
                    related_metrics={"status": status, "error": error}
                )

    def get_status(self, sid: Optional[str] = None) -> Dict[str, Any]:
        """获取服务状态"""
        if sid:
            return self._results.get(sid, {})
        return {
            "services": {
                sid: {
                    **self._services.get(sid, {}),
                    **self._results.get(sid, {}),
                }
                for sid in self._services
            },
            "summary": self._get_summary(),
        }

    def _get_summary(self) -> Dict[str, Any]:
        """获取汇总信息"""
        total = len(self._services)
        running = sum(1 for r in self._results.values() if r.get("status") == STATUS_RUNNING)
        stopped = sum(1 for r in self._results.values() if r.get("status") == STATUS_STOPPED)
        unreachable = sum(1 for r in self._results.values() if r.get("status") in (STATUS_UNREACHABLE, STATUS_TIMEOUT))
        return {
            "total": total,
            "running": running,
            "stopped": stopped,
            "unreachable": unreachable,
            "unknown": total - running - stopped - unreachable,
        }

    def add_service(self, svc: Dict[str, Any]) -> bool:
        """动态添加监控服务"""
        sid = svc.get("id") or svc.get("name")
        if not sid:
            return False
        self._services[sid] = {
            "id": sid,
            "name": svc.get("name", sid),
            "type": svc.get("type", "http"),
            "container": svc.get("container"),
            "url": svc.get("url"),
            "port": svc.get("port"),
            "host": svc.get("host", "127.0.0.1"),
            "probe_interval": svc.get("probe_interval", DEFAULT_PROBE_INTERVAL),
            "timeout": svc.get("timeout", DEFAULT_TIMEOUT),
            "category": svc.get("category", "general"),
            "enabled": svc.get("enabled", True),
        }
        self._results[sid] = {
            "status": STATUS_UNKNOWN, "latency_ms": None, "error_rate": 0.0,
            "last_check": None, "last_error": None, "history": [],
            "consecutive_failures": 0, "total_checks": 0, "total_failures": 0,
        }
        # 持久化到 registry.json
        self._persist_services()
        return True

    def remove_service(self, sid: str) -> bool:
        """移除监控服务"""
        if sid not in self._services:
            return False
        del self._services[sid]
        self._results.pop(sid, None)
        # 持久化到 registry.json
        self._persist_services()
        return True

    def _persist_services(self):
        """将当前服务配置持久化到 registry.json"""
        services_list = list(self._services.values())
        self._save_monitored_services(services_list)

    def probe_now(self, sid: Optional[str] = None):
        """立即探测（不等待间隔）"""
        if sid:
            svc = self._services.get(sid)
            if svc:
                self._probe_service(sid, svc)
                return self._results.get(sid, {})
        else:
            for s, cfg in self._services.items():
                if cfg.get("enabled", True):
                    self._probe_service(s, cfg)
        return self.get_status()


# 全局单例
health_probe = HealthProbe()
