#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae-16GAS 故障注入脚本（仅用于演示和测试）

【安全警告】
- 本脚本仅用于演示和测试环境，禁止在生产环境使用
- 执行前会检查显存状态，空闲 <4GB 时拒绝高显存压力注入
- 支持 --dry-run 模式，只模拟不真实执行
- 支持 --confirm 跳过确认提示（用于自动化演示）

【用法】
python scripts/fault_inject.py --scene <场景名> [--dry-run] [--confirm]

【支持场景】
- vram_exhaustion: 显存耗尽（加载大模型）
- container_crash: 容器崩溃（停止关键容器）
- model_load_fail: 模型加载失败（加载不存在的模型）
- high_vram_pressure: 高显存压力（并行加载多个模型）
- all: 依次执行所有场景（用于完整演示）
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 颜色输出
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(title):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}\n")

def print_step(step, message):
    print(f"{Colors.BLUE}[{step}]{Colors.RESET} {message}")

def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.RESET}")

def print_warning(message):
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.RESET}")

def print_error(message):
    print(f"{Colors.RED}❌ {message}{Colors.RESET}")

def print_info(message):
    print(f"{Colors.MAGENTA}ℹ️  {message}{Colors.RESET}")

def get_vram_status():
    """获取当前显存状态"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            used = float(parts[0])
            total = float(parts[1])
            free = float(parts[2])
            return {
                "used_mb": used,
                "total_mb": total,
                "free_mb": free,
                "usage_percent": round(used / total * 100, 1)
            }
    except Exception as e:
        print_error(f"获取显存状态失败: {e}")
    return None

def check_safety(scene, dry_run=False):
    """安全检查：执行前验证环境状态"""
    print_step("安全检查", f"验证环境状态...")

    vram = get_vram_status()
    if not vram:
        print_error("无法获取显存状态，终止执行")
        return False

    print_info(f"当前显存: {vram['used_mb']:.0f}MB / {vram['total_mb']:.0f}MB "
               f"(使用率 {vram['usage_percent']}%, 空闲 {vram['free_mb']:.0f}MB)")

    # 高显存压力场景需要更多空闲显存
    if scene in ["vram_exhaustion", "high_vram_pressure", "all"]:
        if vram['free_mb'] < 4096 and not dry_run:
            print_error(f"空闲显存不足 ({vram['free_mb']:.0f}MB < 4096MB)，"
                        f"拒绝高显存压力注入")
            print_info("请先释放显存，或使用 --dry-run 模式")
            return False
        if vram['usage_percent'] > 70 and not dry_run:
            print_warning(f"显存使用率较高 ({vram['usage_percent']}%)，"
                         f"注入可能导致系统不稳定")

    print_success("安全检查通过")
    return True

def inject_vram_exhaustion(dry_run=False):
    """场景1：显存耗尽（加载大模型）"""
    print_header("场景1：显存耗尽（加载大模型）")

    print_step("1/3", "加载 Ollama 大模型 qwen3.5:9b...")
    if dry_run:
        print_info("[DRY-RUN] 模拟执行: ollama run qwen3.5:9b")
        time.sleep(1)
    else:
        try:
            # 后台运行 ollama run，触发模型加载
            proc = subprocess.Popen(
                ["ollama", "run", "qwen3.5:9b", "你好"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True
            )
            print_info("Ollama 模型加载中，等待显存上升...")
            time.sleep(5)  # 等待模型加载
            print_success("模型加载指令已发送")
        except Exception as e:
            print_error(f"Ollama 模型加载失败: {e}")

    print_step("2/3", "等待显存使用率上升...")
    for i in range(5):
        vram = get_vram_status()
        if vram:
            print_info(f"  第{i+1}次检测: 使用率 {vram['usage_percent']}%")
            if vram['usage_percent'] > 80:
                print_success("显存使用率已超过 80%，故障注入成功")
                break
        time.sleep(2)

    print_step("3/3", "触发 GMae 告警...")
    print_info("GMae 应在 5 秒内检测到显存异常并触发告警")
    print_info("请在浏览器中查看 Dashboard 页面的告警横幅")

    print_success("显存耗尽场景注入完成")
    return True

def inject_container_crash(dry_run=False):
    """场景2：容器崩溃（停止关键容器）"""
    print_header("场景2：容器崩溃（停止关键容器）")

    print_step("1/3", "停止 ComfyUI 容器...")
    if dry_run:
        print_info("[DRY-RUN] 模拟执行: docker stop comfyui")
    else:
        try:
            result = subprocess.run(
                ["docker", "stop", "comfyui"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                print_success("ComfyUI 容器已停止")
            else:
                print_error(f"停止容器失败: {result.stderr}")
        except Exception as e:
            print_error(f"停止容器异常: {e}")

    print_step("2/3", "等待 GMae 检测容器状态变化...")
    time.sleep(5)
    print_info("GMae 应通过 Docker Events 检测到容器停止")

    print_step("3/3", "触发告警...")
    print_info("GMae 应触发'关键容器停止'告警，并在诊断中心显示根因")

    print_success("容器崩溃场景注入完成")
    return True

def inject_model_load_fail(dry_run=False):
    """场景3：模型加载失败（加载不存在的模型）"""
    print_header("场景3：模型加载失败（加载不存在的模型）")

    print_step("1/3", "尝试加载不存在的模型...")
    if dry_run:
        print_info("[DRY-RUN] 模拟执行: ollama run nonexistent-model:99b")
    else:
        try:
            result = subprocess.run(
                ["ollama", "run", "nonexistent-model:99b", "test"],
                capture_output=True, text=True, timeout=30
            )
            print_info(f"Ollama 返回: {result.stderr or result.stdout}")
        except Exception as e:
            print_info(f"预期失败: {e}")

    print_step("2/3", "记录失败事件...")
    print_info("GMae 应记录模型加载失败事件，并在事件时间线中显示")

    print_step("3/3", "触发诊断...")
    print_info("GMae 诊断中心应能关联到模型加载失败事件")

    print_success("模型加载失败场景注入完成")
    return True

def inject_high_vram_pressure(dry_run=False):
    """场景4：高显存压力（并行加载多个模型）"""
    print_header("场景4：高显存压力（并行加载多个模型）")

    print_step("1/4", "加载第一个模型...")
    if dry_run:
        print_info("[DRY-RUN] 模拟加载 qwen3.5:9b")
    else:
        subprocess.Popen(["ollama", "run", "qwen3.5:9b", "hi"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(3)

    print_step("2/4", "加载第二个模型...")
    if dry_run:
        print_info("[DRY-RUN] 模拟加载另一个模型")
    else:
        # 尝试加载另一个模型（如果有）
        subprocess.Popen(["ollama", "run", "qwen3.5:9b", "hi again"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(3)

    print_step("3/4", "检测显存状态...")
    vram = get_vram_status()
    if vram:
        print_info(f"当前显存使用率: {vram['usage_percent']}%")

    print_step("4/4", "触发 GMae 高显存压力告警...")
    print_info("GMae 应检测到高显存压力，并建议释放或切换场景")

    print_success("高显存压力场景注入完成")
    return True

def cleanup(scene, dry_run=False):
    """清理：恢复环境状态"""
    print_header("环境清理")

    print_step("清理", "恢复环境状态...")

    if scene in ["container_crash", "all"] and not dry_run:
        print_info("重启 ComfyUI 容器...")
        try:
            subprocess.run(["docker", "start", "comfyui"],
                          capture_output=True, timeout=30)
            print_success("ComfyUI 容器已重启")
        except Exception as e:
            print_warning(f"重启容器失败: {e}")

    if scene in ["vram_exhaustion", "high_vram_pressure", "all"] and not dry_run:
        print_info("释放 Ollama 模型显存...")
        try:
            subprocess.run(["ollama", "stop", "qwen3.5:9b"],
                          capture_output=True, timeout=30)
            print_success("Ollama 模型已停止")
        except Exception as e:
            print_warning(f"停止模型失败: {e}")

    time.sleep(3)
    vram = get_vram_status()
    if vram:
        print_info(f"清理后显存: 使用率 {vram['usage_percent']}%, "
                  f"空闲 {vram['free_mb']:.0f}MB")

    print_success("环境清理完成")

def main():
    parser = argparse.ArgumentParser(
        description="GMae-16GAS 故障注入脚本（仅用于演示和测试）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/fault_inject.py --scene vram_exhaustion
  python scripts/fault_inject.py --scene all --dry-run
  python scripts/fault_inject.py --scene container_crash --confirm
        """
    )
    parser.add_argument("--scene", type=str, required=True,
                       choices=["vram_exhaustion", "container_crash",
                               "model_load_fail", "high_vram_pressure", "all"],
                       help="故障场景名称")
    parser.add_argument("--dry-run", action="store_true",
                       help="只模拟不真实执行")
    parser.add_argument("--confirm", action="store_true",
                       help="跳过确认提示")
    parser.add_argument("--no-cleanup", action="store_true",
                       help="执行后不自动清理环境")

    args = parser.parse_args()

    # 打印标题
    print_header("GMae-16GAS 故障注入脚本")
    print_info(f"场景: {args.scene}")
    print_info(f"模式: {'DRY-RUN (模拟)' if args.dry_run else '真实执行'}")
    print_info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if args.dry_run:
        print_warning("DRY-RUN 模式：不会真实执行任何操作")

    # 安全检查
    if not check_safety(args.scene, args.dry_run):
        print_error("安全检查未通过，终止执行")
        sys.exit(1)

    # 确认提示
    if not args.confirm and not args.dry_run:
        print_warning("\n即将执行故障注入，这可能影响系统稳定性！")
        confirm = input("确认执行？(yes/no): ").strip().lower()
        if confirm not in ["yes", "y"]:
            print_info("已取消执行")
            sys.exit(0)

    # 执行场景
    scenes_map = {
        "vram_exhaustion": inject_vram_exhaustion,
        "container_crash": inject_container_crash,
        "model_load_fail": inject_model_load_fail,
        "high_vram_pressure": inject_high_vram_pressure,
    }

    if args.scene == "all":
        for name, func in scenes_map.items():
            func(args.dry_run)
            time.sleep(2)
    else:
        scenes_map[args.scene](args.dry_run)

    # 清理
    if not args.no_cleanup:
        cleanup(args.scene, args.dry_run)

    print_header("执行完成")
    print_success("故障注入脚本执行完成")
    print_info("请在浏览器中查看 GMae Dashboard 和诊断中心的效果")

if __name__ == "__main__":
    main()
