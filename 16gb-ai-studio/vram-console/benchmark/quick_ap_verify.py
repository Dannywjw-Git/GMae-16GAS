"""快速验证 auto_protect 是否触发（加载 9B 后等待 qos_loop）"""
import sys, time
sys.path.insert(0, ".")
from bench_utils import ollama_generate, gpu_snapshot, _http_get, comfy_free, gmae_auto_protect_status

TOKEN = "o5NLMbpeJcTD8Z7vmXriuRjVB0WsQwzU"
BASE = "http://127.0.0.1:8787"

def gmae_qos_status():
    return _http_get(f"{BASE}/api/qos/status", headers={"X-API-Key": TOKEN})

print("=== Quick auto_protect verification ===")

comfy_free()
time.sleep(2)
base = gpu_snapshot()
print(f"Baseline: free={base['free_mb']}MB")

qos0 = gmae_qos_status()
print(f"QoS before: level={qos0['data']['level']}, history={len(qos0['data']['history'])}")
ap0 = gmae_auto_protect_status()
print(f"AP before: enabled={ap0['data']['enabled']}, mode={ap0['data']['mode']}, triggers={len(ap0['data']['history'])}")

print("\nLoading qwen3.5:9b...")
r, t = ollama_generate("qwen3.5:9b", "hi", timeout=120)
time.sleep(3)
after = gpu_snapshot()
print(f"After 9B: free={after['free_mb']}MB, used={after['used_mb']}MB")

print("\nWaiting 15s for qos_loop...")
for i in range(15):
    time.sleep(1)
    if i % 5 == 4:
        snap = gpu_snapshot()
        print(f"  t={i+1}s: free={snap['free_mb']}MB")

qos1 = gmae_qos_status()
print(f"\nQoS after: level={qos1['data']['level']}, history={len(qos1['data']['history'])}")
if qos1['data']['history']:
    print(f"  Last: {qos1['data']['history'][-1]}")
if qos1['data']['last_action']:
    print(f"  Last action: {qos1['data']['last_action']}")

ap1 = gmae_auto_protect_status()
print(f"AP after: triggers={len(ap1['data']['history'])}")
if ap1['data']['history']:
    print(f"  Last: {ap1['data']['history'][-1]}")
if ap1['data']['last_trigger']:
    print(f"  Detail: {ap1['data']['last_trigger']}")

final = gpu_snapshot()
print(f"\nFinal VRAM: free={final['free_mb']}MB")

triggered = len(ap1['data']['history']) > 0 or qos1['data']['level'] == 'emergency'
print(f"\n=== RESULT: {'TRIGGERED' if triggered else 'NOT TRIGGERED'} ===")
