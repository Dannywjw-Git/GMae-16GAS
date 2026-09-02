#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
状态缓存模块（S1.1 指标缓存层）

【职责边界 - 与 registry.py 的区别】
- 本文件：专门的 API 响应缓存（/api/status），有 TTL + 后台异步刷新
- registry.py：通用状态存储（服务列表、队列任务、锁等），无 TTL
- 【重要】需要 TTL 的缓存数据用本文件，通用运行时状态用 registry

为 /api/status 提供 TTL 缓存，减少 docker exec 调用。

核心类：
- StatusCache: 单例缓存管理器，支持 get/set/invalidate/is_expired/try_background_refresh

设计要点：
- TTL 默认 10 秒，危险状态（danger/critical）时缩短为 2 秒
- 缓存失效时后台异步刷新（不阻塞请求，返回旧数据 + stale 标记）
- 写操作后主动调用 invalidate()
- 线程安全（threading.Lock）
- 返回深拷贝，避免外部修改缓存

使用方式：
    from core.status_cache import status_cache

    # 读路径：尝试缓存，过期则后台刷新
    result = status_cache.try_background_refresh(_build_status)
    # result 包含原始 data + cached/cached_at/stale 元信息字段

    # 写路径：操作成功后失效缓存
    status_cache.invalidate()
"""

import threading
import time
import json
from typing import Optional, Dict, Any, Callable


class StatusCache:
    """状态缓存管理器。

    为 /api/status 提供 TTL 缓存，支持后台异步刷新。
    缓存存储原始 status data（current_status() 的返回值），
    不包含 v1 响应包装（ok/data/error/meta）。
    """

    def __init__(self, ttl_seconds: float = 10.0, danger_ttl_seconds: float = 2.0,
                 refresh_timeout_seconds: float = 30.0):
        self._ttl = ttl_seconds
        self._danger_ttl = danger_ttl_seconds
        self._refresh_timeout = refresh_timeout_seconds
        self._cache: Optional[Dict[str, Any]] = None
        self._cached_at: float = 0.0
        self._lock = threading.Lock()
        self._refreshing = False
        self._refresh_started_at: float = 0.0
        self._refresh_thread: Optional[threading.Thread] = None

    def _current_ttl(self) -> float:
        """根据缓存中的危险等级返回当前 TTL。"""
        if self._cache is None:
            return self._ttl
        danger_level = self._cache.get("vram_ledger", {}).get("danger_level", "safe")
        return self._danger_ttl if danger_level in ("danger", "critical") else self._ttl

    def get(self) -> Optional[Dict[str, Any]]:
        """获取缓存（未过期时）。返回 None 表示缓存不存在或已过期。

        返回深拷贝，避免外部修改缓存内部数据。
        """
        with self._lock:
            if self._cache is None:
                return None
            age = time.time() - self._cached_at
            if age > self._current_ttl():
                return None
            return json.loads(json.dumps(self._cache))

    def get_stale(self) -> Optional[Dict[str, Any]]:
        """获取缓存（即使已过期），用于后台刷新时返回旧数据。

        返回的 dict 上附加 cached=True, cached_at=<epoch>, stale=True 标记。
        """
        with self._lock:
            if self._cache is None:
                return None
            result = json.loads(json.dumps(self._cache))
            result["cached"] = True
            result["cached_at"] = self._cached_at
            result["stale"] = True
            return result

    def set(self, data: Dict[str, Any]) -> None:
        """设置缓存（深拷贝存储）。"""
        with self._lock:
            self._cache = json.loads(json.dumps(data))
            self._cached_at = time.time()

    def invalidate(self) -> None:
        """失效缓存（写操作成功后调用）。

        同时重置 _refreshing 标志：如果后台刷新线程正在运行，
        其结果已因写操作而过期，允许下一次请求启动新的同步刷新。
        否则后续请求会进入"正在刷新"分支，但 get_stale() 返回 None
        （缓存已被清空），导致 500 错误。
        """
        with self._lock:
            self._cache = None
            self._cached_at = 0.0
            self._refreshing = False
            self._refresh_started_at = 0.0

    def is_expired(self) -> bool:
        """检查缓存是否已过期（或不存在）。"""
        with self._lock:
            if self._cache is None:
                return True
            age = time.time() - self._cached_at
            return age > self._current_ttl()

    def _check_refresh_timeout(self) -> None:
        """检查后台刷新是否超时，超时则重置 _refreshing 标志。

        防止后台线程卡住（如 docker exec 无限等待）导致缓存永远不更新。
        必须在持有 _lock 的情况下调用。
        """
        if self._refreshing and self._refresh_started_at > 0:
            elapsed = time.time() - self._refresh_started_at
            if elapsed > self._refresh_timeout:
                # 超时，强制重置（后台线程可能卡住了，让它自然结束）
                self._refreshing = False
                self._refresh_started_at = 0.0

    def try_background_refresh(self, refresh_func: Callable[[], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """尝试从缓存获取数据，过期则后台异步刷新。

        策略：
        1. 缓存未过期 → 直接返回缓存（cached=True, stale=False）
        2. 缓存已过期且有旧数据 → 启动后台刷新线程，返回旧数据（cached=True, stale=True）
        3. 缓存已过期且无旧数据 → 同步执行刷新，返回新数据（cached=False）
        4. 正在刷新中 → 直接返回 stale 数据（不阻塞，cached=True, stale=True）

        后台刷新超时保护：如果刷新超过 30 秒未完成，自动重置 _refreshing，
        允许下一次请求启动新的刷新（防止后台线程卡住导致缓存永不过期）。

        Args:
            refresh_func: 无参数函数，返回完整的 status data dict（慢路径）

        Returns:
            包含原始 data 字段 + cached/cached_at/stale 元信息的 dict。
            调用方应将 cached/cached_at/stale 提取到响应 meta 中。
            refresh_func 失败时返回 None。
        """
        with self._lock:
            self._check_refresh_timeout()

        # 1. 缓存未过期，直接返回
        cached = self.get()
        if cached is not None:
            cached["cached"] = True
            cached["cached_at"] = self._cached_at
            cached["stale"] = False
            return cached

        # 2. 缓存已过期，检查是否有旧数据可返回
        stale = self.get_stale()
        if stale is not None and not self._refreshing:
            # 有旧数据，启动后台刷新，返回 stale 数据
            with self._lock:
                self._refreshing = True
                self._refresh_started_at = time.time()
            self._refresh_thread = threading.Thread(
                target=self._do_refresh,
                args=(refresh_func,),
                daemon=True,
            )
            self._refresh_thread.start()
            return stale

        # 3. 无旧数据，同步刷新（首次请求或缓存被 invalidate 后）
        if not self._refreshing:
            with self._lock:
                self._refreshing = True
                self._refresh_started_at = time.time()
            try:
                new_data = refresh_func()
                if new_data is None:
                    return None
                self.set(new_data)
                # 同步刷新的新数据标记为非缓存
                result = json.loads(json.dumps(new_data))
                result["cached"] = False
                result["cached_at"] = None
                result["stale"] = False
                return result
            finally:
                with self._lock:
                    self._refreshing = False
                    self._refresh_started_at = 0.0
        else:
            # 4. 正在刷新中，直接返回 stale 数据（不阻塞等待）
            stale = self.get_stale()
            if stale is not None:
                return stale
            # 防御：正在刷新但无旧数据（如 invalidate 与刷新竞态），
            # 重置刷新标志，让下一次请求走同步刷新路径
            with self._lock:
                self._refreshing = False
                self._refresh_started_at = 0.0
            return None

    def _do_refresh(self, refresh_func: Callable[[], Dict[str, Any]]) -> None:
        """后台刷新执行体（在独立线程中运行）。

        刷新失败时静默保留旧数据，不影响服务稳定性。
        """
        try:
            new_data = refresh_func()
            if new_data is not None:
                self.set(new_data)
        except Exception:
            # 后台刷新失败不影响服务，保留旧数据
            pass
        finally:
            with self._lock:
                self._refreshing = False
                self._refresh_started_at = 0.0


# 全局单例（模块导入时创建）
status_cache = StatusCache()
