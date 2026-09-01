#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""service 命令组：服务控制（启动/停止/状态/Helper）"""
from ..formatter import print_json, print_table, _c, check_ok, print_ok


def register(subparsers):
    p = subparsers.add_parser("service", help="服务控制（启动/停止/状态/Helper/容器）")
    sub = p.add_subparsers(dest="subcmd")

    # status
    ps = sub.add_parser("status", help="查看所有服务状态")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=run_status)

    # start
    pst = sub.add_parser("start", help="启动服务")
    pst.add_argument("name", help="服务名称（comfyui / ollama / fooocus / owui）")
    pst.add_argument("--json", action="store_true")
    pst.add_argument("--quiet", action="store_true")
    pst.set_defaults(func=run_start)

    # stop
    psp = sub.add_parser("stop", help="停止服务")
    psp.add_argument("name", help="服务名称")
    psp.add_argument("--json", action="store_true")
    psp.add_argument("--quiet", action="store_true")
    psp.set_defaults(func=run_stop)

    # helper
    ph = sub.add_parser("helper", help="桌面 Helper 管理")
    ph.add_argument("action", choices=["status", "start", "stop"], help="操作")
    ph.add_argument("--json", action="store_true")
    ph.set_defaults(func=run_helper)

    # container
    pc = sub.add_parser("container", help="容器控制")
    pc.add_argument("action", choices=["stop"], help="操作")
    pc.add_argument("name", help="容器名称")
    pc.add_argument("--json", action="store_true")
    pc.add_argument("--quiet", action="store_true")
    pc.set_defaults(func=run_container)

    p.set_defaults(func=lambda a, c, cfg: p.print_help())


def run_status(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.status()
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    print(_c("\n=== 服务状态 ===", "cyan", use_color))
    services = [
        ("ComfyUI", result.get("comfyui", {}).get("running", False), "8188"),
        ("Ollama", result.get("ollama", {}).get("running", False), "11434"),
        ("Open WebUI", result.get("owui", {}).get("running", False), "3000"),
        ("Fooocus", result.get("fooocus", {}).get("running", False), "-"),
    ]
    rows = []
    for name, running, port in services:
        status = _c("● 运行中", "green", use_color) if running else _c("○ 已停止", "gray", use_color)
        rows.append([name, status, port])
    print_table(["服务", "状态", "端口"], rows, use_color)

    # Helper
    helper = result.get("helper", {})
    if helper:
        hrunning = helper.get("running", False)
        hstatus = _c("● 运行中", "green", use_color) if hrunning else _c("○ 未运行", "gray", use_color)
        print(f"\n  桌面 Helper: {hstatus}")
    print()


def run_start(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.service_action(args.name, "start")
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok(f"服务启动指令已发送: {args.name}", use_color)
        if result.get("message"):
            print(f"  {result['message']}")


def run_stop(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.service_action(args.name, "stop")
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok(f"服务停止指令已发送: {args.name}", use_color)


def run_helper(args, client, cfg):
    use_color = cfg.get("color", True)
    if args.action == "status":
        result = client.helper_status()
    elif args.action == "start":
        result = client.helper_start()
    else:
        result = client.helper_stop()
    if args.json:
        print_json(result)
        return
    if check_ok(result, use_color=use_color):
        if args.action == "status":
            running = result.get("running", False)
            status = _c("运行中", "green", use_color) if running else _c("未运行", "gray", use_color)
            print(f"\n  桌面 Helper: {status}")
            if result.get("port"):
                print(f"  端口: {result['port']}")
        else:
            print_ok(f"Helper {args.action} 指令已发送", use_color)
        if result.get("message"):
            print(f"  {result['message']}")
        print()


def run_container(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.container_stop(args.name)
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok(f"容器已停止: {args.name}", use_color)
