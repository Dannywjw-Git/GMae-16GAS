#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 全局状态注册表（唯一状态持有者）

【职责边界 - 与 status_cache.py 的区别】
- 本文件：通用状态存储（服务列表、队列任务、锁、运行时标志等），无 TTL
- status_cache.py：专门的 API 响应缓存（/api/status），有 TTL + 后台异步刷新
- 【重要】不要用 registry 存储需要 TTL 的缓存数据，应使用 status_cache

- 所有跨模块共享状态集中管理
- 所有访问自动加锁，消除竞态条件
- 支持命名空间，避免 key 冲突
- 单例模式，全局唯一实例

使用方式：
    from core.registry import registry
    registry.set("queue_tasks", {})
    tasks = registry.get("queue_tasks")
    with registry.lock("queue"):
        registry.set("queue_tasks", {})
"""
import threading
from typing import Any, Optional


class StateRegistry:
    """全局状态注册表（线程安全）"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._state = {}
        self._locks = {}
        self._global_lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        """获取状态值（线程安全）"""
        with self._global_lock:
            return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置状态值（线程安全）"""
        with self._global_lock:
            self._state[key] = value

    def delete(self, key: str) -> None:
        """删除状态值（线程安全）"""
        with self._global_lock:
            self._state.pop(key, None)

    def has(self, key: str) -> bool:
        """检查状态是否存在（线程安全）"""
        with self._global_lock:
            return key in self._state

    def lock(self, key: str) -> threading.Lock:
        """获取指定 key 的专用锁（用于复杂操作的原子性）"""
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def update_dict(self, key: str, **kwargs) -> dict:
        """原子更新字典类型的状态（合并更新）"""
        with self._global_lock:
            current = self._state.get(key, {})
            if not isinstance(current, dict):
                current = {}
            current.update(kwargs)
            self._state[key] = current
            return current

    def append_list(self, key: str, item: Any, max_len: Optional[int] = None) -> list:
        """原子追加到列表类型的状态"""
        with self._global_lock:
            current = self._state.get(key, [])
            if not isinstance(current, list):
                current = []
            current.append(item)
            if max_len and len(current) > max_len:
                current = current[-max_len:]
            self._state[key] = current
            return current

    def snapshot(self) -> dict:
        """获取所有状态的快照（用于调试）"""
        with self._global_lock:
            return dict(self._state)

    def clear(self) -> None:
        """清空所有状态（测试用）"""
        with self._global_lock:
            self._state.clear()
            self._locks.clear()


# 全局单例
registry = StateRegistry()
