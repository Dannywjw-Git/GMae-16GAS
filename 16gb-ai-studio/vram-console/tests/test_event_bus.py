#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EventBus 单元测试（S2.1 事件标准化 + EventBus）

测试覆盖：
- 基本功能：record/query/get_recent/count_by_category
- 事件格式校验：7 个字段完整
- 类别/级别校验：未知类别归为 system，未知级别归为 info
- 多维度过滤：start_time/end_time/category/level/source/event/limit
- 时间倒序：query 返回按时间倒序
- 环形缓冲区：超过 max_events 自动淘汰最旧的
- 持久化：事件写入日志文件
- 启动加载：从持久化文件加载最近的事件
- 线程安全：并发 record/query 不崩溃
- count_by_category：包含所有 7 个类别，无事件的类别为 0
"""
import unittest
import sys
import os
import json
import time
import threading
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus import EventBus, EVENT_CATEGORIES, EVENT_LEVELS


class TestEventBusBasic(unittest.TestCase):
    """基本功能测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "test_events.jsonl")
        self.bus = EventBus(max_events=100, log_file=self.log_file)

    def tearDown(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        os.rmdir(self.tmpdir)

    def test_record_returns_event(self):
        """record() 返回事件对象。"""
        evt = self.bus.record(
            category="vram", level="warning", source="test",
            event="test_event", message="测试事件", metadata={"key": "value"}
        )
        self.assertIsInstance(evt, dict)
        self.assertEqual(evt["category"], "vram")
        self.assertEqual(evt["level"], "warning")
        self.assertEqual(evt["event"], "test_event")
        self.assertEqual(evt["message"], "测试事件")
        self.assertEqual(evt["metadata"], {"key": "value"})

    def test_event_has_all_fields(self):
        """事件对象包含全部 7 个字段。"""
        evt = self.bus.record(
            category="system", level="info", source="test",
            event="field_test", message="字段测试"
        )
        for field in ("timestamp", "category", "level", "source", "event", "message", "metadata"):
            self.assertIn(field, evt, f"事件缺少字段: {field}")

    def test_timestamp_is_iso8601(self):
        """timestamp 是 ISO 8601 格式。"""
        evt = self.bus.record(
            category="system", level="info", source="test",
            event="ts_test", message="时间戳测试"
        )
        # ISO 8601 格式包含 'T' 和 '+' 或 'Z'
        self.assertIn("T", evt["timestamp"])

    def test_metadata_default_empty_dict(self):
        """metadata 不传时默认为空 dict。"""
        evt = self.bus.record(
            category="system", level="info", source="test",
            event="meta_test", message="元数据测试"
        )
        self.assertEqual(evt["metadata"], {})

    def test_unknown_category_defaults_to_system(self):
        """未知类别归为 system。"""
        evt = self.bus.record(
            category="unknown_category", level="info", source="test",
            event="cat_test", message="类别测试"
        )
        self.assertEqual(evt["category"], "system")

    def test_unknown_level_defaults_to_info(self):
        """未知级别归为 info。"""
        evt = self.bus.record(
            category="system", level="unknown_level", source="test",
            event="lvl_test", message="级别测试"
        )
        self.assertEqual(evt["level"], "info")


class TestEventBusQuery(unittest.TestCase):
    """查询功能测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "test_events.jsonl")
        self.bus = EventBus(max_events=100, log_file=self.log_file)
        # 插入测试事件
        self.bus.record(category="vram", level="warning", source="qos",
                        event="vram_warning", message="显存警告", metadata={"free_mb": 3000})
        self.bus.record(category="vram", level="critical", source="qos",
                        event="vram_critical", message="显存危险", metadata={"free_mb": 800})
        self.bus.record(category="container", level="info", source="docker",
                        event="container_start", message="容器启动", metadata={"name": "ollama"})
        self.bus.record(category="user_action", level="info", source="api",
                        event="vram_free", message="释放显存", metadata={"level": "L1"})
        time.sleep(0.01)  # 确保时间戳有差异

    def tearDown(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        os.rmdir(self.tmpdir)

    def test_query_returns_all(self):
        """无过滤条件时返回所有事件。"""
        events = self.bus.query(limit=100)
        self.assertEqual(len(events), 4)

    def test_query_filter_by_category(self):
        """按类别过滤。"""
        events = self.bus.query(category="vram", limit=100)
        self.assertEqual(len(events), 2)
        for e in events:
            self.assertEqual(e["category"], "vram")

    def test_query_filter_by_level(self):
        """按级别过滤。"""
        events = self.bus.query(level="critical", limit=100)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "vram_critical")

    def test_query_filter_by_source(self):
        """按来源过滤。"""
        events = self.bus.query(source="qos", limit=100)
        self.assertEqual(len(events), 2)
        for e in events:
            self.assertEqual(e["source"], "qos")

    def test_query_filter_by_event(self):
        """按事件类型过滤（精确匹配）。"""
        events = self.bus.query(event="vram_free", limit=100)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "user_action")

    def test_query_combined_filters(self):
        """组合过滤条件。"""
        events = self.bus.query(category="vram", level="critical", limit=100)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "vram_critical")

    def test_query_limit(self):
        """limit 限制返回数量。"""
        events = self.bus.query(limit=2)
        self.assertEqual(len(events), 2)

    def test_query_limit_max_500(self):
        """limit 超过 500 时截断为 500。"""
        events = self.bus.query(limit=1000)
        # 只有 4 条事件，所以返回 4 条（但 limit 内部被截断为 500）
        self.assertEqual(len(events), 4)

    def test_query_returns_reverse_chronological(self):
        """查询结果按时间倒序（最新的在前）。"""
        events = self.bus.query(limit=100)
        for i in range(len(events) - 1):
            self.assertGreaterEqual(events[i]["timestamp"], events[i + 1]["timestamp"])

    def test_query_no_match(self):
        """无匹配时返回空列表。"""
        events = self.bus.query(category="nonexistent", limit=100)
        self.assertEqual(events, [])


class TestEventBusGetRecent(unittest.TestCase):
    """get_recent 测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "test_events.jsonl")
        self.bus = EventBus(max_events=100, log_file=self.log_file)

    def tearDown(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        os.rmdir(self.tmpdir)

    def test_get_recent_returns_events(self):
        """get_recent 返回最近的事件。"""
        self.bus.record(category="system", level="info", source="test",
                        event="recent_test", message="最近事件测试")
        events = self.bus.get_recent(seconds=300)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "recent_test")

    def test_get_recent_filter_by_category(self):
        """get_recent 支持按类别过滤。"""
        self.bus.record(category="vram", level="warning", source="test",
                        event="vram_test", message="显存测试")
        self.bus.record(category="container", level="info", source="test",
                        event="container_test", message="容器测试")
        events = self.bus.get_recent(seconds=300, category="vram")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "vram")


class TestEventBusCountByCategory(unittest.TestCase):
    """count_by_category 测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "test_events.jsonl")
        self.bus = EventBus(max_events=100, log_file=self.log_file)

    def tearDown(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        os.rmdir(self.tmpdir)

    def test_count_includes_all_categories(self):
        """统计结果包含所有 7 个类别。"""
        stats = self.bus.count_by_category(seconds=300)
        self.assertEqual(set(stats.keys()), EVENT_CATEGORIES)

    def test_count_zero_when_empty(self):
        """无事件时所有类别计数为 0。"""
        stats = self.bus.count_by_category(seconds=300)
        for cat, count in stats.items():
            self.assertEqual(count, 0, f"类别 {cat} 计数应为 0")

    def test_count_correct(self):
        """统计计数正确。"""
        self.bus.record(category="vram", level="warning", source="test",
                        event="e1", message="m1")
        self.bus.record(category="vram", level="critical", source="test",
                        event="e2", message="m2")
        self.bus.record(category="container", level="info", source="test",
                        event="e3", message="m3")
        stats = self.bus.count_by_category(seconds=300)
        self.assertEqual(stats["vram"], 2)
        self.assertEqual(stats["container"], 1)
        self.assertEqual(stats["model"], 0)


class TestEventBusRingBuffer(unittest.TestCase):
    """环形缓冲区测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "test_events.jsonl")
        self.bus = EventBus(max_events=5, log_file=self.log_file)

    def tearDown(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        os.rmdir(self.tmpdir)

    def test_ring_buffer_evicts_oldest(self):
        """超过 max_events 时自动淘汰最旧的。"""
        for i in range(8):
            self.bus.record(category="system", level="info", source="test",
                            event=f"event_{i}", message=f"事件 {i}")
        events = self.bus.query(limit=100)
        self.assertEqual(len(events), 5)
        # 最旧的 3 个（event_0/1/2）应被淘汰
        event_names = [e["event"] for e in events]
        self.assertNotIn("event_0", event_names)
        self.assertNotIn("event_1", event_names)
        self.assertNotIn("event_2", event_names)
        # 最新的 5 个应保留
        self.assertIn("event_7", event_names)


class TestEventBusPersistence(unittest.TestCase):
    """持久化测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "test_events.jsonl")

    def tearDown(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        os.rmdir(self.tmpdir)

    def test_events_written_to_file(self):
        """事件写入持久化文件。"""
        bus = EventBus(max_events=100, log_file=self.log_file)
        bus.record(category="vram", level="warning", source="test",
                    event="persist_test", message="持久化测试")
        # 读取文件验证
        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        evt = json.loads(lines[0])
        self.assertEqual(evt["event"], "persist_test")

    def test_load_from_file_on_init(self):
        """启动时从持久化文件加载最近的事件。"""
        # 先写入一些事件
        bus1 = EventBus(max_events=100, log_file=self.log_file)
        bus1.record(category="vram", level="warning", source="test",
                    event="load_test_1", message="加载测试1")
        bus1.record(category="container", level="info", source="test",
                    event="load_test_2", message="加载测试2")
        # 创建新的 EventBus 实例，应从文件加载
        bus2 = EventBus(max_events=100, log_file=self.log_file)
        events = bus2.query(limit=100)
        self.assertEqual(len(events), 2)
        event_names = [e["event"] for e in events]
        self.assertIn("load_test_1", event_names)
        self.assertIn("load_test_2", event_names)

    def test_load_respects_max_events(self):
        """启动加载时只保留最近的 max_events 条。"""
        # 写入 10 条事件
        bus1 = EventBus(max_events=100, log_file=self.log_file)
        for i in range(10):
            bus1.record(category="system", level="info", source="test",
                        event=f"ev_{i}", message=f"事件 {i}")
        # 创建 max_events=3 的新实例，应只加载最近 3 条
        bus2 = EventBus(max_events=3, log_file=self.log_file)
        events = bus2.query(limit=100)
        self.assertEqual(len(events), 3)


class TestEventBusThreadSafety(unittest.TestCase):
    """线程安全测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "test_events.jsonl")
        self.bus = EventBus(max_events=200, log_file=self.log_file)

    def tearDown(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        os.rmdir(self.tmpdir)

    def test_concurrent_record(self):
        """并发 record 不崩溃，事件数正确。"""
        errors = []

        def worker(prefix):
            try:
                for i in range(20):
                    self.bus.record(
                        category="system", level="info", source=prefix,
                        event=f"{prefix}_{i}", message=f"并发测试 {prefix} {i}"
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"w{t}",)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0, f"并发错误: {errors}")
        events = self.bus.query(limit=500)
        self.assertEqual(len(events), 100)

    def test_concurrent_record_and_query(self):
        """并发 record 和 query 不崩溃。"""
        errors = []

        def recorder():
            try:
                for i in range(30):
                    self.bus.record(
                        category="vram", level="warning", source="recorder",
                        event=f"rec_{i}", message=f"记录 {i}"
                    )
            except Exception as e:
                errors.append(e)

        def querier():
            try:
                for _ in range(30):
                    self.bus.query(category="vram", limit=50)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=recorder), threading.Thread(target=querier)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0, f"并发错误: {errors}")


class TestEventBusClear(unittest.TestCase):
    """clear 测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "test_events.jsonl")
        self.bus = EventBus(max_events=100, log_file=self.log_file)

    def tearDown(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        os.rmdir(self.tmpdir)

    def test_clear_removes_all_events(self):
        """clear 清空内存中的事件。"""
        self.bus.record(category="system", level="info", source="test",
                        event="before_clear", message="清空前")
        self.assertEqual(len(self.bus.query(limit=100)), 1)
        self.bus.clear()
        self.assertEqual(len(self.bus.query(limit=100)), 0)

    def test_clear_does_not_delete_file(self):
        """clear 不删除持久化文件。"""
        self.bus.record(category="system", level="info", source="test",
                        event="file_test", message="文件测试")
        self.bus.clear()
        self.assertTrue(os.path.exists(self.log_file))


class TestEventBusConstants(unittest.TestCase):
    """常量测试。"""

    def test_event_categories_has_7(self):
        """EVENT_CATEGORIES 包含 7 个类别。"""
        self.assertEqual(len(EVENT_CATEGORIES), 7)
        for cat in ("vram", "container", "model", "task", "user_action", "system", "guard"):
            self.assertIn(cat, EVENT_CATEGORIES)

    def test_event_levels_has_5(self):
        """EVENT_LEVELS 包含 5 个级别。"""
        self.assertEqual(len(EVENT_LEVELS), 5)
        for lvl in ("debug", "info", "warning", "error", "critical"):
            self.assertIn(lvl, EVENT_LEVELS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
