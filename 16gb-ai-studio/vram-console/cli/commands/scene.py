#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene 命令组：场景切换与组合"""
from ..formatter import print_json, print_table, _c, check_ok, print_ok


def register(subparsers):
    p = subparsers.add_parser("scene", help="场景管理（列表/切换/组合）")
    sub = p.add_subparsers(dest="subcmd")

    # list
    pl = sub.add_parser("list", help="列出所有可用场景")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=run_list)

    # switch
    ps = sub.add_parser("switch", help="切换到指定场景")
    ps.add_argument("name", help="场景名称（如 idle / comfyui / ollama / fooocus）")
    ps.add_argument("--json", action="store_true")
    ps.add_argument("--quiet", action="store_true")
    ps.set_defaults(func=run_switch)

    # combo
    pc = sub.add_parser("combo", help="切换对话组合（模型大小）")
    pc.add_argument("name", help="组合名称（如 9b / 0.6b / 7b）")
    pc.add_argument("--json", action="store_true")
    pc.add_argument("--quiet", action="store_true")
    pc.set_defaults(func=run_combo)

    p.set_defaults(func=lambda a, c, cfg: p.print_help())


def run_list(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.registry()
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    scenes_raw = result.get("scenes", {})
    # scenes 可能是字典（键=场景名）或列表，统一转为列表
    if isinstance(scenes_raw, dict):
        scenes = [{"name": k, **v} for k, v in scenes_raw.items()]
    else:
        scenes = scenes_raw or []
    print(_c("\n=== 可用场景 ===", "cyan", use_color))
    if not scenes:
        print(_c("  （注册表中无场景定义）", "gray", use_color))
    else:
        rows = []
        for s in scenes:
            name = s.get("name", s.get("id", "?"))
            desc = s.get("label", s.get("description", s.get("desc", "")))
            exclusive = "是" if s.get("exclusive") else "否"
            containers = s.get("containers", s.get("services", []))
            services_str = ", ".join(containers) if isinstance(containers, list) else str(containers)
            vram_budget = s.get("vram_budget_gb", "")
            rows.append([name, desc, exclusive, services_str, f"{vram_budget}G" if vram_budget else ""])
        print_table(["场景", "名称", "独占", "关联容器", "显存预算"], rows, use_color)
    print()


def run_switch(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.scene_switch(args.name)
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok(f"已切换到场景: {args.name}", use_color)
        if result.get("message"):
            print(f"  {result['message']}")
        if result.get("actions"):
            for a in result["actions"]:
                print(f"  - {a}")


def run_combo(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.combo_switch(args.name)
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok(f"已切换组合: {args.name}", use_color)
        if result.get("message"):
            print(f"  {result['message']}")
