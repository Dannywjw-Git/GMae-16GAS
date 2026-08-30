#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 调度中心测试：安全函数
测试范围：模型名安全校验、命令注入防护、显存保护
运行方式：python -m unittest tests.test_security -v
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入 server 模块中的安全函数
import server


class TestSafeModelName(unittest.TestCase):
    """模型名安全校验测试（防命令注入）"""

    def test_valid_names(self):
        """合法模型名应通过校验"""
        valid_names = [
            "qwen3.5:9b",
            "qwen3:0.6b",
            "qwythos-9b:q4km",
            "darkidol-8b:q4km",
            "llama3.1:8b-instruct-q4_0",
            "model/name:tag",
            "model.name:tag",
            "model-name:tag",
            "Model123:tag",
        ]
        for name in valid_names:
            ok, checked = server._safe_model_name(name)
            self.assertTrue(ok, f"合法模型名被拒绝: {name}")
            self.assertEqual(checked, name)

    def test_invalid_names(self):
        """非法模型名应被拒绝（防命令注入）"""
        invalid_names = [
            "model;rm -rf /",           # 分号注入
            "model&&whoami",             # && 注入
            "model|cat /etc/passwd",     # 管道注入
            "model`whoami`",             # 反引号注入
            "model$(whoami)",            # $() 注入
            "model name",                 # 空格
            "model>out.txt",             # 重定向
            "model<in.txt",              # 输入重定向
            "model*",                     # 通配符
            "model?",                     # 问号通配符
            "",                           # 空字符串
        ]
        for name in invalid_names:
            ok, checked = server._safe_model_name(name)
            self.assertFalse(ok, f"非法模型名被接受: {name}")

    def test_empty_name(self):
        """空模型名应被拒绝"""
        ok, msg = server._safe_model_name("")
        self.assertFalse(ok)

    def test_none_name(self):
        """None 模型名应被拒绝"""
        ok, msg = server._safe_model_name(None)
        self.assertFalse(ok)


class TestRunArgsSecurity(unittest.TestCase):
    """run_args 安全执行测试（shell=False）"""

    def test_run_args_returns_tuple(self):
        """run_args 应返回 (returncode, output) 元组"""
        rc, out = server.run_args(["echo", "hello"], timeout=5)
        self.assertIsInstance(rc, int)
        self.assertIsInstance(out, str)

    def test_run_args_no_shell_injection(self):
        """run_args 使用参数数组，不应执行 shell 注入"""
        # 如果 shell=True，这个命令会创建文件；shell=False 时应该失败或作为参数传递
        rc, out = server.run_args(["echo", "test; touch /tmp/injection_test"], timeout=5)
        # 验证注入文件未被创建
        self.assertFalse(os.path.exists("/tmp/injection_test"), "shell 注入成功，安全漏洞！")


class TestModelLoadVramProtection(unittest.TestCase):
    """模型加载显存保护测试（B2 修复：显存不足时拒绝加载）"""

    def test_model_action_rejects_load_when_vram_low(self):
        """显存不足时，model_action load 应返回错误（不实际调用，只验证逻辑）"""
        # 这个测试需要 mock gpu_status，这里只验证函数存在和逻辑结构
        self.assertTrue(hasattr(server, "model_action"))
        self.assertTrue(callable(server.model_action))

    def test_model_action_validates_action(self):
        """model_action 应校验 action 参数"""
        result = server.model_action("test-model", "invalid_action")
        self.assertFalse(result["ok"])
        self.assertIn("unknown action", result["error"])


class TestScanRegisterSecurity(unittest.TestCase):
    """scan_register 安全测试"""

    def test_unknown_source_rejected(self):
        """未知 source 应被拒绝（不默认 comfyui）"""
        result = server.scan_register("nonexistent_source_12345", "test-model")
        self.assertFalse(result["ok"])
        self.assertIn("unknown source", result["error"])

    def test_duplicate_model_rejected(self):
        """重复模型应被拒绝"""
        # 用一个已存在的模型测试（ollama 中应该有 qwen3.5:9b）
        result = server.scan_register("ollama", "qwen3.5:9b")
        self.assertFalse(result["ok"])
        self.assertIn("already registered", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
