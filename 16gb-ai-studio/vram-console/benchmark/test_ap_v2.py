"""可靠的 auto_protect 响应时间测试：检测 history 数量变化"""
import sys, time
sys.path.insert(0, ".")
from bench_utils import (ollama_generate, gpu_snapshot, comfy_free,
                          gmae_auto_protect_status, _http_get)

TOKEN = "o5NLMbpeJcTD8Z7vmXriuRjVB0WsQwzU"
BASE = "http://127.0.0.1:8787"

def qos_status():
    return _http_get(f"{BASE}/api/qos/status", headers={"X-API-Key": TOKEN})

print("=== Auto-Protect Response Time Test (v2) ===")

# 基线
comfy_free()
time.sleep(2)
base = gpu_snapshot()
print(f"Baseline: free={base['free_mb']}MB")

# 记录初始 history 数量
ap0 = gmae_auto_protect_status()
initial_triggers = len(ap0["data"]["history"])
print(f"Initial AP triggers: {initial_triggers}")

# 切换到 aggressive
_http_get(f"{BASE}/api/auto-protect/config?enabled=true&mode=aggressive", headers={"X-API-Key": TOKEN})
# 用 POST
import json
_http_post = __import__("bench_utils")._http_post
_http_post(f"{BASE}/api/auto-protect/config", {"enabled": True, "mode": "aggressive"}, headers={"X-API-Key": TOKEN})
print("Mode: aggressive")

# 加载 9B
print("\nLoading qwen3.5:9b...")
t0 = time.time()
r, t = ollama_generate("qwen3.5:9b", "Write a long story about AI.", timeout=120)
load_time = time.time() - t0
time.sleep(2)
after = gpu_snapshot()
print(f"After 9B: free={after['free_mb']}MB (load took {load_time:.1f}s)")

if after["free_mb"] > 2048:
    print("WARNING: VRAM not low enough, 9B may not have loaded properly")
else:
    print(f"VRAM critical: {after['free_mb']}MB < 2048MB threshold")

# 等待触发（检测 history 数量变化）
print("\nWaiting for auto_protect trigger (max 60s)...")
trigger_time = None
for i in range(60):
    time.sleep(1)
    ap = gmae_auto_protect_status()
    current_triggers = len(ap["data"]["history"])
    if current_triggers > initial_triggers:
        trigger_time = i + 1
        last = ap["data"]["history"][-1]
        print(f"  TRIGGERED after {trigger_time}s!")
        print(f"  Level: {last.get('level')}, free_mb: {last.get('free_mb')}")
        print(f"  Actions: {[a.get('action') for a in last.get('actions', [])]}")
        break
    if i % 10 == 9:
        snap = gpu_snapshot()
        qos = qos_status()
        print(f"  t={i+1}s: free={snap['free_mb']}MB, qos={qos['data']['level']}, triggers={current_triggers}")

if trigger_time is None:
    print("  NOT triggered within 60s")
else:
    # 等待显存恢复
    print("\nWaiting for VRAM recovery...")
    recovery_time = None
    for i in range(60):
        time.sleep(1)
        snap = gpu_snapshot()
        if snap["free_mb"] > 4096:
            recovery_time = i + 1
            print(f"  Recovered after {recovery_time}s: free={snap['free_mb']}MB")
            break
        if i % 10 == 9:
            print(f"  t={i+1}s: free={snap['free_mb']}MB")

# 恢复 standard 模式
_http_post(f"{BASE}/api/auto-protect/config", {"enabled": True, "mode": "standard"}, headers={"X-API-Key": TOKEN})

# 最终状态
final = gpu_snapshot()
print(f"\nFinal: free={final['free_mb']}MB")
print(f"\n=== RESULT: triggered={trigger_time is not None}, trigger_wait={trigger_time}s, recovery={recovery_time}s ===")
