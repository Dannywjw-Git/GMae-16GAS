#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""guard 命令组：门卫（检查/驱逐/kick）"""
from ..formatter import print_json, print_table, _c, check_ok, print_ok, print_warn


def register(subparsers):
    p = subparsers.add_parser("guard", help="门卫管理（检查/驱逐/结束进程）")
    sub = p.add_subparsers(dest="subcmd")

    # check
    pc = sub.add_parser("check", help="检查未登记/异常进程")
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=run_check)

    # evict
    pe = sub.add_parser("evict", help="执行驱逐建议")
    pe.add_argument("--json", action="store_true")
    pe.add_argument("--quiet", action="store_true")
    pe.set_defaults(func=run_evict)

    # kick
    pk = sub.add_parser("kick", help="强制结束指定进程")
    pk.add_argument("pid", help="进程 PID")
    pk.add_argument("--json", action="store_true")
    pk.add_argument("--quiet", action="store_true")
    pk.set_defaults(func=run_kick)

    p.set_defaults(func=lambda a, c, cfg: p.print_help())


def run_check(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.guard_check()
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    print(_c("\n=== 门卫检查 ===", "cyan", use_color))

    # 受管进程
    managed = result.get("managed", result.get("processes", []))
    if managed:
        print(_c(f"\n  受管进程 ({len(managed)})", "green", use_color))
        rows = [[str(p.get("pid", "?")), p.get("name", p.get("comm", "?")),
                 f"{p.get('vram_mb', p.get('vram_gb', '?'))}"] for p in managed]
        print_table(["PID", "进程", "显存"], rows, use_color)

    # 未登记进程
    unknown = result.get("unknown_pids", result.get("unknown", []))
    if unknown:
        print(_c(f"\n  未登记进程 ({len(unknown)})", "yellow", use_color))
        for pid in unknown:
            print(f"  - PID {pid}")

    # 桌面进程
    desktop = result.get("desktop_processes", [])
    if desktop:
        print(_c(f"\n  桌面进程 ({len(desktop)})", "cyan", use_color))
        rows = [[str(p.get("pid", p.get("Pid", "?"))),
                 p.get("name", p.get("ProcessName", "?")),
                 f"{p.get('vram_mb', '?')} MB"] for p in desktop]
        print_table(["PID", "进程", "显存"], rows, use_color)

    # 建议
    suggestions = result.get("suggestions", result.get("evict_suggestions", []))
    if suggestions:
        print(_c("\n  驱逐建议", "yellow", use_color))
        for s in suggestions:
            print(f"  - {s}")
    print()


def run_evict(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.guard_evict()
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok("门卫驱逐已执行", use_color)
        evicted = result.get("evicted", [])
        if evicted:
            for e in evicted:
                print(f"  - 已驱逐: {e}")
        if result.get("message"):
            print(f"  {result['message']}")


def run_kick(args, client, cfg):
    use_color = cfg.get("color", True)
    print_warn(f"即将强制结束进程 PID={args.pid}，此操作不可撤销", use_color)
    result = client.guard_kick(args.pid)
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok(f"进程已结束: PID={args.pid}", use_color)
