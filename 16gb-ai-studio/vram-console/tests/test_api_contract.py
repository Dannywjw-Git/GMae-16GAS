# -*- coding: utf-8 -*-
"""API 数据结构契约测试（P0-2 最小测试集）— 验证后端返回字段与前端消费对齐"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHealthContract(unittest.TestCase):
    """/api/health 返回结构契约"""

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server

    def test_health_returns_dict(self):
        result = self.server.health_check()
        self.assertIsInstance(result, dict, "health_check 应返回 dict")

    def test_health_has_required_fields(self):
        result = self.server.health_check()
        required = ["ok", "ts", "services"]
        for field in required:
            self.assertIn(field, result, f"health_check 缺少字段: {field}")

    def test_health_services_structure(self):
        result = self.server.health_check()
        services = result.get("services", {})
        # 至少应包含 gpu 服务状态
        self.assertIn("gpu", services, "services 应包含 gpu")
        gpu = services["gpu"]
        self.assertIn("ok", gpu, "gpu 状态应包含 ok")
        self.assertIn("free_mb", gpu, "gpu 状态应包含 free_mb")
        self.assertIn("total_mb", gpu, "gpu 状态应包含 total_mb")

    def test_health_ok_is_bool(self):
        result = self.server.health_check()
        self.assertIsInstance(result["ok"], bool, "health ok 应为布尔值")


class TestRegistryViewContract(unittest.TestCase):
    """/api/registry 返回结构契约"""

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server

    def test_registry_view_returns_dict(self):
        result = self.server.registry_view()
        self.assertIsInstance(result, dict, "registry_view 应返回 dict")

    def test_registry_view_has_required_fields(self):
        result = self.server.registry_view()
        required = ["ok", "ollama_models", "ollama_combos", "comfyui_models",
                    "scenes", "gpu_guard", "sync"]
        for field in required:
            self.assertIn(field, result, f"registry_view 缺少字段: {field}")

    def test_registry_view_ollama_models_structure(self):
        result = self.server.registry_view()
        models = result.get("ollama_models", [])
        self.assertIsInstance(models, list, "ollama_models 应为列表")
        if models:
            m = models[0]
            # 核心字段（前端消费）
            core_fields = ["id", "name", "vram_gb", "category", "installed"]
            for field in core_fields:
                self.assertIn(field, m, f"ollama 模型缺少核心字段: {field}")

    def test_registry_view_comfyui_models_structure(self):
        result = self.server.registry_view()
        models = result.get("comfyui_models", [])
        self.assertIsInstance(models, list, "comfyui_models 应为列表")
        if models:
            m = models[0]
            core_fields = ["id", "name", "vram_gb", "category", "installed"]
            for field in core_fields:
                self.assertIn(field, m, f"comfyui 模型缺少核心字段: {field}")

    def test_registry_view_scenes_is_dict(self):
        result = self.server.registry_view()
        self.assertIsInstance(result.get("scenes"), dict, "scenes 应为 dict")

    def test_registry_view_gpu_guard_structure(self):
        result = self.server.registry_view()
        guard = result.get("gpu_guard", {})
        self.assertIn("managed", guard, "gpu_guard 应包含 managed")
        self.assertIn("protect", guard, "gpu_guard 应包含 protect")


class TestBudgetEngineContract(unittest.TestCase):
    """/api/budget 返回结构契约"""

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server

    def test_budget_engine_returns_dict(self):
        result = self.server.budget_engine()
        self.assertIsInstance(result, dict, "budget_engine 应返回 dict")

    def test_budget_engine_has_required_fields(self):
        result = self.server.budget_engine()
        required = ["ok", "total_gb", "used_gb", "avail_gb", "models"]
        for field in required:
            self.assertIn(field, result, f"budget_engine 缺少字段: {field}")

    def test_budget_engine_gpu_structure(self):
        result = self.server.budget_engine()
        # budget_engine 顶层直接返回显存字段（GB），而非嵌套 gpu 对象
        self.assertIn("total_gb", result, "应包含 total_gb")
        self.assertIn("used_gb", result, "应包含 used_gb")
        self.assertIn("avail_gb", result, "应包含 avail_gb")
        self.assertIsInstance(result["total_gb"], (int, float), "total_gb 应为数字")
        self.assertGreater(result["total_gb"], 0, "total_gb 应大于 0")

    def test_budget_engine_models_decision(self):
        result = self.server.budget_engine()
        models = result.get("models", [])
        self.assertIsInstance(models, list, "models 应为列表")
        valid_decisions = ["ok", "free_L1", "free_L2", "reject"]
        for m in models:
            self.assertIn("id", m, "预算模型应包含 id")
            self.assertIn("decision", m, "预算模型应包含 decision")
            self.assertIn(m["decision"], valid_decisions,
                           f"模型 {m.get('id')} 的 decision={m['decision']} 不在有效值中")
            self.assertIn("vram_gb", m, "预算模型应包含 vram_gb")
            self.assertIn("need_free_gb", m, "预算模型应包含 need_free_gb")
            self.assertIn("note", m, "预算模型应包含 note")


class TestQueueSnapshotContract(unittest.TestCase):
    """/api/queue 返回结构契约"""

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server

    def test_queue_snapshot_returns_dict(self):
        result = self.server.queue_snapshot()
        self.assertIsInstance(result, dict, "queue_snapshot 应返回 dict")

    def test_queue_snapshot_has_required_fields(self):
        result = self.server.queue_snapshot()
        required = ["ok", "queue", "tasks", "worker_alive", "client_id"]
        for field in required:
            self.assertIn(field, result, f"queue_snapshot 缺少字段: {field}")

    def test_queue_snapshot_tasks_structure(self):
        result = self.server.queue_snapshot()
        tasks = result.get("tasks", [])
        self.assertIsInstance(tasks, list, "tasks 应为列表")
        valid_status = ["queued", "precheck", "freeing", "running", "done", "failed", "canceled"]
        for t in tasks:
            self.assertIn("id", t, "任务应包含 id")
            self.assertIn("model", t, "任务应包含 model")
            self.assertIn("status", t, "任务应包含 status")
            self.assertIn(t["status"], valid_status,
                          f"任务 {t.get('id')} 的 status={t['status']} 不在有效值中")
            self.assertIn("created", t, "任务应包含 created")


class TestAuthStatusContract(unittest.TestCase):
    """/api/auth/status 返回结构契约"""

    def test_auth_status_returns_dict(self):
        import auth
        result = auth.auth_status()
        self.assertIsInstance(result, dict, "auth_status 应返回 dict")

    def test_auth_status_has_required_fields(self):
        import auth
        result = auth.auth_status()
        required = ["has_admin", "admin_email", "smtp_configured", "smtp_user", "active_sessions"]
        for field in required:
            self.assertIn(field, result, f"auth_status 缺少字段: {field}")

    def test_auth_status_has_admin_is_bool(self):
        import auth
        result = auth.auth_status()
        self.assertIsInstance(result["has_admin"], bool, "has_admin 应为布尔值")
        self.assertIsInstance(result["smtp_configured"], bool, "smtp_configured 应为布尔值")
        self.assertIsInstance(result["active_sessions"], int, "active_sessions 应为整数")


class TestSafeModelName(unittest.TestCase):
    """模型名安全校验测试（防注入）"""

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server

    def test_safe_model_name_normal(self):
        """正常模型名应通过校验"""
        ok, name = self.server._safe_model_name("qwen3.5:9b")
        self.assertTrue(ok, f"正常模型名应通过: {name}")

    def test_safe_model_name_with_path(self):
        """包含路径穿越的模型名应被拒绝"""
        ok, name = self.server._safe_model_name("../../../etc/passwd")
        self.assertFalse(ok, "路径穿越应被拒绝")

    def test_safe_model_name_with_shell(self):
        """包含 shell 元字符的模型名应被拒绝"""
        ok, name = self.server._safe_model_name("test; rm -rf /")
        self.assertFalse(ok, "shell 元字符应被拒绝")

    def test_safe_model_name_with_pipe(self):
        ok, name = self.server._safe_model_name("test | cat /etc/passwd")
        self.assertFalse(ok, "管道符应被拒绝")

    def test_safe_model_name_with_backtick(self):
        ok, name = self.server._safe_model_name("test`whoami`")
        self.assertFalse(ok, "反引号应被拒绝")

    def test_safe_model_name_empty(self):
        ok, name = self.server._safe_model_name("")
        self.assertFalse(ok, "空模型名应被拒绝")


if __name__ == "__main__":
    unittest.main(verbosity=2)
