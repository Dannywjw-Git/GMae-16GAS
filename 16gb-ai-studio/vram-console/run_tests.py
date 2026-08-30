# -*- coding: utf-8 -*-
"""GMae 调度中心测试运行入口（零依赖，Python 标准库 unittest）

用法：
    python run_tests.py              # 运行全部测试
    python run_tests.py test_auth    # 只运行认证模块测试
    python run_tests.py -v           # 详细输出
"""

import os
import sys
import unittest

# 确保 vram-console 目录在 path 中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

TEST_MODULES = [
    "tests.test_registry",
    "tests.test_auth",
    "tests.test_api_contract",
    "tests.test_budget",
    "tests.test_security",
]

# 自动发现 tests 目录下所有 test_*.py（避免遗漏新增模块）
def _discover_test_modules():
    """自动扫描 tests/ 目录下所有 test_*.py，返回模块名列表。"""
    import glob
    test_dir = os.path.join(BASE_DIR, "tests")
    pattern = os.path.join(test_dir, "test_*.py")
    modules = []
    for f in sorted(glob.glob(pattern)):
        name = os.path.splitext(os.path.basename(f))[0]
        modules.append("tests." + name)
    return modules

# 优先使用自动发现（保证不遗漏），回退到手动列表
try:
    TEST_MODULES = _discover_test_modules()
except Exception:
    pass


def run_all(verbosity=2):
    """运行全部测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for module in TEST_MODULES:
        try:
            suite.addTests(loader.loadTestsFromName(module))
            print(f"  ✅ 加载测试模块: {module}")
        except Exception as e:
            print(f"  ❌ 加载测试模块失败: {module} - {e}")

    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print(f"测试总数: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print("=" * 60)

    if result.failures:
        print("\n❌ 失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}")
    if result.errors:
        print("\n❌ 错误的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}")

    return result.wasSuccessful()


def run_single(module_name, verbosity=2):
    """运行单个测试模块"""
    full_name = "tests." + module_name if not module_name.startswith("tests.") else module_name
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(full_name)
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    print("=" * 60)
    print("GMae 调度中心 - 自动化测试")
    print("=" * 60)

    verbosity = 2
    target = None

    for arg in sys.argv[1:]:
        if arg == "-v" or arg == "--verbose":
            verbosity = 3
        elif arg == "-q" or arg == "--quiet":
            verbosity = 1
        elif not arg.startswith("-"):
            target = arg

    if target:
        print(f"\n运行单个测试模块: {target}\n")
        success = run_single(target, verbosity)
    else:
        print("\n加载测试模块...")
        success = run_all(verbosity)

    sys.exit(0 if success else 1)
