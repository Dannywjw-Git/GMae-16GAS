#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根因推断规则引擎单元测试（S2.5）
覆盖：RuleEngine 基本功能、5 条规则正例/反例、Top3 限制、默认诊断、get_all_rules
"""
import os
import sys
import json
import tempfile
import unittest
from datetime import datetime, timezone

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.event_bus import EventBus
from engine.diagnose import RuleEngine, Rule, rule_engine as global_rule_engine


class TestDiagnoseBase(unittest.TestCase):
    """诊断测试基类：使用临时 event_bus，避免污染正式日志。"""

    def setUp(self):
        # 创建临时目录和临时 event_bus
        self.tmpdir = tempfile.mkdtemp()
        self.test_event_bus = EventBus(
            max_events=100,
            log_file=os.path.join(self.tmpdir, "test_events.jsonl")
        )
        # 临时替换 engine.diagnose 模块中的 event_bus 引用
        import engine.diagnose as diagnose_mod
        self._original_event_bus = diagnose_mod.event_bus
        diagnose_mod.event_bus = self.test_event_bus

        # 创建独立的 rule_engine 用于测试（不使用全局单例，避免规则重复注册）
        self.engine = RuleEngine()
        # 从全局 rule_engine 复制规则
        for r in global_rule_engine._rules:
            self.engine.register(r)

    def tearDown(self):
        # 恢复原始 event_bus
        import engine.diagnose as diagnose_mod
        diagnose_mod.event_bus = self._original_event_bus
        # 清理临时文件
        try:
            import shutil
            shutil.rmtree(self.tmpdir, ignore_errors=True)
        except Exception:
            pass

    def _make_event(self, category, event_name, message="test", metadata=None):
        """添加测试事件。"""
        self.test_event_bus.record(
            category=category,
            level="info",
            source="test",
            event=event_name,
            message=message,
            metadata=metadata or {}
        )


class TestRuleEngineBasic(TestDiagnoseBase):
    """RuleEngine 基本功能测试。"""

    def test_register_and_get_all_rules(self):
        """注册规则后 get_all_rules 返回正确数量。"""
        rules = self.engine.get_all_rules()
        self.assertEqual(len(rules), 9)  # RC-001 ~ RC-009
        for r in rules:
            self.assertIn("id", r)
            self.assertIn("name", r)
            self.assertIn("root_cause", r)
            self.assertIn("confidence", r)
            self.assertIn("suggested_action", r)

    def test_diagnose_returns_result_structure(self):
        """diagnose 返回正确的结构。"""
        result = self.engine.diagnose("vram_critical", current_status={})
        self.assertEqual(result.alert_type, "vram_critical")
        self.assertEqual(result.window_seconds, 300)
        self.assertIsInstance(result.matched_rules, list)
        self.assertIsInstance(result.total_events, int)

    def test_diagnose_window_seconds(self):
        """diagnose 尊重 window_seconds 参数。"""
        self._make_event("task", "task_submitted", "test")
        result = self.engine.diagnose("vram_critical", window_seconds=60, current_status={})
        self.assertEqual(result.window_seconds, 60)


class TestRC001ComfyUITask(TestDiagnoseBase):
    """RC-001: ComfyUI 生成任务显存溢出。"""

    def test_rc001_positive(self):
        """正例：有 task 事件 + ComfyUI 运行 + 显存 <1024MB → 匹配 RC-001。"""
        self._make_event("task", "task_submitted", "comfyui task")
        status = {"data": {
            "services": {"comfyui": {"ok": True}},
            "vram_ledger": {"free_mb": 500}
        }}
        result = self.engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertIn("RC-001", rule_ids)

    def test_rc001_negative_no_task(self):
        """反例：无 task 事件 → 不匹配 RC-001。"""
        status = {"data": {
            "services": {"comfyui": {"ok": True}},
            "vram_ledger": {"free_mb": 500}
        }}
        result = self.engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertNotIn("RC-001", rule_ids)

    def test_rc001_negative_enough_vram(self):
        """反例：显存充足（>1024MB）→ 不匹配 RC-001。"""
        self._make_event("task", "task_submitted", "comfyui task")
        status = {"data": {
            "services": {"comfyui": {"ok": True}},
            "vram_ledger": {"free_mb": 5000}
        }}
        result = self.engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertNotIn("RC-001", rule_ids)


class TestRC002LargeModel(TestDiagnoseBase):
    """RC-002: 大模型加载导致显存不足。"""

    def test_rc002_positive(self):
        """正例：有 model_loaded 事件 + 加载了大模型 + 显存 <2048MB → 匹配 RC-002。"""
        self._make_event("model", "model_loaded", "qwen3.5:9b loaded")
        status = {"data": {
            "ollama": {"loaded_models": ["qwen3.5:9b"]},
            "vram_ledger": {"free_mb": 1000}
        }}
        result = self.engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertIn("RC-002", rule_ids)

    def test_rc002_negative_small_model(self):
        """反例：只加载了小模型 → 不匹配 RC-002。"""
        self._make_event("model", "model_loaded", "qwen3:0.6b loaded")
        status = {"data": {
            "ollama": {"loaded_models": ["qwen3:0.6b"]},
            "vram_ledger": {"free_mb": 1000}
        }}
        result = self.engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertNotIn("RC-002", rule_ids)


class TestRC005DesktopVram(TestDiagnoseBase):
    """RC-005: 桌面应用占用显存。"""

    def test_rc005_positive(self):
        """正例：桌面显存 >2048MB + 无 task/model 事件 + 显存 <2048MB → 匹配 RC-005。"""
        status = {"data": {
            "desktop_vram": {"total_mb": 3000},
            "vram_ledger": {"free_mb": 1000}
        }}
        result = self.engine.diagnose("vram_critical", current_status=status)
        rule_ids = [r["rule_id"] for r in result.matched_rules]
        self.assertIn("RC-005", rule_ids)


class TestDefaultDiagnosis(TestDiagnoseBase):
    """默认诊断测试。"""

    def test_default_diagnosis_when_no_match(self):
        """无匹配规则时返回 DEFAULT 诊断。"""
        status = {"data": {"vram_ledger": {"free_mb": 100}, "services": {}}}
        result = self.engine.diagnose("vram_critical", current_status=status)
        self.assertEqual(result.matched_rules[0]["rule_id"], "DEFAULT")
        self.assertIsNotNone(result.default_diagnosis)


class TestTop3Limit(TestDiagnoseBase):
    """Top3 限制测试。"""

    def test_top3_only(self):
        """多个匹配时只返回 Top3，按置信度降序。"""
        # 构造多个匹配
        for i in range(3):
            self._make_event("task", "task_submitted_{}".format(i))
            self._make_event("model", "model_loaded_{}".format(i))
        status = {"data": {
            "services": {"comfyui": {"ok": True}, "fooocus": {"ok": True}},
            "ollama": {"loaded_models": ["qwen3.5:9b"]},
            "desktop_vram": {"total_mb": 3000},
            "vram_ledger": {"free_mb": 500}
        }}
        result = self.engine.diagnose("vram_critical", current_status=status)
        self.assertLessEqual(len(result.matched_rules), 3)
        # 按置信度降序
        confidences = [r["confidence"] for r in result.matched_rules]
        self.assertEqual(confidences, sorted(confidences, reverse=True))


class TestMatchedRuleStructure(TestDiagnoseBase):
    """匹配规则的结构测试。"""

    def test_matched_rule_has_required_fields(self):
        """匹配的规则包含所有必要字段。"""
        self._make_event("task", "task_submitted", "test")
        status = {"data": {
            "services": {"comfyui": {"ok": True}},
            "vram_ledger": {"free_mb": 500}
        }}
        result = self.engine.diagnose("vram_critical", current_status=status)
        for rule in result.matched_rules:
            if rule["rule_id"] == "DEFAULT":
                continue
            self.assertIn("rule_id", rule)
            self.assertIn("rule_name", rule)
            self.assertIn("root_cause", rule)
            self.assertIn("confidence", rule)
            self.assertIn("suggested_action", rule)
            self.assertIn("related_events", rule)
            self.assertIn("related_events_count", rule)


if __name__ == "__main__":
    unittest.main(verbosity=2)
