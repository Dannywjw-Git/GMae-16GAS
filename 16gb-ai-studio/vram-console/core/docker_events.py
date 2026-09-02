#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker 事件监听模块（S1.2 Docker Events API）

用 `docker events` 命令流式监听容器状态变化，维护内存中的容器状态表，
替代 /api/status 中的 docker exec ps 轮询，降低状态查询延迟。

核心类：
- DockerEventsMonitor: 后台线程监听 docker events，维护 container_states 字典

设计要点：
- 用 subprocess.Popen 启动 `docker events --format '{{json .}}'`，逐行读取
- 解析 JSON 事件，更新 container_states（running/exited）
- 线程安全（threading.Lock）
- 服务停止时优雅退出（daemon=True + stop() 方法）
- Windows 兼容：用 docker events 命令，不依赖 Docker SDK 或 TCP API
- 降级方案：docker events 启动失败时，is_available()=False，
  /api/status 回退到 docker exec ps
- 初始同步：用 docker ps 填充当前运行中的容器
- 状态变化回调：可选 on_state_change 回调，容器 start/stop/die 时触发
  （用于自动失效 status 缓存，确保 /api/status 返回最新数据）

使用方式：
    from core.docker_events import docker_events
    from core.status_cache import status_cache

    # 启动时注册回调（容器状态变化时失效缓存）
    docker_events.on_state_change = lambda name, action: status_cache.invalidate()
    docker_events.start()

    # 查询容器状态
    state = docker_events.get_container_state("ollama")  # "running" | "exited" | None

    # 停止时
    docker_events.stop()
"""

import subprocess
import json
import threading
import time
from typing import Dict, Optional, Callable
from core.event_bus import event_bus


class DockerEventsMonitor:
    """Docker 事件监听器。

    后台线程运行 `docker events` 命令，逐行解析事件，维护容器状态表。
    容器状态变化时可选触发回调（如失效 status 缓存）。
    """

    def __init__(self, on_state_change: Optional[Callable[[str, str], None]] = None):
        self._states: Dict[str, str] = {}  # container_name -> "running" | "exited"
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._available = False  # docker events 是否成功启动
        self._on_state_change = on_state_change  # 状态变化回调 (container_name, action) -> None

    def start(self) -> bool:
        """启动事件监听线程。

        Returns:
            True 表示成功启动，False 表示失败（降级，调用方应回退到 docker exec）。
        """
        if self._running:
            return self._available

        try:
            # 启动 docker events 流式监听
            self._process = subprocess.Popen(
                ["docker", "events", "--format", "{{json .}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._running = True
            self._available = True

            # 启动后台读取线程
            self._thread = threading.Thread(target=self._read_events, daemon=True)
            self._thread.start()

            # 初始同步：用 docker ps 填充当前运行中的容器
            self._initial_sync()

            return True
        except Exception:
            self._available = False
            self._running = False
            return False

    def stop(self) -> None:
        """停止事件监听，释放子进程资源。"""
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception as e:
                    log_error("exception_suppressed", error=e, context="docker_events.py:107")
            self._process = None
        self._thread = None
        self._available = False

    def get_container_state(self, container_name: str) -> Optional[str]:
        """获取容器状态。

        Args:
            container_name: 容器名称

        Returns:
            "running" | "exited" | None（None 表示未知：监控不可用或容器未出现过）
        """
        with self._lock:
            return self._states.get(container_name)

    def get_all_states(self) -> Dict[str, str]:
        """获取所有容器状态的副本。"""
        with self._lock:
            return dict(self._states)

    def is_available(self) -> bool:
        """docker events 监控是否可用。"""
        return self._available

    @property
    def on_state_change(self) -> Optional[Callable[[str, str], None]]:
        """容器状态变化回调。签名：(container_name, action) -> None。"""
        return self._on_state_change

    @on_state_change.setter
    def on_state_change(self, callback: Optional[Callable[[str, str], None]]) -> None:
        """设置容器状态变化回调。"""
        self._on_state_change = callback

    def _initial_sync(self) -> None:
        """初始同步：用 docker ps 获取当前运行中的容器。

        在后台线程中执行，不阻塞 start() 返回。
        """
        def _sync():
            try:
                result = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}} {{.Status}}"],
                    capture_output=True, text=True, timeout=10,
                )
                with self._lock:
                    for line in result.stdout.strip().split("\n"):
                        if line:
                            parts = line.split(" ", 1)
                            if len(parts) == 2:
                                name, status = parts
                                self._states[name] = "running" if "Up" in status else "exited"
            except Exception:
                pass  # 初始同步失败不影响事件监听

        threading.Thread(target=_sync, daemon=True).start()

    def _read_events(self) -> None:
        """后台线程：逐行读取 docker events 输出。"""
        if not self._process or not self._process.stdout:
            return
        try:
            for line in self._process.stdout:
                if not self._running:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    self._handle_event(event)
                except json.JSONDecodeError:
                    continue
        except Exception:
            # 读取异常（如 docker 退出），标记为不可用
            self._available = False

    def _handle_event(self, event: dict) -> None:
        """处理单个 docker 事件，更新容器状态表。

        Args:
            event: docker events 的 JSON 事件对象
        """
        event_type = event.get("Type", "")
        action = event.get("Action", "")
        actor = event.get("Actor", {})
        attributes = actor.get("Attributes", {})
        container_name = attributes.get("name", "")

        # 只处理有名称的容器事件（匿名容器或非容器事件忽略）
        if event_type != "container" or not container_name:
            return

        state_changed = False
        with self._lock:
            if action == "start":
                self._states[container_name] = "running"
                state_changed = True
            elif action in ("stop", "die", "kill"):
                self._states[container_name] = "exited"
                state_changed = True
            elif action == "restart":
                self._states[container_name] = "running"
                state_changed = True
            elif action == "destroy":
                self._states.pop(container_name, None)
                state_changed = True
            # 其他事件（create/rename/pause/unpause/exec_create 等）不更新状态

        # 状态变化时触发回调（在锁外执行，避免死锁）
        if state_changed and self._on_state_change:
            try:
                self._on_state_change(container_name, action)
            except Exception:
                pass  # 回调异常不影响事件监听

        # S2.4: 容器状态变化记录到 event_bus
        if state_changed:
            try:
                event_level = "warning" if action in ("die", "destroy", "kill") else "info"
                event_bus.record(
                    category="container",
                    level=event_level,
                    source="docker_events",
                    event="container_{}".format(action),
                    message="容器 {} {}".format(container_name, action),
                    metadata={
                        "container": container_name,
                        "action": action,
                        "docker_event": action,
                    }
                )
            except Exception:
                pass  # 事件记录失败不影响事件监听


# 全局单例（模块导入时创建，不自动启动）
docker_events = DockerEventsMonitor()
