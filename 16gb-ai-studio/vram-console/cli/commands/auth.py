#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auth 命令组：认证（登录/登出/改密/whoami）"""
import getpass
from ..config import load_config, save_config
from ..formatter import print_json, _c, check_ok, print_ok, print_error


def register(subparsers):
    p = subparsers.add_parser("auth", help="认证管理（登录/登出/改密/当前用户）")
    sub = p.add_subparsers(dest="subcmd")

    # status
    ps = sub.add_parser("status", help="查看认证状态")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=run_status)

    # login
    pl = sub.add_parser("login", help="登录并保存 Token（或使用 API Token）")
    pl.add_argument("--email", help="邮箱（不填则交互输入）")
    pl.add_argument("--password", help="密码（不填则交互输入，不推荐明文）")
    pl.add_argument("--token", help="直接使用 API Token（推荐，无需账号密码）")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=run_login)

    # logout
    po = sub.add_parser("logout", help="清除本地保存的 Token")
    po.set_defaults(func=run_logout)

    # whoami
    pw = sub.add_parser("whoami", help="查看当前认证身份")
    pw.add_argument("--json", action="store_true")
    pw.set_defaults(func=run_whoami)

    p.set_defaults(func=lambda a, c, cfg: p.print_help())


def run_status(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.auth_status()
    if args.json:
        print_json(result)
        return
    print(_c("\n=== 认证状态 ===", "cyan", use_color))
    has_admin = result.get("has_admin", False)
    smtp = result.get("smtp_configured", False)
    print(f"  管理员已设置: {'是' if has_admin else '否（需首次设置）'}")
    print(f"  SMTP 已配置: {'是' if smtp else '否'}")
    if cfg.get("token"):
        print(f"  本地 Token: {_c('已配置', 'green', use_color)}")
    else:
        print(f"  本地 Token: {_c('未配置（使用 gmae auth login --token <token>）', 'yellow', use_color)}")
    print()


def run_login(args, client, cfg):
    use_color = cfg.get("color", True)
    new_cfg = load_config()

    if args.token:
        new_cfg["token"] = args.token
        save_config(new_cfg)
        print_ok("API Token 已保存", use_color)
        # 验证 token
        test_client = type(client)(new_cfg)
        result = test_client.status()
        if result.get("ok"):
            print_ok("Token 验证成功", use_color)
        else:
            print_error(f"Token 验证失败: {result.get('error', '未知错误')}", use_color)
        return

    email = args.email or input("邮箱: ").strip()
    password = args.password or getpass.getpass("密码: ")
    result = client.login(email, password, remember=True)
    if args.json:
        print_json(result)
        return
    if check_ok(result, use_color=use_color):
        print_ok(f"登录成功: {email}", use_color)
        print(_c("  注意：Session Cookie 模式不保存到 CLI 配置。", "yellow", use_color))
        print(_c("  推荐使用 API Token: gmae auth login --token <your-token>", "cyan", use_color))


def run_logout(args, client, cfg):
    use_color = cfg.get("color", True)
    new_cfg = load_config()
    if new_cfg.get("token"):
        new_cfg["token"] = ""
        save_config(new_cfg)
        print_ok("本地 Token 已清除", use_color)
    else:
        print("本地无保存的 Token")


def run_whoami(args, client, cfg):
    use_color = cfg.get("color", True)
    if not cfg.get("token"):
        print(_c("未配置 Token，请先运行 gmae auth login --token <token>", "yellow", use_color))
        return
    result = client.status()
    if args.json:
        print_json(result)
        return
    if check_ok(result, use_color=use_color):
        print(_c("\n=== 当前身份 ===", "cyan", use_color))
        print(f"  认证方式: API Token")
        print(f"  服务器: {cfg['server']}")
        print(f"  连接状态: {_c('正常', 'green', use_color)}")
        gpu = result.get("gpu", {})
        print(f"  GPU: {gpu.get('name', gpu.get('model', '未知'))}")
        print()
