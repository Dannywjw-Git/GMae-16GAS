"""
GMae v0.3.1 — 准入闸门模块单元测试
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import admission_gate
from admission_gate import GateContext


def make_ctx(**kwargs):
    """创建测试用 GateContext，默认 16GB 卡，空闲 8GB"""
    defaults = dict(
        vram_total_mb=16384,
        vram_used_mb=8000,
        vram_free_mb=8384,
        base_noise_mb=1200,
        current_scene="dialogue",
        loaded_ollama_models=[],
        loaded_comfy_models=[],
        comfyui_running=False,
        fooocus_running=False,
        ollama_serve_count=1,
        registry_models={
            "comfyui": [
                {"id": "SDXL", "name": "SDXL 1.0", "vram_gb": 6.5, "exclusive": False},
                {"id": "Flux-Q5", "name": "Flux.1 dev Q5", "vram_gb": 13.0, "exclusive": True},
            ],
            "ollama": [
                {"id": "qwen3.5:9b", "name": "qwen3.5:9b", "vram_gb": 6.6, "exclusive": False, "ctx": 8192},
                {"id": "qwen3.5:0.8b", "name": "qwen3.5:0.8b", "vram_gb": 3.5, "exclusive": False, "ctx": 65536},
            ],
        },
        danger_thresholds={"danger_mb": 15073, "free_target_mb": 2457},
    )
    defaults.update(kwargs)
    return GateContext(**defaults)


class TestFormatCheck(unittest.TestCase):
    """防线1：格式校验"""

    def test_unknown_action_rejected(self):
        r = admission_gate.check("destroy_gpu", {}, make_ctx())
        self.assertFalse(r["allowed"])
        self.assertIn("未知 action", r["reason"])

    def test_missing_required_args(self):
        r = admission_gate.check("switch_scene", {}, make_ctx())
        self.assertFalse(r["allowed"])
        self.assertIn("缺少必填参数", r["reason"])

    def test_valid_action_passes_format(self):
        r = admission_gate.check("free_vram", {}, make_ctx())
        self.assertTrue(r["checks"]["format"]["passed"])


class TestRuleR1(unittest.TestCase):
    """R1: 禁止两个大模型（≥5G）同时常驻"""

    def test_two_large_models_rejected(self):
        """已有 9b(6.6G)，再加载 SDXL(6.5G) 应被 R1 拦截"""
        ctx = make_ctx(loaded_ollama_models=[{"name": "qwen3.5:9b", "size_gb": 6.6}])
        r = admission_gate.check("submit_task", {"model": "SDXL", "params": {}}, ctx)
        self.assertFalse(r["allowed"])
        self.assertIn("R1", r["violated_rules"])

    def test_small_model_allowed_with_large(self):
        """已有 9b，加载 0.8b(3.5G) 不触发 R1"""
        ctx = make_ctx(loaded_ollama_models=[{"name": "qwen3.5:9b", "size_gb": 6.6}])
        r = admission_gate.check("load_model", {"model": "qwen3.5:0.8b"}, ctx)
        # R1 不触发（0.8b < 5G），但可能有其他检查
        self.assertNotIn("R1", r["violated_rules"])

    def test_already_loaded_model_not_violated(self):
        """已加载的模型再次加载不触发 R1"""
        ctx = make_ctx(loaded_ollama_models=[{"name": "qwen3.5:9b", "size_gb": 6.6}])
        r = admission_gate.check("load_model", {"model": "qwen3.5:9b"}, ctx)
        self.assertNotIn("R1", r["violated_rules"])


class TestRuleR2(unittest.TestCase):
    """R2: 独占模型不与其他AI负载共存"""

    def test_flux_with_other_model_rejected(self):
        """已有 9b，加载 Flux(独占) 应被 R2 拦截"""
        ctx = make_ctx(loaded_ollama_models=[{"name": "qwen3.5:9b", "size_gb": 6.6}])
        r = admission_gate.check("submit_task", {"model": "Flux-Q5", "params": {}}, ctx)
        self.assertIn("R2", r["violated_rules"])

    def test_exclusive_loaded_then_other_rejected(self):
        """已有 Flux 加载，再加载其他模型应被 R2 拦截"""
        ctx = make_ctx(loaded_comfy_models=[{"id": "Flux-Q5", "name": "Flux", "vram_gb": 13.0, "exclusive": True}])
        r = admission_gate.check("load_model", {"model": "qwen3.5:0.8b"}, ctx)
        self.assertIn("R2", r["violated_rules"])


class TestRuleR3(unittest.TestCase):
    """R3: 禁止 num_ctx 超 8192"""

    def test_ctx_over_8k_rejected(self):
        r = admission_gate.check("load_model", {"model": "qwen3.5:9b", "ctx": 32768}, make_ctx())
        self.assertIn("R3", r["violated_rules"])

    def test_ctx_8k_allowed(self):
        r = admission_gate.check("load_model", {"model": "qwen3.5:9b", "ctx": 8192}, make_ctx())
        self.assertNotIn("R3", r["violated_rules"])


class TestRuleR7(unittest.TestCase):
    """R7: 禁止未登记模型占用显存"""

    def test_unregistered_model_rejected(self):
        r = admission_gate.check("load_model", {"model": "unknown:7b"}, make_ctx())
        self.assertIn("R7", r["violated_rules"])

    def test_registered_model_allowed(self):
        r = admission_gate.check("load_model", {"model": "qwen3.5:0.8b"}, make_ctx())
        self.assertNotIn("R7", r["violated_rules"])


class TestBudgetCheck(unittest.TestCase):
    """防线3：预算校验"""

    def test_insufficient_vram_rejected(self):
        """空闲显存不足时应被预算校验拦截"""
        ctx = make_ctx(vram_free_mb=1024, vram_used_mb=15360)
        r = admission_gate.check("load_model", {"model": "SDXL"}, ctx)
        self.assertFalse(r["allowed"])
        self.assertGreater(r["required_free_gb"], 0)

    def test_sufficient_vram_passes(self):
        """空闲显存充足时预算校验通过"""
        ctx = make_ctx(vram_free_mb=12000, vram_used_mb=4000)
        r = admission_gate.check("load_model", {"model": "qwen3.5:0.8b"}, ctx)
        self.assertTrue(r["checks"]["budget"]["passed"])


class TestFullCheck(unittest.TestCase):
    """完整闸门检查"""

    def test_all_passes(self):
        """所有检查通过的场景"""
        ctx = make_ctx(vram_free_mb=12000, vram_used_mb=4000)
        r = admission_gate.check("load_model", {"model": "qwen3.5:0.8b"}, ctx)
        self.assertTrue(r["allowed"])
        self.assertEqual(r["violated_rules"], [])

    def test_result_structure(self):
        """返回结果结构完整"""
        r = admission_gate.check("free_vram", {}, make_ctx())
        self.assertIn("allowed", r)
        self.assertIn("reason", r)
        self.assertIn("required_free_gb", r)
        self.assertIn("violated_rules", r)
        self.assertIn("checks", r)
        self.assertIn("format", r["checks"])
        self.assertIn("rules", r["checks"])
        self.assertIn("budget", r["checks"])


if __name__ == "__main__":
    unittest.main()
