#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 核心逻辑单元测试
- 测试纯逻辑函数，不依赖外部服务
- 运行方式：python -m pytest tests/test_core_logic.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.utils import _safe_model_name
from services.status import _infer_scene_from_containers


class TestSafeModelName:
    """测试模型名安全校验"""

    def test_valid_normal_model(self):
        ok, name = _safe_model_name("qwen3.5:9b")
        assert ok is True
        assert name == "qwen3.5:9b"

    def test_valid_with_slash(self):
        ok, name = _safe_model_name("llama3.1:8b-instruct-q4_K_M")
        assert ok is True

    def test_empty_name(self):
        ok, msg = _safe_model_name("")
        assert ok is False
        assert "empty" in msg

    def test_none_name(self):
        ok, msg = _safe_model_name(None)
        assert ok is False

    def test_path_traversal(self):
        ok, msg = _safe_model_name("../../etc/passwd")
        assert ok is False
        assert ".." in msg

    def test_absolute_path(self):
        ok, msg = _safe_model_name("/etc/passwd")
        assert ok is False
        assert "absolute" in msg.lower() or "path" in msg.lower()

    def test_too_long(self):
        long_name = "a" * 129
        ok, msg = _safe_model_name(long_name)
        assert ok is False
        assert "too long" in msg

    def test_special_chars(self):
        ok, msg = _safe_model_name("model;rm -rf /")
        assert ok is False
        assert "invalid" in msg.lower()


class TestInferScene:
    """测试场景推断逻辑"""

    def test_comfy_scene(self):
        scene = _infer_scene_from_containers({"comfyui", "ollama"})
        assert scene == "comfy"

    def test_fooocus_scene(self):
        scene = _infer_scene_from_containers({"fooocus", "ollama"})
        assert scene == "fooocus"

    def test_dialogue_scene(self):
        scene = _infer_scene_from_containers({"ollama"})
        assert scene == "dialogue"

    def test_empty_containers(self):
        scene = _infer_scene_from_containers(set())
        assert scene == "dialogue"

    def test_fooocus_priority_over_comfy(self):
        """fooocus 优先级高于 comfy"""
        scene = _infer_scene_from_containers({"fooocus", "comfyui"})
        assert scene == "fooocus"


class TestVRAMConstants:
    """测试显存常量定义"""

    def test_baseline_noise(self):
        from core.config import VRAM_BASELINE_NOISE_MB
        assert VRAM_BASELINE_NOISE_MB == 1200
        assert isinstance(VRAM_BASELINE_NOISE_MB, int)

    def test_comfy_resident_threshold(self):
        from core.config import COMFY_MODEL_RESIDENT_THRESHOLD_MB
        assert COMFY_MODEL_RESIDENT_THRESHOLD_MB == 1024

    def test_diff_threshold(self):
        from core.config import VRAM_DIFF_THRESHOLD_MB
        assert VRAM_DIFF_THRESHOLD_MB == 1000

    def test_loading_speed(self):
        from core.config import VRAM_LOADING_SPEED_MB_PER_S
        assert VRAM_LOADING_SPEED_MB_PER_S == 500

    def test_loading_overhead(self):
        from core.config import VRAM_LOADING_OVERHEAD_MB
        assert VRAM_LOADING_OVERHEAD_MB == 2000


class TestConfigLoading:
    """测试配置加载"""

    def test_registry_loaded(self):
        from core.config import REGISTRY
        assert isinstance(REGISTRY, dict)
        assert "ollama" in REGISTRY or "comfyui" in REGISTRY

    def test_port_config(self):
        from core.config import PORT
        assert PORT == 8787
        assert isinstance(PORT, int)

    def test_api_token_exists(self):
        from core.config import API_TOKEN
        # Token 可能为空（未配置），但必须是字符串
        assert isinstance(API_TOKEN, str)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
