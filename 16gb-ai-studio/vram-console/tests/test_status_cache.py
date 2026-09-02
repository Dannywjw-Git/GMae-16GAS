#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StatusCache 单元测试（S1.1 指标缓存层）

测试覆盖：
- set/get 基本功能
- TTL 过期
- invalidate 失效
- 危险状态更短 TTL
- 返回深拷贝（外部修改不影响缓存）
- is_expired 状态检查
- get_stale 过期数据获取
- try_background_refresh 三种策略（缓存命中/stale后台刷新/同步刷新）
- 线程安全（并发访问不崩溃）

运行方式：
    cd vram-console
    python tests/test_status_cache.py
    或 python -m pytest tests/test_status_cache.py -v
"""
import unittest
import time
import sys
import threading
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.status_cache import StatusCache


def _make_status(danger_level: str = "safe", version: int = 1) -> dict:
    """构造一个模拟的 status data（与 current_status() 返回结构类似）。"""
    return {
        "scene": "dialogue",
        "gpu": {"total_mb": 16380, "used_mb": 5000, "free_mb": 11380},
        "vram_ledger": {
            "danger_level": danger_level,
            "free_mb": 11380,
            "breakdown": {"base_noise_mb": 3000, "ollama_mb": 2000, "free_mb": 11380},
        },
        "services": {"ollama": {"ok": True}, "comfyui": {"ok": False}},
        "version": version,
    }


class TestStatusCacheBasic(unittest.TestCase):
    """基本功能测试。"""

    def setUp(self):
        self.cache = StatusCache(ttl_seconds=0.5, danger_ttl_seconds=0.2)

    def test_set_and_get(self):
        """设置缓存后能获取到相同数据。"""
        data = _make_status()
        self.cache.set(data)
        result = self.cache.get()
        self.assertIsNotNone(result)
        self.assertEqual(result["scene"], "dialogue")
        self.assertEqual(result["vram_ledger"]["danger_level"], "safe")

    def test_get_empty_returns_none(self):
        """未设置缓存时 get 返回 None。"""
        self.assertIsNone(self.cache.get())

    def test_expiry(self):
        """超过 TTL 后缓存过期，get 返回 None。"""
        data = _make_status(danger_level="safe")
        self.cache.set(data)
        time.sleep(0.6)  # 超过 0.5s TTL
        self.assertIsNone(self.cache.get())

    def test_not_expired_within_ttl(self):
        """在 TTL 内缓存不过期。"""
        data = _make_status()
        self.cache.set(data)
        time.sleep(0.1)
        result = self.cache.get()
        self.assertIsNotNone(result)

    def test_invalidate(self):
        """invalidate 后缓存被清空。"""
        data = _make_status()
        self.cache.set(data)
        self.assertIsNotNone(self.cache.get())
        self.cache.invalidate()
        self.assertIsNone(self.cache.get())

    def test_get_returns_deep_copy(self):
        """get 返回深拷贝，外部修改不影响缓存内部数据。"""
        data = _make_status()
        self.cache.set(data)
        result = self.cache.get()
        result["scene"] = "modified"
        result["vram_ledger"]["free_mb"] = 99999
        # 原缓存不应被修改
        cached = self.cache.get()
        self.assertEqual(cached["scene"], "dialogue")
        self.assertEqual(cached["vram_ledger"]["free_mb"], 11380)

    def test_set_stores_deep_copy(self):
        """set 存储深拷贝，外部修改原始 data 不影响缓存。"""
        data = _make_status()
        self.cache.set(data)
        data["scene"] = "modified_external"
        cached = self.cache.get()
        self.assertEqual(cached["scene"], "dialogue")


class TestStatusCacheDangerTTL(unittest.TestCase):
    """危险状态更短 TTL 测试。"""

    def setUp(self):
        self.cache = StatusCache(ttl_seconds=0.5, danger_ttl_seconds=0.2)

    def test_danger_shorter_ttl(self):
        """danger 状态使用更短 TTL（0.2s），0.3s 后过期。"""
        data = _make_status(danger_level="danger")
        self.cache.set(data)
        time.sleep(0.3)  # 超过 0.2s danger TTL，但未超过 0.5s 普通 TTL
        self.assertIsNone(self.cache.get())

    def test_critical_shorter_ttl(self):
        """critical 状态也使用更短 TTL。"""
        data = _make_status(danger_level="critical")
        self.cache.set(data)
        time.sleep(0.3)
        self.assertIsNone(self.cache.get())

    def test_safe_uses_normal_ttl(self):
        """safe 状态使用普通 TTL（0.5s），0.3s 后不过期。"""
        data = _make_status(danger_level="safe")
        self.cache.set(data)
        time.sleep(0.3)  # 未超过 0.5s 普通 TTL
        result = self.cache.get()
        self.assertIsNotNone(result)

    def test_warning_uses_normal_ttl(self):
        """warning 状态使用普通 TTL（只有 danger/critical 用短 TTL）。"""
        data = _make_status(danger_level="warning")
        self.cache.set(data)
        time.sleep(0.3)
        result = self.cache.get()
        self.assertIsNotNone(result)


class TestStatusCacheStale(unittest.TestCase):
    """过期数据（stale）获取测试。"""

    def setUp(self):
        self.cache = StatusCache(ttl_seconds=0.3, danger_ttl_seconds=0.1)

    def test_get_stale_returns_expired_data(self):
        """get_stale 即使缓存已过期也返回数据，并标记 stale=True。"""
        data = _make_status(version=1)
        self.cache.set(data)
        time.sleep(0.4)  # 过期
        self.assertIsNone(self.cache.get())  # get 返回 None
        stale = self.cache.get_stale()
        self.assertIsNotNone(stale)
        self.assertTrue(stale["cached"])
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["version"], 1)
        self.assertIn("cached_at", stale)

    def test_get_stale_empty_returns_none(self):
        """无缓存时 get_stale 返回 None。"""
        self.assertIsNone(self.cache.get_stale())

    def test_is_expired(self):
        """is_expired 正确判断过期状态。"""
        self.assertTrue(self.cache.is_expired())  # 无缓存
        data = _make_status()
        self.cache.set(data)
        self.assertFalse(self.cache.is_expired())  # 刚设置
        time.sleep(0.4)
        self.assertTrue(self.cache.is_expired())  # 已过期


class TestStatusCacheBackgroundRefresh(unittest.TestCase):
    """try_background_refresh 三种策略测试。"""

    def setUp(self):
        self.cache = StatusCache(ttl_seconds=0.3, danger_ttl_seconds=0.1)

    def test_cache_hit_returns_cached(self):
        """缓存未过期时直接返回缓存，cached=True, stale=False。"""
        data = _make_status(version=1)
        self.cache.set(data)

        refresh_called = []
        def refresh_func():
            refresh_called.append(True)
            return _make_status(version=2)

        result = self.cache.try_background_refresh(refresh_func)
        self.assertIsNotNone(result)
        self.assertTrue(result["cached"])
        self.assertFalse(result["stale"])
        self.assertEqual(result["version"], 1)  # 缓存数据，不是新数据
        self.assertEqual(len(refresh_called), 0)  # 不应调用 refresh_func

    def test_stale_refresh_returns_old_and_triggers_background(self):
        """缓存过期有旧数据时，返回旧数据（stale=True），并启动后台刷新。"""
        # TTL=1.0秒：初始缓存等待1.2秒过期；后台刷新后缓存age约0.6秒 < 1.0秒，第二次调用时仍有效
        cache = StatusCache(ttl_seconds=1.0, danger_ttl_seconds=0.5)
        data = _make_status(version=1)
        cache.set(data)
        time.sleep(1.2)  # 过期（>1.0秒TTL）

        refresh_called = []
        def refresh_func():
            refresh_called.append(True)
            time.sleep(0.2)  # 模拟慢刷新
            return _make_status(version=2)

        # 第一次调用：返回 stale 旧数据，启动后台刷新
        result = cache.try_background_refresh(refresh_func)
        self.assertIsNotNone(result)
        self.assertTrue(result["cached"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["version"], 1)  # 旧数据

        # 等待后台刷新完成（0.2秒刷新 + 余量）
        time.sleep(0.8)

        # 第二次调用：应返回新数据（缓存age约0.6秒 < 1.0秒TTL，未过期）
        result2 = cache.try_background_refresh(refresh_func)
        self.assertIsNotNone(result2)
        self.assertTrue(result2["cached"])
        self.assertFalse(result2["stale"])
        self.assertEqual(result2["version"], 2)  # 新数据

    def test_sync_refresh_when_no_cache(self):
        """无缓存（无旧数据）时同步执行刷新，返回新数据，cached=False。"""
        refresh_called = []
        def refresh_func():
            refresh_called.append(True)
            return _make_status(version=3)

        result = self.cache.try_background_refresh(refresh_func)
        self.assertIsNotNone(result)
        self.assertFalse(result["cached"])
        self.assertFalse(result["stale"])
        self.assertEqual(result["version"], 3)
        self.assertEqual(len(refresh_called), 1)

    def test_invalidate_then_sync_refresh(self):
        """invalidate 后无旧数据，下次请求同步刷新。"""
        data = _make_status(version=1)
        self.cache.set(data)
        self.cache.invalidate()

        def refresh_func():
            return _make_status(version=2)

        result = self.cache.try_background_refresh(refresh_func)
        self.assertIsNotNone(result)
        self.assertFalse(result["cached"])
        self.assertEqual(result["version"], 2)

    def test_refresh_func_returns_none(self):
        """refresh_func 返回 None 时 try_background_refresh 返回 None。"""
        def refresh_func():
            return None

        result = self.cache.try_background_refresh(refresh_func)
        self.assertIsNone(result)

    def test_background_refresh_failure_keeps_old(self):
        """后台刷新失败时保留旧数据，不崩溃。"""
        data = _make_status(version=1)
        self.cache.set(data)
        time.sleep(0.4)  # 过期

        def failing_refresh():
            raise RuntimeError("simulated refresh failure")

        # 第一次调用：返回 stale 旧数据，启动后台刷新（会失败）
        result = self.cache.try_background_refresh(failing_refresh)
        self.assertIsNotNone(result)
        self.assertTrue(result["stale"])
        self.assertEqual(result["version"], 1)

        # 等待后台刷新失败完成
        time.sleep(0.3)

        # 旧数据仍在（刷新失败不清除缓存）
        stale = self.cache.get_stale()
        self.assertIsNotNone(stale)
        self.assertEqual(stale["version"], 1)


class TestStatusCacheThreadSafety(unittest.TestCase):
    """线程安全测试。"""

    def setUp(self):
        self.cache = StatusCache(ttl_seconds=1.0, danger_ttl_seconds=0.5)

    def test_concurrent_set_and_get(self):
        """并发 set 和 get 不崩溃，数据一致。"""
        errors = []

        def writer():
            try:
                for i in range(50):
                    self.cache.set(_make_status(version=i))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    result = self.cache.get()
                    if result is not None:
                        _ = result["version"]
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)] + \
                  [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")

    def test_concurrent_invalidate(self):
        """并发 invalidate 不崩溃。"""
        self.cache.set(_make_status())
        errors = []

        def invalidator():
            try:
                for _ in range(100):
                    self.cache.invalidate()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=invalidator) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0)


class TestStatusCacheMetaFields(unittest.TestCase):
    """缓存元信息字段测试（cached/cached_at/stale）。"""

    def setUp(self):
        self.cache = StatusCache(ttl_seconds=0.5, danger_ttl_seconds=0.2)

    def test_cached_at_is_epoch_float(self):
        """cached_at 是 epoch 秒浮点数。"""
        data = _make_status()
        self.cache.set(data)
        result = self.cache.get()
        # get 本身不附加 cached_at，但 get_stale 和 try_background_refresh 会
        stale = self.cache.get_stale()
        self.assertIn("cached_at", stale)
        self.assertIsInstance(stale["cached_at"], float)
        self.assertGreater(stale["cached_at"], 1700000000)  # 2023年以后

    def test_try_refresh_result_has_all_meta_fields(self):
        """try_background_refresh 返回的结果始终包含 cached/cached_at/stale。"""
        def refresh_func():
            return _make_status(version=1)

        result = self.cache.try_background_refresh(refresh_func)
        self.assertIn("cached", result)
        self.assertIn("cached_at", result)
        self.assertIn("stale", result)

    def test_sync_refresh_cached_at_is_none(self):
        """同步刷新（无缓存）时 cached_at 为 None。"""
        def refresh_func():
            return _make_status(version=1)

        result = self.cache.try_background_refresh(refresh_func)
        self.assertFalse(result["cached"])
        self.assertIsNone(result["cached_at"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
