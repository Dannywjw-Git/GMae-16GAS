#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""model 命令组：模型管理（列表/加载/卸载/扫描/登记）"""
from ..formatter import print_json, print_table, _c, check_ok, print_ok


def register(subparsers):
    p = subparsers.add_parser("model", help="模型管理（列表/加载/卸载/扫描/登记）")
    sub = p.add_subparsers(dest="subcmd")

    # list
    pl = sub.add_parser("list", help="列出所有已登记模型")
    pl.add_argument("--category", help="按类别筛选（llm / image / video / audio / embedding / reranker）")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=run_list)

    # load
    pld = sub.add_parser("load", help="加载指定模型")
    pld.add_argument("name", help="模型名称")
    pld.add_argument("--json", action="store_true")
    pld.add_argument("--quiet", action="store_true")
    pld.set_defaults(func=run_load)

    # unload
    pu = sub.add_parser("unload", help="卸载指定模型")
    pu.add_argument("name", help="模型名称")
    pu.add_argument("--json", action="store_true")
    pu.add_argument("--quiet", action="store_true")
    pu.set_defaults(func=run_unload)

    # scan
    ps = sub.add_parser("scan", help="扫描新模型")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=run_scan)

    # register
    pr = sub.add_parser("register", help="手动登记模型")
    pr.add_argument("name", help="模型名称")
    pr.add_argument("--source", default="comfyui", help="来源（comfyui / ollama / manual）")
    pr.add_argument("--vram", type=float, default=0, help="显存占用 GB")
    pr.add_argument("--category", default="image", help="类别（image / llm / video / audio）")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=run_register)

    p.set_defaults(func=lambda a, c, cfg: p.print_help())


def run_list(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.registry()
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    # 模型分两组：ollama_models（列表）和 comfyui_models（字典含 models 列表）
    models = []
    ollama_models = result.get("ollama_models", [])
    if isinstance(ollama_models, list):
        for m in ollama_models:
            if isinstance(m, dict):
                m.setdefault("category", "llm")
                models.append(m)
    comfyui_models = result.get("comfyui_models", {})
    if isinstance(comfyui_models, dict):
        comfyui_list = comfyui_models.get("models", [])
        if isinstance(comfyui_list, list):
            for m in comfyui_list:
                if isinstance(m, dict):
                    m.setdefault("category", "image")
                    models.append(m)
    elif isinstance(comfyui_models, list):
        models.extend(comfyui_models)
    if args.category:
        models = [m for m in models if m.get("category") == args.category]

    print(_c(f"\n=== 已登记模型 ({len(models)}) ===", "cyan", use_color))
    if not models:
        print(_c("  （无模型）", "gray", use_color))
    else:
        rows = []
        for m in models:
            name = m.get("name", m.get("id", "?"))
            cat = m.get("category", "?")
            vram = m.get("vram_gb", m.get("vram", "?"))
            verified = "✓" if m.get("vram_verified") else " "
            enabled = _c("启用", "green", use_color) if m.get("enabled", True) else _c("禁用", "gray", use_color)
            rows.append([name, cat, f"{vram}G", verified, enabled])
        print_table(["模型", "类别", "显存", "校准", "状态"], rows, use_color)
    print()


def run_load(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.model_action(args.name, "load")
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok(f"模型加载指令已发送: {args.name}", use_color)
        if result.get("message"):
            print(f"  {result['message']}")


def run_unload(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.model_action(args.name, "unload")
    if args.json:
        print_json(result)
        return
    if check_ok(result, quiet=args.quiet, use_color=use_color):
        print_ok(f"模型卸载指令已发送: {args.name}", use_color)


def run_scan(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.model_scan()
    if args.json:
        print_json(result)
        return
    if not check_ok(result, use_color=use_color):
        return
    found = result.get("found", result.get("new_models", []))
    print(_c("\n=== 模型扫描结果 ===", "cyan", use_color))
    if isinstance(found, list) and found:
        for m in found:
            name = m.get("name", m) if isinstance(m, dict) else str(m)
            print(f"  - {name}")
    else:
        print(_c("  未发现新模型", "gray", use_color))
    if result.get("message"):
        print(f"  {result['message']}")
    print()


def run_register(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.model_register(args.source, args.name, args.vram, args.category)
    if args.json:
        print_json(result)
        return
    if check_ok(result, use_color=use_color):
        print_ok(f"模型已登记: {args.name} ({args.category}, {args.vram}GB)", use_color)
