#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GMae v0.3.1 M-Eng 单元测试"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from meng.model_scanner import ModelScanner
from meng.p0_benchmark import P0Benchmark
from meng.benchmark_engine import BenchmarkEngine


class TestModelScanner(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.registry_path = os.path.join(self.tmpdir, "registry.json")
        with open(self.registry_path, "w") as f:
            json.dump({
                "ollama": {"models": [{"id": "qwen3.5:9b"}]},
                "comfyui": {"models": [{"id": "SDXL"}]}
            }, f)
        self.scanner = ModelScanner(registry_path=self.registry_path)

    def test_get_registered_ids(self):
        ids = self.scanner.get_registered_ids()
        self.assertIn("qwen3.5:9b", ids)
        self.assertIn("SDXL", ids)

    @patch.object(ModelScanner, "scan_ollama")
    def test_find_new_models(self, mock_scan):
        mock_scan.return_value = [
            {"name": "qwen3.5:9b", "size": 9.9e9},
            {"name": "new-model:7b", "size": 4.5e9},
            {"name": "bge-m3:latest", "size": 1.2e9},  # 嵌入模型应跳过
        ]
        new = self.scanner.find_new_models()
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["id"], "new-model:7b")

    @patch.object(ModelScanner, "scan_ollama")
    def test_find_new_models_empty(self, mock_scan):
        mock_scan.return_value = []
        new = self.scanner.find_new_models()
        self.assertEqual(len(new), 0)


class TestP0Benchmark(unittest.TestCase):
    def setUp(self):
        self.bench = P0Benchmark()

    @patch("urllib.request.urlopen")
    def test_chat(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "message": {"content": "hello"},
            "prompt_eval_count": 10,
            "eval_count": 20,
            "total_duration": 1e9,
            "load_duration": 1e8,
            "prompt_eval_duration": 2e8,
            "eval_duration": 5e8,
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: False
        mock_urlopen.return_value = mock_resp

        result = self.bench._chat("test:1b", [{"role": "user", "content": "hi"}])
        self.assertEqual(result["content"], "hello")
        self.assertEqual(result["prompt_eval_count"], 10)
        self.assertEqual(result["eval_count"], 20)
        self.assertGreater(result["gen_tok_s"] if "gen_tok_s" in result else 0, -1)


class TestBenchmarkEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.registry_path = os.path.join(self.tmpdir, "registry.json")
        with open(self.registry_path, "w") as f:
            json.dump({"ollama": {"models": []}, "last_updated": "2026-01-01"}, f)
        self.engine = BenchmarkEngine(registry_path=self.registry_path)

    def test_write_to_registry(self):
        result = {
            "model": "test:1b",
            "timestamp": "2026-09-01 12:00:00",
            "status": "completed",
            "vram": {"model_vram_gb": 2.5},
            "speed": {"prefill_tok_s": 500, "gen_tok_s": 50},
            "smoke": {"passed": True},
        }
        ok = self.engine.write_to_registry("test:1b", result)
        self.assertTrue(ok)

        with open(self.registry_path, "r") as f:
            reg = json.load(f)
        models = reg["ollama"]["models"]
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["id"], "test:1b")
        self.assertEqual(models[0]["vram_gb"], 2.5)
        self.assertTrue(models[0]["vram_verified"])
        self.assertEqual(models[0]["benchmark_level"], "P0")

    def test_log_result(self):
        result = {"model": "test:1b", "status": "completed"}
        self.engine.log_result(result)
        self.assertTrue(os.path.exists(self.engine._results_log))

    @patch.object(BenchmarkEngine, "is_system_idle")
    @patch.object(ModelScanner, "find_new_models")
    def test_run_once_no_new_models(self, mock_scan, mock_idle):
        mock_scan.return_value = []
        result = self.engine.run_once()
        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["new_models"], 0)

    @patch.object(BenchmarkEngine, "is_system_idle")
    @patch.object(ModelScanner, "find_new_models")
    def test_run_once_system_busy(self, mock_scan, mock_idle):
        mock_scan.return_value = [{"id": "new:1b", "size_gb": 1.0}]
        mock_idle.return_value = (False, "显存不足")
        result = self.engine.run_once()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "显存不足")

    def test_pause_resume(self):
        self.engine._pause_event.set()
        self.engine.pause()
        self.assertFalse(self.engine._pause_event.is_set())
        self.engine.resume()
        self.assertTrue(self.engine._pause_event.is_set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
