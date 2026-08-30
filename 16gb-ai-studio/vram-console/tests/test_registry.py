#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 调度中心测试：registry.json 解析与数据结构
测试范围：registry.json 有效性、模型字段完整性、场景/组合配置、健康度检查
运行方式：python -m unittest tests.test_registry -v
"""
import unittest
import json
import os
import sys

# 把上级目录加入 path，以便 import server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "registry.json")


class TestRegistryFile(unittest.TestCase):
    """registry.json 文件有效性测试"""

    def setUp(self):
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            self.reg = json.load(f)

    def test_file_exists(self):
        """registry.json 文件存在且可读"""
        self.assertTrue(os.path.exists(REGISTRY_PATH))

    def test_valid_json(self):
        """registry.json 是合法 JSON"""
        self.assertIsInstance(self.reg, dict)

    def test_top_level_keys(self):
        """顶层必须包含的键"""
        required = ["version", "ollama", "comfyui", "scenes", "system"]
        for key in required:
            self.assertIn(key, self.reg, f"registry 缺少顶层键: {key}")

    def test_system_config(self):
        """系统配置必须包含显存相关参数"""
        sys_cfg = self.reg.get("system", {})
        self.assertIn("gpu_vram_total_gb", sys_cfg)
        self.assertIn("gpu_base_noise_gb", sys_cfg)
        self.assertIn("vram_reserve_gb", sys_cfg)
        # 数值合理性
        self.assertGreater(sys_cfg["gpu_vram_total_gb"], 0)
        self.assertGreaterEqual(sys_cfg["gpu_base_noise_gb"], 0)
        self.assertGreater(sys_cfg["vram_reserve_gb"], 0)


class TestOllamaModels(unittest.TestCase):
    """Ollama 模型数据结构测试"""

    def setUp(self):
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            self.reg = json.load(f)
        self.models = self.reg.get("ollama", {}).get("models", [])

    def test_models_is_list(self):
        """ollama.models 必须是列表"""
        self.assertIsInstance(self.models, list)
        self.assertGreater(len(self.models), 0, "ollama 模型列表不能为空")

    def test_model_required_fields(self):
        """每个模型必须包含的字段"""
        required = ["id", "name", "vram_gb", "category"]
        for m in self.models:
            for field in required:
                self.assertIn(field, m, f"模型 {m.get('id', '?')} 缺少字段: {field}")

    def test_model_vram_positive(self):
        """模型显存必须大于 0"""
        for m in self.models:
            self.assertGreater(m["vram_gb"], 0, f"模型 {m['id']} 显存必须大于 0")

    def test_model_category_valid(self):
        """模型 category 必须是已知类型"""
        valid_cats = ["llm", "image", "video", "audio", "music", "embedding", "reranker", "unknown"]
        for m in self.models:
            self.assertIn(m["category"], valid_cats, f"模型 {m['id']} category 无效: {m['category']}")

    def test_no_filename_ids(self):
        """模型 id 不应是文件名（不应以 .safetensors/.gguf/.bin 结尾）"""
        for m in self.models:
            mid = m["id"]
            self.assertFalse(mid.endswith(".safetensors"), f"模型 id 是文件名: {mid}")
            self.assertFalse(mid.endswith(".gguf"), f"模型 id 是文件名: {mid}")
            self.assertFalse(mid.endswith(".bin"), f"模型 id 是文件名: {mid}")

    def test_no_duplicate_ids(self):
        """模型 id 不能重复"""
        ids = [m["id"] for m in self.models]
        self.assertEqual(len(ids), len(set(ids)), f"ollama 模型 id 重复: {[x for x in ids if ids.count(x) > 1]}")


class TestComfyuiModels(unittest.TestCase):
    """ComfyUI 模型数据结构测试"""

    def setUp(self):
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            self.reg = json.load(f)
        self.models = self.reg.get("comfyui", {}).get("models", [])

    def test_models_is_list(self):
        self.assertIsInstance(self.models, list)
        self.assertGreater(len(self.models), 0)

    def test_model_required_fields(self):
        required = ["id", "name", "vram_gb", "category"]
        for m in self.models:
            for field in required:
                self.assertIn(field, m, f"ComfyUI 模型 {m.get('id', '?')} 缺少字段: {field}")

    def test_no_filename_ids(self):
        for m in self.models:
            mid = m["id"]
            self.assertFalse(mid.endswith(".safetensors"), f"ComfyUI 模型 id 是文件名: {mid}")
            self.assertFalse(mid.endswith(".gguf"), f"ComfyUI 模型 id 是文件名: {mid}")


class TestScenes(unittest.TestCase):
    """场景配置测试"""

    def setUp(self):
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            self.reg = json.load(f)
        self.scenes = self.reg.get("scenes", {})

    def test_scenes_is_dict(self):
        self.assertIsInstance(self.scenes, dict)
        self.assertGreater(len(self.scenes), 0, "场景配置不能为空")

    def test_scene_required_fields(self):
        """每个场景必须包含的字段"""
        required = ["label", "vram_budget_gb", "containers"]
        for sid, s in self.scenes.items():
            for field in required:
                self.assertIn(field, s, f"场景 {sid} 缺少字段: {field}")

    def test_scene_budget_positive(self):
        """场景显存预算必须大于 0"""
        for sid, s in self.scenes.items():
            self.assertGreater(s["vram_budget_gb"], 0, f"场景 {sid} 显存预算必须大于 0")

    def test_known_scenes(self):
        """必须包含的核心场景"""
        required_scenes = ["dialogue", "comfy"]
        for s in required_scenes:
            self.assertIn(s, self.scenes, f"缺少核心场景: {s}")


class TestCombos(unittest.TestCase):
    """模型组合配置测试"""

    def setUp(self):
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            self.reg = json.load(f)
        self.combos = self.reg.get("ollama", {}).get("combos", {})

    def test_combos_is_dict(self):
        self.assertIsInstance(self.combos, dict)

    def test_combo_structure(self):
        """每个组合必须包含 load 和 stop 字段"""
        for cid, c in self.combos.items():
            self.assertIn("load", c, f"组合 {cid} 缺少 load 字段")
            self.assertIn("stop", c, f"组合 {cid} 缺少 stop 字段")


class TestScannerConfig(unittest.TestCase):
    """扫描器配置测试"""

    def setUp(self):
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            self.reg = json.load(f)
        self.scanner = self.reg.get("scanner", {})

    def test_scanner_has_targets(self):
        """扫描器必须配置 targets"""
        self.assertIn("targets", self.scanner, "scanner 缺少 targets 配置")
        self.assertIsInstance(self.scanner["targets"], list)

    def test_target_structure(self):
        """每个扫描目标必须包含的字段"""
        required = ["source", "type"]
        for t in self.scanner.get("targets", []):
            for field in required:
                self.assertIn(field, t, f"扫描目标缺少字段: {field}")
            self.assertIn(t["type"], ["docker_dir", "api"], f"扫描目标 type 无效: {t['type']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
