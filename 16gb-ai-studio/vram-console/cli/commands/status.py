#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""status 命令组：系统状态总览"""
from ..formatter import print_json, print_kv, format_vram_bar, _c, check_ok


def register(subparsers):
    p = subparsers.add_parser("status", help="系统状态总览（显存/场景/模型/QoS）")
    p.add_argument("--json", action="store_true", help="输出原始 JSON")
    p.add_argument("--quiet", action="store_true", help="精简输出")
    p.set_defaults(func=run)


def run(args, client, cfg):
    use_color = cfg.get("color", True)
    result = client.status()
    if args.json:
        print_json(result)
        return
    # /api/status 直接返回状态字典（无 ok 字段），用 gpu 字段判断成功
    if not result.get("gpu"):
        err = result.get("error", "无法获取状态")
        if not args.quiet:
            from ..formatter import print_error
            print_error(err, use_color)
        return

    # 显存水位（API 返回 MB，转换为 GB）
    gpu = result.get("gpu", {})
    total = gpu.get("total_mb", 16384) / 1024
    used = gpu.get("used_mb", 0) / 1024
    free = gpu.get("free_mb", 0) / 1024
    print(_c("\n=== 显存水位 ===", "cyan", use_color))
    print("  " + format_vram_bar(used, total, use_color=use_color))
    print(f"  空闲: {free:.1f} GB  |  已用: {used:.1f} GB  |  总计: {total:.1f} GB")

    # 危险等级
    ledger = result.get("vram_ledger", {})
    danger = ledger.get("danger_level", "safe")
    danger_map = {"safe": ("安全", "green"), "warning": ("警告", "yellow"),
                  "danger": ("危险", "red"), "critical": ("危急", "red")}
    label, color = danger_map.get(danger, (danger, "gray"))
    print(f"  危险等级: {_c(label, color, use_color)}")

    # 场景（可能是字符串或字典）
    print(_c("\n=== 当前场景 ===", "cyan", use_color))
    scene = result.get("scene", {})
    if isinstance(scene, str):
        current = scene
        exclusive = False
    else:
        current = scene.get("current", scene.get("name", "未知"))
        exclusive = scene.get("exclusive", False)
    print(f"  场景: {_c(current, 'bold', use_color)}")
    if exclusive:
        print(f"  {_c('独占模式', 'yellow', use_color)}")

    # 模型
    print(_c("\n=== 活跃模型 ===", "cyan", use_color))
    ollama = result.get("ollama", {})
    loaded = ollama.get("loaded", []) or ollama.get("models", [])
    if loaded:
        for m in loaded:
            name = m.get("name", m.get("model", "?"))
            vram = m.get("vram_gb", m.get("size_gb", "?"))
            print(f"  - {name}  ({vram} GB)")
    else:
        print(_c("  （无模型加载）", "gray", use_color))

    # ComfyUI
    comfy = result.get("comfyui", {})
    if comfy.get("running") or comfy.get("models"):
        cmodels = comfy.get("models", [])
        if cmodels:
            print(f"\n  ComfyUI 已加载: {len(cmodels)} 个模型")

    # QoS
    print(_c("\n=== QoS 状态 ===", "cyan", use_color))
    qos = result.get("qos", {})
    level = qos.get("level", "unknown")
    print(f"  水位: {level}")
    if qos.get("msg"):
        print(f"  消息: {qos['msg']}")

    # 服务活跃度
    print(_c("\n=== 服务活跃度 ===", "cyan", use_color))
    activity = result.get("activity", {})
    services = activity.get("services", {})
    if services:
        for name, info in services.items():
            status = info.get("status", "?")
            last = info.get("last_active_minutes", "?")
            icon = _c("●", "green", use_color) if status == "active" else _c("○", "gray", use_color)
            print(f"  {icon} {name}: {status}  (闲置 {last} 分钟)")

    print()
