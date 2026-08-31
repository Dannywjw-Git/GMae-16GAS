#!/usr/bin/env python3
"""E2E验证：7项改进后的C-Eng关键场景"""
import json, urllib.request, time, subprocess

def get_vram():
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5
    )
    parts = result.stdout.strip().split(",")
    return float(parts[0]), float(parts[1])

def chat(msg, execute=False):
    payload = {"message": msg, "execute": execute}
    req = urllib.request.Request(
        "http://127.0.0.1:8789/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())

print("=" * 60)
print("场景1: 查询类（快道，应<5秒）")
print("=" * 60)
used, free = get_vram()
print(f"当前显存: 已用 {used/1024:.1f}GB, 空闲 {free/1024:.1f}GB")
r = chat("当前显存状态")
print(f"  intent: {r.get('intent')}")
print(f"  backend: {r.get('backend_used')} ({r.get('backend_tier')})")
print(f"  latency: {r.get('latency_ms')}ms")
print(f"  plan: {[s.get('tool') for s in r.get('plan', [])]}")
print(f"  validation: {r.get('validation', {}).get('all_passed')}")
print()

print("=" * 60)
print("场景2: 模糊请求（应返回clarify意图，无操作步骤）")
print("=" * 60)
r = chat("帮我弄一下")
print(f"  intent: {r.get('intent')}")
print(f"  plan长度: {len(r.get('plan', []))}")
print(f"  confidence: {r.get('confidence')}")
print(f"  期望: intent=clarify, plan=[]")
print()

print("=" * 60)
print("场景3: 文生图（深道，决策后应自动释放9b）")
print("=" * 60)
used_before, free_before = get_vram()
print(f"决策前: 已用 {used_before/1024:.1f}GB, 空闲 {free_before/1024:.1f}GB")
r = chat("出一张日落风景图")
time.sleep(3)
used_after, free_after = get_vram()
print(f"决策后: 已用 {used_after/1024:.1f}GB, 空闲 {free_after/1024:.1f}GB")
print(f"  intent: {r.get('intent')}")
print(f"  backend: {r.get('backend_used')} ({r.get('backend_tier')})")
print(f"  latency: {r.get('latency_ms')}ms")
print(f"  plan: {[s.get('tool') for s in r.get('plan', [])]}")
print(f"  validation: {r.get('validation', {}).get('all_passed')}")
print(f"  9b释放: {(used_before - used_after)/1024:.1f}GB (期望>5GB)")
for s in r.get("validation", {}).get("steps", []):
    status = "PASS" if s.get("passed") else "REJECT"
    print(f"    [{status}] {s.get('tool')}: {s.get('reason', '')}")
print()

print("=" * 60)
print("场景4: 连续对话（第二轮应能看到历史上下文）")
print("=" * 60)
r = chat("再来一张海边的")
print(f"  intent: {r.get('intent')}")
print(f"  plan: {[s.get('tool') for s in r.get('plan', [])]}")
print(f"  (期望: 理解'再'指继续出图，规划submit_task)")
print()

print("全部E2E验证完成")
