"""快速测试 Ollama 9B 生成速度和显存"""
import sys, time
sys.path.insert(0, ".")
from bench_utils import ollama_generate, gpu_snapshot, comfy_free, ollama_ps

comfy_free()
time.sleep(2)

print("=== qwen3.5:9b generation test ===")
before = gpu_snapshot()
print(f"Before: used={before['used_mb']}MB, free={before['free_mb']}MB")

print("Warming up (loading model)...")
r1, t1 = ollama_generate("qwen3.5:9b", "Say hello in one word", timeout=120)
time.sleep(2)
after_load = gpu_snapshot()
print(f"After load: used={after_load['used_mb']}MB, free={after_load['free_mb']}MB")
loaded = ollama_ps()
models = [(m.get("model"), round(m.get("size_gb", 0), 1)) for m in loaded.get("models", [])]
print(f"Ollama loaded: {models}")

print("Running generation test...")
r2, t2 = ollama_generate("qwen3.5:9b", "Write a short poem about AI, exactly 4 lines.", timeout=120)
eval_count = r2.get("eval_count", 0) if isinstance(r2, dict) else 0
speed = round(eval_count / t2, 1) if t2 > 0 else 0
print(f"Generation: {t2}s, eval_count={eval_count}, speed={speed} tok/s")
if isinstance(r2, dict):
    print(f"Response: {r2.get('response', '')[:120]}")

peak = max(before["used_mb"], after_load["used_mb"])
print(f"Peak GPU used: {peak}MB ({round(peak/1024, 1)}GB)")
