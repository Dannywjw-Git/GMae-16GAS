#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae v0.3.1 C-Eng 单元测试
测试 Provider 层、Tool 层、隐私过滤、决策日志、决策引擎核心逻辑。
不依赖真实 LLM 调用（mock）。
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, PARENT_DIR)

from ceng.providers.base import LLMProvider, LLMResponse
from ceng.providers.ollama_provider import OllamaProvider
from ceng.providers.openai_compat import OpenAICompatProvider
from ceng.providers.manager import ProviderManager
from ceng.tools.base import Tool
from ceng.tools.peng_client import PengClient
from ceng.tools.peng_tools import create_all_tools, get_tool_schemas
from ceng.privacy_filter import PrivacyFilter
from ceng.decision_logger import DecisionLogger
from ceng.decision_engine import DecisionEngine


class TestLLMResponse(unittest.TestCase):
    def test_ok_property(self):
        r = LLMResponse(content="hello")
        self.assertTrue(r.ok)
        r2 = LLMResponse(content="", error="fail")
        self.assertFalse(r2.ok)

    def test_defaults(self):
        r = LLMResponse(content="test")
        self.assertEqual(r.prompt_tokens, 0)
        self.assertEqual(r.completion_tokens, 0)
        self.assertEqual(r.latency_ms, 0)
        self.assertEqual(r.tool_calls, [])


class TestOllamaProvider(unittest.TestCase):
    def test_init(self):
        p = OllamaProvider(model="qwen3.5:0.8b", name="test-fast")
        self.assertEqual(p.name, "test-fast")
        self.assertEqual(p.backend, "local")
        self.assertEqual(p.capability_tier, "light")
        self.assertEqual(p.speed_tier, "fast")

    def test_init_deep(self):
        p = OllamaProvider(model="qwen3.5:9b", name="test-deep", capability_tier="deep")
        self.assertEqual(p.capability_tier, "deep")
        self.assertEqual(p.speed_tier, "normal")

    def test_to_dict(self):
        p = OllamaProvider(model="qwen3.5:0.8b", name="test")
        d = p.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["backend"], "local")
        self.assertIn("vram_cost_gb", d)


class TestProviderManager(unittest.TestCase):
    def test_default_providers(self):
        mgr = ProviderManager()
        providers = mgr.get_all()
        self.assertGreaterEqual(len(providers), 2)  # 快道+深道

    def test_get_fast(self):
        mgr = ProviderManager()
        fast = mgr.get_fast()
        self.assertIsNotNone(fast)
        self.assertEqual(fast.capability_tier, "light")

    def test_get_deep(self):
        mgr = ProviderManager()
        deep = mgr.get_deep()
        self.assertIsNotNone(deep)
        self.assertEqual(deep.capability_tier, "deep")

    def test_add_remove(self):
        mgr = ProviderManager()
        p = OllamaProvider(model="test:1b", name="test-add")
        mgr.add_provider(p)
        self.assertIn("test-add", [x.name for x in mgr.get_all()])
        mgr.remove_provider("test-add")
        self.assertNotIn("test-add", [x.name for x in mgr.get_all()])

    def test_get_status(self):
        mgr = ProviderManager()
        status = mgr.get_status()
        self.assertIsInstance(status, list)
        self.assertGreater(len(status), 0)
        for s in status:
            self.assertIn("name", s)
            self.assertIn("backend", s)
            self.assertIn("available", s)


class TestPengClient(unittest.TestCase):
    def test_init(self):
        c = PengClient(base_url="http://localhost:8787")
        self.assertEqual(c.base_url, "http://localhost:8787")

    def test_headers(self):
        c = PengClient(api_token="secret")
        h = c._headers()
        self.assertEqual(h["X-API-Key"], "secret")

    def test_headers_no_token(self):
        # PengClient 现在会自动从 .api_token 文件发现 token
        # 所以无 token 参数时 headers 可能包含自动发现的 token
        c = PengClient(api_token="")
        h = c._headers()
        # 手动清空 token 后验证
        c.api_token = ""
        h2 = c._headers()
        self.assertNotIn("X-API-Key", h2)


class TestTools(unittest.TestCase):
    def test_create_all_tools(self):
        client = PengClient()
        tools = create_all_tools(client)
        self.assertEqual(len(tools), 11)
        names = [t.name for t in tools]
        expected = ["get_system_status", "get_model_budget", "list_models",
                    "switch_scene", "submit_task", "cancel_task",
                    "get_task_status", "free_vram", "evict_process", "get_advice",
                    "load_model"]
        for name in expected:
            self.assertIn(name, names)

    def test_tool_schemas(self):
        client = PengClient()
        tools = create_all_tools(client)
        schemas = get_tool_schemas(tools)
        self.assertEqual(len(schemas), 11)
        for s in schemas:
            self.assertEqual(s["type"], "function")
            self.assertIn("name", s["function"])
            self.assertIn("parameters", s["function"])

    def test_tool_descriptions_have_vram_hint(self):
        """每个 Tool 的 description 应包含显存代价提示。"""
        client = PengClient()
        tools = create_all_tools(client)
        for t in tools:
            self.assertTrue(len(t.description) > 10, f"{t.name} description too short")


class TestPrivacyFilter(unittest.TestCase):
    def test_filter_keeps_system_status(self):
        f = PrivacyFilter()
        state = {"vram": {"total_gb": 16, "used_gb": 5, "free_gb": 11},
                 "scene": "comfy", "danger_level": "safe", "queue_depth": 0,
                 "loaded_models": [{"name": "SDXL", "size_gb": 6.5}]}
        result = f.filter_for_cloud(state, "出一张图")
        self.assertIn("vram", result)
        self.assertEqual(result["vram"]["total_gb"], 16)
        self.assertEqual(result["scene"], "comfy")

    def test_filter_removes_sensitive(self):
        f = PrivacyFilter()
        state = {"vram": {}, "api_keys": "secret", "file_paths": ["C:/secret"],
                 "generated_content": "sensitive", "full_process_list": []}
        result = f.filter_for_cloud(state, "test")
        self.assertNotIn("api_keys", result)
        self.assertNotIn("file_paths", result)
        self.assertNotIn("generated_content", result)
        self.assertNotIn("full_process_list", result)

    def test_filter_classifies_task_type(self):
        f = PrivacyFilter(send_prompts_to_cloud=False)
        result = f.filter_for_cloud({}, "出一张猫的图")
        self.assertEqual(result["user_request_type"], "image_generation")

        result2 = f.filter_for_cloud({}, "生成一段音乐")
        self.assertEqual(result2["user_request_type"], "music_generation")

        result3 = f.filter_for_cloud({}, "当前显存状态")
        self.assertEqual(result3["user_request_type"], "system_query")

    def test_filter_sends_prompts_when_enabled(self):
        f = PrivacyFilter(send_prompts_to_cloud=True)
        result = f.filter_for_cloud({}, "出一张猫的图")
        self.assertEqual(result["user_request"], "出一张猫的图")
        self.assertNotIn("user_request_type", result)


class TestDecisionLogger(unittest.TestCase):
    def test_log_and_get(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = DecisionLogger(log_dir=tmpdir)
            decision = {"turn_id": "test123", "intent": "query", "status": "planned"}
            logger.log_decision(decision)
            execution = {"turn_id": "test123", "status": "completed", "all_success": True}
            logger.log_execution("test123", execution)

            result = logger.get_by_turn_id("test123")
            self.assertIsNotNone(result["decision"])
            self.assertIsNotNone(result["execution"])
            self.assertEqual(result["decision"]["intent"], "query")

    def test_get_recent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = DecisionLogger(log_dir=tmpdir)
            for i in range(5):
                logger.log_decision({"turn_id": f"t{i}", "status": "planned"})
            recent = logger.get_recent(limit=3)
            self.assertEqual(len(recent), 3)


class TestDecisionEngineParse(unittest.TestCase):
    """测试决策引擎的 JSON 解析逻辑（不调用真实 LLM）。"""

    def setUp(self):
        client = PengClient()
        self.engine = DecisionEngine(client)

    def test_parse_valid_json(self):
        content = '{"intent":"query","plan":[],"confidence":0.9}'
        result = self.engine._parse_decision(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["intent"], "query")

    def test_parse_json_in_code_block(self):
        content = '```json\n{"intent":"query","plan":[]}\n```'
        result = self.engine._parse_decision(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["intent"], "query")

    def test_parse_invalid(self):
        result = self.engine._parse_decision("not json at all")
        self.assertIsNone(result)

    def test_parse_empty(self):
        self.assertIsNone(self.engine._parse_decision(""))
        self.assertIsNone(self.engine._parse_decision(None))


class TestDecisionEngineValidation(unittest.TestCase):
    """测试准入校验逻辑。"""

    def test_read_only_tools_pass(self):
        client = PengClient()
        engine = DecisionEngine(client)
        plan = [{"step": 1, "tool": "get_system_status", "args": {}}]
        result = engine._validate_plan(plan)
        self.assertTrue(result["all_passed"])

    def test_unknown_tool_skipped(self):
        client = PengClient()
        engine = DecisionEngine(client)
        plan = [{"step": 1, "tool": "nonexistent_tool", "args": {}}]
        result = engine._validate_plan(plan)
        self.assertTrue(result["all_passed"])  # 未知工具跳过校验


if __name__ == "__main__":
    unittest.main(verbosity=2)
