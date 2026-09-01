#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae CLI 主入口
用法：gmae <命令组> <子命令> [参数]
"""
import sys
import argparse

from . import __version__
from .config import load_config
from .client import GMaeClient
from .commands import ALL_COMMANDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmae",
        description="GMae 显存指挥家 - 命令行工具（One GPU, Infinite Models）",
        epilog="示例:\n"
               "  gmae status                    系统状态总览\n"
               "  gmae vram free                 一键释放显存\n"
               "  gmae vram budget               预算引擎决策表\n"
               "  gmae scene list                列出可用场景\n"
               "  gmae scene switch comfyui      切换到 ComfyUI 场景\n"
               "  gmae model list                列出所有模型\n"
               "  gmae queue submit sdxl --prompt \"a cat\"  提交生成任务\n"
               "  gmae logs -n 20 --level error  查看最近 20 条错误日志\n"
               "  gmae auth login --token XXX    配置 API Token\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--version", action="version", version=f"gmae-cli {__version__}")
    parser.add_argument("--server", help="覆盖服务器地址（如 http://127.0.0.1:8787）")
    parser.add_argument("--token", help="覆盖 API Token")
    parser.add_argument("--timeout", type=int, help="覆盖请求超时（秒）")
    parser.add_argument("--no-color", action="store_true", help="禁用彩色输出")

    subparsers = parser.add_subparsers(dest="command", metavar="<命令>")
    for cmd_module in ALL_COMMANDS:
        cmd_module.register(subparsers)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    # 加载配置并应用全局覆盖
    cfg = load_config()
    if args.server:
        cfg["server"] = args.server
    if args.token:
        cfg["token"] = args.token
    if args.timeout:
        cfg["timeout"] = args.timeout
    if args.no_color:
        cfg["color"] = False

    client = GMaeClient(cfg)

    if hasattr(args, "func"):
        try:
            args.func(args, client, cfg)
            return 0
        except KeyboardInterrupt:
            print("\n已取消")
            return 130
        except Exception as e:
            print(f"执行出错: {e}", file=sys.stderr)
            return 1
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
