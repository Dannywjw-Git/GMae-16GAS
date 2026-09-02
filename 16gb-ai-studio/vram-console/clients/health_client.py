#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健康探测 HTTP 客户端（P1-3 外部服务封装）

封装各类服务的健康探测 HTTP 调用，提供统一接口：
- HTTP 健康检查（带超时、重试）
- TCP 端口探测
- 服务状态聚合

使用方式：
    from clients.health_client import health_client, HealthResult

    # HTTP 健康检查
    result = health_client.http_check("http://127.0.0.1:8188/system_stats")
    if result.ok:
        print("ComfyUI 运行中")

    # 批量探测
    results = health_client.check_all([
        {"name": "comfyui", "url": "http://127.0.0.1:8188/system_stats"},
        {"name": "ollama", "url": "http://127.0.0.1:11434/api/tags"},
    ])
"""
import json
import time
import socket
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed


@dataclass
class HealthResult:
    """健康探测结果（统一返回对象）"""
    ok: bool = False
    name: str = ""
    url: str = ""
    status_code: int = 0
    response_time_ms: float = 0.0
    error: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "url": self.url,
            "status_code": self.status_code,
            "response_time_ms": self.response_time_ms,
            "error": self.error,
            "data": self.data,
        }


class HealthClient:
    """健康探测客户端（线程安全）"""

    def __init__(self, default_timeout: float = 5.0, max_retries: int = 1):
        """初始化健康探测客户端

        Args:
            default_timeout: 默认超时时间（秒）
            max_retries: 默认重试次数
        """
        self._default_timeout = default_timeout
        self._max_retries = max_retries

    def http_check(
        self,
        url: str,
        name: str = "",
        timeout: Optional[float] = None,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        expected_status: int = 200,
        retries: Optional[int] = None,
    ) -> HealthResult:
        """HTTP 健康检查

        Args:
            url: 检查的 URL
            name: 服务名称（用于标识）
            timeout: 超时时间（秒）
            method: HTTP 方法
            headers: 请求头
            expected_status: 期望的 HTTP 状态码
            retries: 重试次数

        Returns:
            HealthResult 统一结果对象
        """
        if timeout is None:
            timeout = self._default_timeout
        if retries is None:
            retries = self._max_retries

        result = HealthResult(name=name, url=url)
        last_error = None

        for attempt in range(retries + 1):
            start_time = time.time()
            try:
                req = urllib.request.Request(url, method=method, headers=headers or {})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    result.status_code = resp.status
                    result.response_time_ms = (time.time() - start_time) * 1000
                    result.ok = resp.status == expected_status
                    if not result.ok:
                        result.error = f"期望状态码 {expected_status}，实际 {resp.status}"
                    # 尝试解析响应体
                    try:
                        raw = resp.read().decode("utf-8")
                        result.data = json.loads(raw)
                    except Exception:
                        pass
                    return result
            except urllib.error.HTTPError as e:
                result.status_code = e.code
                result.response_time_ms = (time.time() - start_time) * 1000
                result.ok = e.code == expected_status
                last_error = f"HTTP {e.code}: {e.reason}"
                result.error = last_error
            except urllib.error.URLError as e:
                result.response_time_ms = (time.time() - start_time) * 1000
                last_error = f"连接失败: {e.reason}"
                result.error = last_error
            except TimeoutError:
                result.response_time_ms = (time.time() - start_time) * 1000
                last_error = f"请求超时（{timeout}秒）"
                result.error = last_error
            except Exception as e:
                result.response_time_ms = (time.time() - start_time) * 1000
                last_error = f"异常: {type(e).__name__}: {e}"
                result.error = last_error

            # 重试前短暂等待
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))

        result.ok = False
        result.error = last_error
        return result

    def tcp_check(
        self,
        host: str,
        port: int,
        name: str = "",
        timeout: Optional[float] = None,
    ) -> HealthResult:
        """TCP 端口探测

        Args:
            host: 主机地址
            port: 端口号
            name: 服务名称
            timeout: 超时时间（秒）

        Returns:
            HealthResult
        """
        if timeout is None:
            timeout = self._default_timeout

        result = HealthResult(name=name, url=f"tcp://{host}:{port}")
        start_time = time.time()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.close()
            result.ok = True
            result.response_time_ms = (time.time() - start_time) * 1000
        except socket.timeout:
            result.error = f"连接超时（{timeout}秒）"
            result.response_time_ms = (time.time() - start_time) * 1000
        except ConnectionRefusedError:
            result.error = "连接被拒绝"
            result.response_time_ms = (time.time() - start_time) * 1000
        except Exception as e:
            result.error = f"异常: {type(e).__name__}: {e}"
            result.response_time_ms = (time.time() - start_time) * 1000

        return result

    def check_all(
        self,
        targets: List[Dict[str, Any]],
        max_workers: int = 5,
    ) -> List[HealthResult]:
        """批量健康检查（并发执行）

        Args:
            targets: 检查目标列表，每项包含 name/url/type 等
            max_workers: 最大并发数

        Returns:
            HealthResult 列表
        """
        results: List[HealthResult] = []

        def _check(target: Dict[str, Any]) -> HealthResult:
            check_type = target.get("type", "http")
            name = target.get("name", target.get("url", ""))

            if check_type == "tcp":
                return self.tcp_check(
                    host=target["host"],
                    port=target["port"],
                    name=name,
                    timeout=target.get("timeout"),
                )
            else:
                return self.http_check(
                    url=target["url"],
                    name=name,
                    timeout=target.get("timeout"),
                    method=target.get("method", "GET"),
                    headers=target.get("headers"),
                    expected_status=target.get("expected_status", 200),
                )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_check, t): t for t in targets}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    target = futures[future]
                    results.append(HealthResult(
                        ok=False,
                        name=target.get("name", ""),
                        url=target.get("url", ""),
                        error=f"执行异常: {e}",
                    ))

        return results

    def summarize(self, results: List[HealthResult]) -> Dict[str, Any]:
        """汇总健康检查结果

        Args:
            results: 健康检查结果列表

        Returns:
            汇总信息（总数/正常数/异常数/平均响应时间等）
        """
        total = len(results)
        ok_count = sum(1 for r in results if r.ok)
        fail_count = total - ok_count
        avg_response = (
            sum(r.response_time_ms for r in results) / total if total > 0 else 0.0
        )
        failed_services = [r.name for r in results if not r.ok]

        return {
            "total": total,
            "ok": ok_count,
            "failed": fail_count,
            "all_ok": fail_count == 0,
            "avg_response_time_ms": round(avg_response, 1),
            "failed_services": failed_services,
            "details": [r.to_dict() for r in results],
        }


# 全局单例
health_client = HealthClient(default_timeout=5.0, max_retries=1)
