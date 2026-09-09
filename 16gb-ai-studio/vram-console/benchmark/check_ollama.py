"""检查 ollama 状态并手动加载 9B"""
import sys, time
sys.path.insert(0, ".")
from bench_utils import ollama_ps, ollama_generate, gpu_snapshot

print("=== Ollama status ===")
try:
    ps = ollama_ps()
    models = [(m.get("model"), m.get("size_gb")) for m in ps.get("models", [])]
    print(f"Loaded models: {models}")
except Exception as e:
    print(f"ollama_ps error: {e}")

print("\nLoading qwen3.5:9b (warmup)...")
before = gpu_snapshot()
print(f"Before: free={before['free_mb']}MB")
r, t = ollama_generate("qwen3.5:9b", "say hi", timeout=120)
print(f"Generate took {t}s, type: {type(r).__name__}")
if isinstance(r, dict):
    print(f"  eval_count={r.get('eval_count')}, error={r.get('error')}")
elif isinstance(r, str):
    print(f"  result: {r[:100]}")
time.sleep(3)
after = gpu_snapshot()
print(f"After: free={after['free_mb']}MB, used={after['used_mb']}MB")

ps2 = ollama_ps()
models2 = [(m.get("model"), round(m.get("size_gb", 0), 1)) for m in ps2.get("models", [])]
print(f"Loaded after: {models2}")
