#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logs 命令组：日志查看"""
from ..formatter import print_json, _c, check_ok


def register(subparsers):
    p = subparsers.add_parser("logs", help="查看系统日志")
    p.add_argument("-n", "--lines", type=int, default=50, help="显示最后 N 行（默认 50）")
    p.add_argument("--level", help="按级别筛选（info / warn / error / critical）")
    p.add_argument("--event", help="按事件名筛选")
    p.add_argument("--json", action="store_true", help="输出原始 JSON")
    p.add_argument("--follow", action="store_true", help="持续跟踪（暂未实现）")
    p.set_defaults(func=run)


def run(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.logs(limit=args.lines * 2)  # 多取一些供筛选
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return

    entries = result.get("logs", result.get("entries", []))
    if args.level:
        entries = [e for e in entries if e.get("level", "").lower() == args.level.lower()]
    if args.event:
        entries = [e for e in entries if args.event.lower() in e.get("event", "").lower()]

    entries = entries[-args.lines:]

    print(_c(f"\n=== 系统日志 (最后 {len(entries)} 条) ===", "cyan", use_color))
    if not entries:
        print(_c("  （无日志）", "gray", use_color))
    else:
        level_colors = {"info": "gray", "warn": "yellow", "warning": "yellow",
                         "error": "red", "critical": "red", "debug": "cyan"}
        for e in entries:
            ts = e.get("timestamp", e.get("time", ""))
            level = e.get("level", "info").lower()
            event = e.get("event", "")
            msg = e.get("message", e.get("msg", ""))
            # 提取关键字段
            details = []
            for k, v in e.items():
                if k not in ("timestamp", "time", "level", "event", "message", "msg") and v:
                    details.append(f"{k}={v}")
            detail_str = " ".join(details)

            level_str = _c(level.upper().ljust(8), level_colors.get(level, "white"), use_color)
            event_str = _c(event, "bold", use_color) if event else ""
            line = f"  {ts} {level_str} {event_str} {msg}"
            if detail_str:
                line += _c(f"  ({detail_str})", "gray", use_color)
            print(line)
    print()
