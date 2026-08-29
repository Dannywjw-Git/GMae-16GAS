# -*- coding: utf-8 -*-
"""registry.json 解析与数据完整性测试（P0-2 最小测试集）"""

import os
import sys
import json
import unittest

# 把 vram-console 目录加入 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "resources", "registry.json")


class TestRegistryFile(unittest.TestCase):
    """registry.json 文件本身的完整性测试"""

    @classmethod
    def setUpClass(cls):
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            cls.registry = json.load(f)

    def test_file_exists(self):
        self.assertTrue(os.path.exists(REGISTRY_PATH), "registry.json 不存在")

    def test_top_level_keys(self):
        """顶层必须包含的关键字段"""
        required = ["version", "ollama", "comfyui", "scenes", "gpu_guard"]
        for key in required:
            self.assertIn(key, self.registry, f"顶层缺少关键字段: {key}")

    def test_ollama_structure(self):
        """ollama 段结构完整性"""
        ollama = self.registry.get("ollama", {})
        self.assertIn("models", ollama, "ollama 缺少 models")
        self.assertIn("combos", ollama, "ollama 缺少 combos")
        self.assertIsInstance(ollama["models"], list, "ollama.models 应为列表")
        self.assertGreater(len(ollama["models"]), 0, "ollama.models 不应为空")

    def test_ollama_model_fields(self):
        """每个 ollama 模型必须包含的核心字段"""
        required_fields = ["id", "name", "vram_gb", "ctx", "category"]
        for m in self.registry.get("ollama", {}).get("models", []):
            for field in required_fields:
                self.assertIn(field, m, f"ollama 模型 {m.get('id', '?')} 缺少字段: {field}")
            # vram_gb 必须 >= 0（embedding 模型可能为 0 表示待估算/极小）
            self.assertGreaterEqual(m["vram_gb"], 0,
                               f"ollama 模型 {m['id']} 的 vram_gb 应 >= 0，当前: {m['vram_gb']}")

    def test_ollama_model_ids_unique(self):
        """ollama 模型 id 不能重复"""
        ids = [m["id"] for m in self.registry.get("ollama", {}).get("models", [])]
        self.assertEqual(len(ids), len(set(ids)), f"ollama 模型 id 有重复: {[x for x in ids if ids.count(x) > 1]}")

    def test_comfyui_structure(self):
        """comfyui 段结构完整性"""
        comfy = self.registry.get("comfyui", {})
        self.assertIn("models", comfy, "comfyui 缺少 models")
        self.assertIsInstance(comfy["models"], list, "comfyui.models 应为列表")

    def test_comfyui_model_fields(self):
        """每个 comfyui 模型必须包含的核心字段"""
        required_fields = ["id", "name", "vram_gb", "category"]
        for m in self.registry.get("comfyui", {}).get("models", []):
            for field in required_fields:
                self.assertIn(field, m, f"comfyui 模型 {m.get('id', '?')} 缺少字段: {field}")

    def test_scenes_defined(self):
        """场景定义必须包含蓝图中的 6 个场景"""
        scenes = self.registry.get("scenes", {})
        expected = ["dialogue", "comfy", "h3", "fooocus", "music", "game"]
        for s in expected:
            self.assertIn(s, scenes, f"缺少场景定义: {s}")

    def test_gpu_guard_structure(self):
        """gpu_guard 段结构完整性"""
        guard = self.registry.get("gpu_guard", {})
        self.assertIn("managed", guard, "gpu_guard 缺少 managed")
        self.assertIn("protect", guard, "gpu_guard 缺少 protect")
        self.assertIn("warn_threshold_mb", guard, "gpu_guard 缺少 warn_threshold_mb")

    def test_no_auto_entries_in_registry(self):
        """registry.json 种子文件中不应包含 auto: 前缀的动态条目（这些是运行时生成的）"""
        for m in self.registry.get("comfyui", {}).get("models", []):
            self.assertFalse(str(m.get("id", "")).startswith("auto:"),
                             f"registry 种子文件中不应有 auto: 动态条目: {m.get('id')}")

    def test_vram_values_reasonable(self):
        """所有模型的 vram_gb 应在合理范围（0 ~ 50 GB，0 表示待估算/极小模型）"""
        all_models = (self.registry.get("ollama", {}).get("models", []) +
                      self.registry.get("comfyui", {}).get("models", []))
        for m in all_models:
            vram = m.get("vram_gb", 0)
            self.assertGreaterEqual(vram, 0, f"模型 {m.get('id')} vram_gb 应 >= 0")
            self.assertLess(vram, 50, f"模型 {m.get('id')} vram_gb={vram} 异常大（>50GB）")


class TestRegistryRuntime(unittest.TestCase):
    """运行时 registry 加载与同步函数测试（需要导入 server 模块）"""

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server

    def test_registry_loaded(self):
        """server 模块应成功加载 registry.json"""
        self.assertIsInstance(self.server.REGISTRY, dict, "REGISTRY 应为 dict")
        self.assertIn("ollama", self.server.REGISTRY, "REGISTRY 应包含 ollama")

    def test_estimate_ollama_vram_fallback(self):
        """_estimate_ollama_vram 在 ollama 未运行时应回退到模型名估算"""
        # 测试几个典型模型名的估算值
        test_cases = [
            ("qwen3.5:9b", 5.0, 12.0),   # 9B * 0.55 + 1 ≈ 5.95
            ("qwen3:27b-q4km", 10.0, 20.0),  # 27B * 0.55 + 1 ≈ 15.85
            ("llama3.2:3b", 2.0, 8.0),    # 3B * 0.75 + 1 ≈ 3.25
        ]
        for name, low, high in test_cases:
            vram = self.server._estimate_ollama_vram(name)
            self.assertGreater(vram, low, f"{name} 估算值 {vram} 应 > {low}")
            self.assertLess(vram, high, f"{name} 估算值 {vram} 应 < {high}")

    def test_estimate_ollama_vram_unknown(self):
        """无法解析参数的模型名应使用默认 7B 估算"""
        vram = self.server._estimate_ollama_vram("unknown-model")
        self.assertGreater(vram, 3.0, "未知模型应使用默认 7B 估算，值应 > 3")
        self.assertLess(vram, 15.0, "未知模型估算值应 < 15")


if __name__ == "__main__":
    unittest.main(verbosity=2)
