#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper 进程 HTTP API 客户端（P1-3 外部服务封装）

封装显存采集助手（Helper）的 HTTP API 调用，提供统一接口：
- 健康检查
- 进程级显存探测
- 配置查询/更新
- 进程管理（启动/停止）

使用方式：
    from clients.helper_client import helper_client, HelperResult

    # 健康检查
    result = helper_client.health()
    if result.ok:
        print("Helper 运行中")

    # 进程级显存探测
    result = helper_client.process_vram()
    if result.ok:
        print(result.data)
"""
import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class HelperResult:
    """Helper API 调用结果（统一返回对象）"""
    ok: bool = False
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    status_code: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
        }


class HelperClient:
    """Helper HTTP API 客户端（线程安全）"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8788,
        token: str = "",
        default_timeout: float = 5.0,
    ):
        """初始化 Helper 客户端

        Args:
            host: Helper 服务地址
            port: Helper 服务端口
            token: API 认证 token
            default_timeout: 默认超时时间（秒）
        """
        self._host = host
        self._port = port
        self._token = token
        self._default_timeout = default_timeout
        self._base_url = f"http://{host}:{port}"

    def set_token(self, token: str) -> None:
        """设置 API token"""
        self._token = token

    def _request(
        self,
        path: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> HelperResult:
        """发送 HTTP 请求到 Helper

        Args:
            path: API 路径（如 /api/health）
            method: HTTP 方法（GET/POST）
            data: POST 请求体
            timeout: 超时时间（秒）

        Returns:
            HelperResult 统一结果对象
        """
        if timeout is None:
            timeout = self._default_timeout

        url = f"{self._base_url}{path}"
        result = HelperResult()
        start_time = time.time()

        try:
            headers = {"X-API-Key": self._token}
            body = None

            if method == "POST" and data is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(data).encode("utf-8")

            req = urllib.request.Request(url, data=body, headers=headers, method=method)

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result.status_code = resp.status
                raw = resp.read().decode("utf-8")
                try:
                    result.data = json.loads(raw)
                except json.JSONDecodeError:
                    result.data = {"raw": raw}
                result.ok = resp.status == 200
                if not result.ok:
                    result.error = f"HTTP {resp.status}"

        except urllib.error.HTTPError as e:
            result.status_code = e.code
            result.ok = False
            result.error = f"HTTP {e.code}: {e.reason}"
            try:
                result.data = json.loads(e.read().decode("utf-8"))
            except Exception:
                pass
        except urllib.error.URLError as e:
            result.ok = False
            result.error = f"连接失败: {e.reason}"
        except TimeoutError:
            result.ok = False
            result.error = f"请求超时（{timeout}秒）"
        except Exception as e:
            result.ok = False
            result.error = f"请求异常: {type(e).__name__}: {e}"

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def health(self, timeout: float = 0.5) -> HelperResult:
        """健康检查（短超时，避免拖慢冷路径）

        Args:
            timeout: 超时时间（秒），默认0.5秒

        Returns:
            HelperResult，ok=True 表示 Helper 运行中
        """
        return self._request("/api/health", timeout=timeout)

    def is_running(self) -> bool:
        """快速检查 Helper 是否在运行（返回布尔值）"""
        return self.health().ok

    def process_vram(self, timeout: float = 10.0) -> HelperResult:
        """获取进程级显存占用明细

        Returns:
            HelperResult，data 包含进程列表和显存占用
        """
        return self._request("/api/process_vram", timeout=timeout)

    def gpu_processes(self, timeout: float = 10.0) -> HelperResult:
        """获取 GPU 进程列表（穿透 WSL2/Docker）

        Returns:
            HelperResult，data 包含 GPU 进程明细
        """
        return self._request("/api/gpu_processes", timeout=timeout)

    def get_config(self, timeout: float = 5.0) -> HelperResult:
        """获取 Helper 配置

        Returns:
            HelperResult，data 包含配置信息
        """
        return self._request("/api/config", timeout=timeout)

    def update_config(self, config: Dict[str, Any], timeout: float = 5.0) -> HelperResult:
        """更新 Helper 配置

        Args:
            config: 配置更新项

        Returns:
            HelperResult
        """
        return self._request("/api/config", method="POST", data=config, timeout=timeout)

    def stop_helper(self, timeout: float = 5.0) -> HelperResult:
        """停止 Helper 进程

        Returns:
            HelperResult
        """
        return self._request("/api/stop", method="POST", timeout=timeout)

    def desktop_kill(self, process_name: str, timeout: float = 10.0) -> HelperResult:
        """终止桌面进程（经 Helper 代理，UAC 提权）

        Args:
            process_name: 进程名（如 python.exe）

        Returns:
            HelperResult
        """
        return self._request(
            "/api/desktop_kill",
            method="POST",
            data={"process_name": process_name},
            timeout=timeout,
        )


# 全局单例（token 从 config.json 读取，延迟初始化）
_helper_client: Optional[HelperClient] = None


def get_helper_client() -> HelperClient:
    """获取全局 HelperClient 单例（延迟初始化，自动读取 token）"""
    global _helper_client
    if _helper_client is None:
        # 从 config.json 读取 token
        token = ""
        try:
            import os
            from core.config import BASE_DIR
            config_file = os.path.join(BASE_DIR, "config.json")
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    token = cfg.get("helper_token", "")
        except Exception:
            pass
        _helper_client = HelperClient(token=token)
    return _helper_client


# 便捷全局实例（首次访问时自动初始化）
helper_client: HelperClient = None  # type: ignore


def __getattr__(name):
    """模块级延迟初始化：首次访问 helper_client 时自动创建"""
    if name == "helper_client":
        return get_helper_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
