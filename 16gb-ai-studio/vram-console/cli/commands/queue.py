#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""queue 命令组：任务队列（提交/列表/取消）"""
import json as _json
from ..formatter import print_json, print_table, _c, check_ok, print_ok


def register(subparsers):
    p = subparsers.add_parser("queue", help="任务队列（提交/列表/取消）")
    sub = p.add_subparsers(dest="subcmd")

    # list
    pl = sub.add_parser("list", help="列出当前任务队列")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=run_list)

    # submit
    ps = sub.add_parser("submit", help="提交生成任务")
    ps.add_argument("model", help="模型名称（需有工作流模板）")
    ps.add_argument("--prompt", help="生成提示词")
    ps.add_argument("--params", help="额外参数 JSON 字符串")
    ps.add_argument("--json", action="store_true")
    ps.add_argument("--quiet", action="store_true")
    ps.set_defaults(func=run_submit)

    # cancel
    pc = sub.add_parser("cancel", help="取消任务")
    pc.add_argument("id", help="任务 ID")
    pc.add_argument("--json", action="store_true")
    pc.add_argument("--quiet", action="store_true")
    pc.set_defaults(func=run_cancel)

    p.set_defaults(func=lambda a, c, cfg: p.print_help())


def run_list(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.queue_list()
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    tasks = result.get("tasks", result.get("queue", []))
    print(_c(f"\n=== 任务队列 ({len(tasks)}) ===", "cyan", use_color))
    if not tasks:
        print(_c("  （队列为空）", "gray", use_color))
    else:
        rows = []
        for t in tasks:
            tid = t.get("id", t.get("task_id", "?"))
            model = t.get("model", "?")
            status = t.get("status", "?")
            progress = t.get("progress", "")
            color_map = {"pending": "yellow", "running": "cyan", "done": "green",
                         "failed": "red", "cancelled": "gray"}
            status_colored = _c(status, color_map.get(status, "white"), use_color)
            rows.append([str(tid), model, status_colored, str(progress)])
        print_table(["ID", "模型", "状态", "进度"], rows, use_color)
    print()


def run_submit(args, client, cfg):
    use_color = cfg.get("color", True)
    params = {}
    if args.prompt:
        params["prompt"] = args.prompt
    if args.params:
        try:
            params.update(_json.loads(args.params))
        except Exception:
            print("参数 JSON 解析失败，使用默认参数")
    result = client.queue_submit(args.model, params)
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        tid = result.get("id", result.get("task_id", "?"))
        print_ok(f"任务已提交: {args.name if hasattr(args, 'name') else args.model} (ID={tid})", use_color)
        if result.get("position") is not None:
            print(f"  队列位置: {result['position']}")


def run_cancel(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.queue_cancel(args.id)
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok(f"任务已取消: {args.id}", use_color)
