"""
GMae v0.3.1 — 动态阈值模块单元测试
"""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import thresholds


class TestDynamicThresholds(unittest.TestCase):
    """测试 DynamicThresholds 计算逻辑"""

    def test_16gb_card_thresholds(self):
        """16GB 卡的阈值计算"""
        t = thresholds.DynamicThresholds(vram_total_mb=16384, base_noise_mb=1200)
        self.assertEqual(t.critical_mb, int(16384 * 0.97))
        self.assertEqual(t.danger_mb, int(16384 * 0.92))
        self.assertEqual(t.warning_mb, int(16384 * 0.85))
        self.assertAlmostEqual(t.critical_mb / 1024, 15.5, places=1)
        self.assertAlmostEqual(t.danger_mb / 1024, 14.7, places=1)

    def test_8gb_card_thresholds(self):
        """8GB 卡的阈值计算（通用化验证）"""
        t = thresholds.DynamicThresholds(vram_total_mb=8192, base_noise_mb=800)
        self.assertEqual(t.critical_mb, int(8192 * 0.97))
        self.assertEqual(t.danger_mb, int(8192 * 0.92))
        self.assertAlmostEqual(t.critical_mb / 1024, 7.8, places=1)

    def test_24gb_card_thresholds(self):
        """24GB 卡的阈值计算"""
        t = thresholds.DynamicThresholds(vram_total_mb=24576, base_noise_mb=1500)
        self.assertAlmostEqual(t.danger_mb / 1024, 22.1, places=1)
        self.assertAlmostEqual(t.warning_mb / 1024, 20.4, places=1)

    def test_usable_vram(self):
        """可用显存 = 总显存 - 底噪"""
        t = thresholds.DynamicThresholds(vram_total_mb=16384, base_noise_mb=1200)
        self.assertEqual(t.usable_mb, 16384 - 1200)

    def test_free_target_minimum(self):
        """free_target 至少 2GB"""
        t = thresholds.DynamicThresholds(vram_total_mb=8192, base_noise_mb=800)
        self.assertGreaterEqual(t.free_target_mb, 2048)

    def test_free_target_percentage(self):
        """大显存卡的 free_target 按百分比计算"""
        t = thresholds.DynamicThresholds(vram_total_mb=49152, base_noise_mb=2000)
        self.assertEqual(t.free_target_mb, int(49152 * 0.15))

    def test_emergency_free(self):
        """紧急阈值 = 总显存 12.5%，至少 1GB"""
        t = thresholds.DynamicThresholds(vram_total_mb=16384, base_noise_mb=1200)
        self.assertEqual(t.emergency_free_mb, max(1024, int(16384 * 0.125)))

    def test_warning_free(self):
        """警告阈值 = 总显存 25%，至少 2GB"""
        t = thresholds.DynamicThresholds(vram_total_mb=16384, base_noise_mb=1200)
        self.assertEqual(t.warning_free_mb, max(2048, int(16384 * 0.25)))

    def test_danger_level(self):
        """危险等级判断"""
        t = thresholds.DynamicThresholds(vram_total_mb=16384, base_noise_mb=1200)
        self.assertEqual(t.danger_level(500), "critical")
        self.assertEqual(t.danger_level(1500), "danger")
        self.assertEqual(t.danger_level(3000), "warning")
        self.assertEqual(t.danger_level(8000), "safe")

    def test_to_dict(self):
        """to_dict 输出结构"""
        t = thresholds.DynamicThresholds(vram_total_mb=16384, base_noise_mb=1200)
        d = t.to_dict()
        self.assertIn("vram_total_mb", d)
        self.assertIn("vram_total_gb", d)
        self.assertIn("base_noise_mb", d)
        self.assertIn("critical_mb", d)
        self.assertIn("danger_mb", d)
        self.assertIn("warning_mb", d)
        self.assertIn("free_target_mb", d)
        self.assertEqual(d["vram_total_gb"], 16.0)


class TestGetThresholds(unittest.TestCase):
    """测试 get_thresholds 加载逻辑"""

    def test_load_from_profile(self):
        """从 hardware_profile.json 加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = {
                "gpus": [{"index": 0, "name": "Test GPU", "vram_total_mb": 24576, "driver_version": "550"}],
                "primary_gpu_index": 0,
                "base_noise_mb": 1500,
                "base_noise_confidence": "high",
                "ram_total_mb": 32768,
                "os_type": "linux",
                "docker_available": True,
                "detected_at": 1234567890,
            }
            path = os.path.join(tmpdir, "hardware_profile.json")
            with open(path, "w") as f:
                json.dump(profile, f)

            thresholds.invalidate_cache()
            t = thresholds.get_thresholds(path)
            self.assertEqual(t.vram_total_mb, 24576)
            self.assertEqual(t.base_noise_mb, 1500)

    def test_fallback_default(self):
        """文件不存在时用默认值"""
        thresholds.invalidate_cache()
        t = thresholds.get_thresholds("/nonexistent/path.json")
        self.assertEqual(t.vram_total_mb, 16384)
        self.assertEqual(t.base_noise_mb, 1200)

    def test_cache(self):
        """缓存生效：第二次调用不重新读取"""
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = {"gpus": [{"index": 0, "vram_total_mb": 16384}],
                       "primary_gpu_index": 0, "base_noise_mb": 1200}
            path = os.path.join(tmpdir, "hp.json")
            with open(path, "w") as f:
                json.dump(profile, f)

            thresholds.invalidate_cache()
            t1 = thresholds.get_thresholds(path)
            t2 = thresholds.get_thresholds(path)
            self.assertIs(t1, t2)  # 同一实例


if __name__ == "__main__":
    unittest.main()
