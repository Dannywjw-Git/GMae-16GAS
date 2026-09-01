#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config 命令组：CLI 配置 + 服务端配置（auto-protect/QoS）"""
from ..config import load_config, save_config, CONFIG_FILE
from ..formatter import print_json, print_kv, _c, check_ok, print_ok


def register(subparsers):
    p = subparsers.add_parser("config", help="配置管理（CLI 配置 / 自动保护 / QoS）")
    sub = p.add_subparsers(dest="subcmd")

    # show
    ps = sub.add_parser("show", help="显示当前 CLI 配置")
    ps.set_defaults(func=run_show)

    # set
    pset = sub.add_parser("set", help="设置 CLI 配置项")
    pset.add_argument("key", help="配置键（server / token / timeout / output / color）")
    pset.add_argument("value", help="配置值")
    pset.set_defaults(func=run_set)

    # autoprotect status
    pas = sub.add_parser("autoprotect", help="自动防死机配置")
    pas.add_argument("action", choices=["status", "enable", "disable"], help="操作")
    pas.add_argument("--mode", choices=["conservative", "standard", "aggressive"], help="保护模式")
    pas.add_argument("--level", choices=["warning", "danger", "critical"], help="触发等级")
    pas.add_argument("--json", action="store_true")
    pas.set_defaults(func=run_autoprotect)

    # qos
    pq = sub.add_parser("qos", help="QoS 水位管理")
    pq.add_argument("action", choices=["status", "check", "execute"], help="操作")
    pq.add_argument("--id", help="建议 ID（execute 时使用）")
    pq.add_argument("--json", action="store_true")
    pq.set_defaults(func=run_qos)

    p.set_defaults(func=lambda a, c, cfg: p.print_help())


def run_show(args, client, cfg):
    use_color = cfg.get("color", True)
    print(_c(f"\n=== CLI 配置 ({CONFIG_FILE}) ===", "cyan", use_color))
    display = cfg.copy()
    if display.get("token"):
        display["token"] = display["token"][:4] + "***" + display["token"][-2:]
    print_kv(display, use_color=use_color)
    print()


def run_set(args, client, cfg):
    use_color = cfg.get("color", True)
    valid_keys = {"server", "token", "timeout", "output", "color"}
    if args.key not in valid_keys:
        print(f"无效配置键: {args.key}")
        print(f"可用键: {', '.join(sorted(valid_keys))}")
        return
    new_cfg = load_config()
    value = args.value
    if args.key == "timeout":
        value = int(value)
    if args.key == "color":
        value = value.lower() in ("true", "1", "yes", "on")
    if args.key == "output" and value not in ("table", "json", "quiet"):
        print(f"output 有效值: table / json / quiet")
        return
    new_cfg[args.key] = value
    save_config(new_cfg)
    print_ok(f"配置已更新: {args.key} = {value}", use_color)


def run_autoprotect(args, client, cfg):
    use_color = cfg.get("color", True)
    if args.action == "status":
        result = client.auto_protect_status()
    else:
        enabled = args.action == "enable"
        body = {"enabled": enabled}
        if args.mode:
            body["mode"] = args.mode
        if args.level:
            body["trigger_level"] = args.level
        result = client.auto_protect_config(body)
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    print(_c("\n=== 自动防死机 ===", "cyan", use_color))
    enabled = result.get("enabled", False)
    status = _c("已启用", "green", use_color) if enabled else _c("已禁用", "gray", use_color)
    print(f"  状态: {status}")
    if result.get("mode"):
        print(f"  模式: {result['mode']}")
    if result.get("trigger_level"):
        print(f"  触发等级: {result['trigger_level']}")
    if result.get("rules"):
        print(f"\n  规则:")
        for r in result["rules"]:
            print(f"    - {r}")
    print()


def run_qos(args, client, cfg):
    use_color = cfg.get("color", True)
    if args.action == "status":
        result = client.qos_status()
    elif args.action == "check":
        result = client.qos_check()
    else:
        if not args.id:
            print("execute 需要 --id 参数")
            return
        result = client.qos_execute(args.id)
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    print(_c("\n=== QoS 状态 ===", "cyan", use_color))
    print_kv(result, use_color=use_color)
    print()
