#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vram 命令组：显存管理（释放/预算/建议/桌面显存）"""
from ..formatter import print_json, print_kv, print_table, format_vram_bar, _c, check_ok, print_ok, print_warn


def register(subparsers):
    p = subparsers.add_parser("vram", help="显存管理（释放/预算/建议/桌面显存）")
    sub = p.add_subparsers(dest="subcmd")

    # free
    pf = sub.add_parser("free", help="一键释放全部显存")
    pf.add_argument("--json", action="store_true")
    pf.add_argument("--quiet", action="store_true")
    pf.set_defaults(func=run_free)

    # budget
    pb = sub.add_parser("budget", help="预算引擎：查看各模型能否运行")
    pb.add_argument("--context", help="上下文覆盖，格式 model:ctx,model:ctx（如 qwen3.5:9b:32768）")
    pb.add_argument("--json", action="store_true")
    pb.add_argument("--quiet", action="store_true")
    pb.set_defaults(func=run_budget)

    # advice
    pa = sub.add_parser("advice", help="智能显存建议")
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=run_advice)

    # desktop
    pd = sub.add_parser("desktop", help="桌面进程显存占用")
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=run_desktop)

    p.set_defaults(func=lambda a, c, cfg: p.print_help())


def run_free(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.free()
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        freed = result.get("freed_gb", result.get("freed", "?"))
        print_ok(f"显存已释放，释放约 {freed} GB", use_color)
        if result.get("details"):
            for d in result["details"]:
                print(f"  - {d}")


def run_budget(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.budget(context_overrides=args.context)
    if args.json:
        print_json(result)
        return
    if not check_ok(result, quiet=args.quiet, use_color=use_color):
        return

    total = result.get("total_gb", 16)
    used = result.get("used_gb", 0)
    free = result.get("free_gb", total - used)
    safe_limit = result.get("safe_limit_gb", total - 4)

    print(_c("\n=== 显存预算 ===", "cyan", use_color))
    print("  " + format_vram_bar(used, total, use_color=use_color))
    print(f"  安全上限: {safe_limit:.1f} GB  |  已用: {used:.1f} GB  |  可用: {free:.1f} GB")

    decisions = result.get("decisions", [])
    if decisions:
        print(_c("\n=== 模型决策表 ===", "cyan", use_color))
        rows = []
        for d in decisions:
            name = d.get("model", d.get("name", "?"))
            vram = d.get("vram_gb", "?")
            status = d.get("status", "?")
            action = d.get("action", d.get("need_free", ""))
            icon_map = {"runnable": _c("✅可跑", "green", use_color),
                        "need_free": _c("⏳需释放", "yellow", use_color),
                        "not_enough": _c("⛔不足", "red", use_color)}
            icon = icon_map.get(status, status)
            rows.append([name, f"{vram}G", icon, str(action)])
        print_table(["模型", "显存", "状态", "操作/需释放"], rows, use_color)
    print()


def run_advice(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.advice()
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    print(_c("\n=== 智能显存建议 ===", "cyan", use_color))
    suggestions = result.get("suggestions", [])
    if not suggestions:
        print(_c("  当前无建议，显存状态良好", "green", use_color))
    for i, s in enumerate(suggestions, 1):
        title = s.get("title", s.get("type", f"建议 {i}"))
        desc = s.get("description", s.get("detail", ""))
        priority = s.get("priority", "info")
        color = {"high": "red", "medium": "yellow", "low": "cyan", "info": "gray"}.get(priority, "gray")
        print(f"\n  {_c(f'[{i}] {title}', color, use_color)}")
        if desc:
            print(f"      {desc}")
    print()


def run_desktop(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.desktop_vram()
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    procs = result.get("processes", result.get("desktop_processes", []))
    print(_c("\n=== 桌面进程显存 ===", "cyan", use_color))
    if not procs:
        print(_c("  （无桌面 GPU 进程，或 Helper 未运行）", "gray", use_color))
    else:
        rows = []
        for p in procs:
            pid = p.get("pid", p.get("Pid", "?"))
            name = p.get("name", p.get("ProcessName", "?"))
            vram = p.get("vram_mb", p.get("dedicated_mb", "?"))
            rows.append([str(pid), name, f"{vram} MB"])
        rows.sort(key=lambda r: int(r[2].split()[0]) if r[2].isdigit() else 0, reverse=True)
        print_table(["PID", "进程名", "显存"], rows, use_color)
    print()
