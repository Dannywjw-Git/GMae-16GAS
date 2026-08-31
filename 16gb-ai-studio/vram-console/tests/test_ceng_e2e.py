#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-Eng E2E 测试 v2 - 增加超时，分步测试"""
import json
import urllib.request

def chat(message, execute=False, timeout=120):
    payload = {"message": message, "execute": execute}
    req = urllib.request.Request(
        "http://127.0.0.1:8789/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def print_result(label, r):
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    print(f"  ok: {r.get('ok')}")
    print(f"  intent: {r.get('intent')}")
    print(f"  backend: {r.get('backend_used')} ({r.get('backend_tier')})")
    print(f"  confidence: {r.get('confidence')}")
    print(f"  latency: {r.get('latency_ms')}ms")
    print(f"  vram_peak: {r.get('estimated_vram_peak')}GB")
    print(f"  plan steps: {len(r.get('plan', []))}")
    for step in r.get("plan", []):
        print(f"    step {step.get('step')}: {step.get('tool')} args={json.dumps(step.get('args', {}), ensure_ascii=False)}")
        print(f"      reason: {step.get('reason')}")
    val = r.get("validation", {})
    print(f"  validation: all_passed={val.get('all_passed')}")
    for s in val.get("steps", []):
        status = "PASS" if s.get("passed") else "REJECT"
        print(f"    [{status}] {s.get('tool')}: {s.get('reason', '')}")
    if r.get("error"):
        print(f"  ERROR: {r.get('error')}")

# 测试1: 查询类
r1 = chat("当前显存状态是什么？")
print_result("测试1: 查询类（只读）", r1)

# 测试2: 文生图
r2 = chat("帮我出一张日落风景的图")
print_result("测试2: 文生图（写操作，过准入）", r2)

# 测试3: 显存释放
r3 = chat("显存不够了，帮我释放一下")
print_result("测试3: 显存释放", r3)

print("\n" + "="*50)
print("  E2E 测试完成")
print("="*50)
