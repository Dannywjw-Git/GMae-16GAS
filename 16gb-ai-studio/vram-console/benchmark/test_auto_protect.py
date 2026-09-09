"""
Benchmark C: 自动防死机响应时间
测量 auto_protect 从触发到完成释放的端到端时间。

方法：
1. 切换到 aggressive 模式（<4GB 空闲即触发 L1）
2. 加载 Ollama 9B 模型 + ComfyUI SDXL，使空闲显存 <4GB
3. 监控 auto_protect 状态，记录触发时间和释放完成时间
4. 测试完恢复 standard 模式
"""
import sys
import time
sys.path.insert(0, ".")
from bench_utils import (
    print_header, gpu_snapshot, gmae_status,
    _http_get, _http_post, GMAE_BASE, GMAE_HEADERS,
    ollama_generate, comfy_free, comfy_queue_prompt, comfy_wait_for_prompt,
    save_result, gmae_health,
)

SDXL_WORKFLOW = {
    "prompt": {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 42, "steps": 30, "cfg": 7.0, "sampler_name": "euler",
            "scheduler": "normal", "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]
        }},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "test", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "bench_ap"}}
    }
}


def auto_protect_status():
    return _http_get(f"{GMAE_BASE}/api/auto-protect/status", headers=GMAE_HEADERS)


def auto_protect_config(enabled=None, mode=None):
    data = {}
    if enabled is not None:
        data["enabled"] = enabled
    if mode is not None:
        data["mode"] = mode
    return _http_post(f"{GMAE_BASE}/api/auto-protect/config", data, headers=GMAE_HEADERS)


def wait_for_auto_protect_trigger(timeout=120, interval=2):
    """等待 auto_protect 触发，返回 (触发记录, 等待秒数)"""
    start = time.time()
    while time.time() - start < timeout:
        status = auto_protect_status()
        if "_error" not in status and status.get("ok"):
            data = status.get("data", status)
            last = data.get("last_trigger")
            history = data.get("history", [])
            if last or history:
                return data, round(time.time() - start, 1)
        time.sleep(interval)
    return None, round(time.time() - start, 1)


def wait_for_vram_recovery(target_free_mb=6000, timeout=120, interval=2):
    """等待显存恢复到目标空闲以上"""
    start = time.time()
    while time.time() - start < timeout:
        snap = gpu_snapshot()
        if "_error" not in snap and snap["free_mb"] >= target_free_mb:
            return snap, round(time.time() - start, 1)
        time.sleep(interval)
    return gpu_snapshot(), round(time.time() - start, 1)


def main():
    print_header("Auto-Protect Response Time Benchmark")

    health = gmae_health()
    if "_error" in health:
        print("ERROR: GMae service not reachable")
        return
    print(f"GMae: free={health['services']['gpu']['free_mb']}MB")

    # 记录初始配置
    initial_status = auto_protect_status()
    initial_mode = initial_status.get("data", initial_status).get("mode", "standard")
    print(f"Initial auto_protect: enabled={initial_status.get('data', initial_status).get('enabled')}, mode={initial_mode}")

    results = {}

    try:
        # 1. 切换到 aggressive 模式
        print("\n=== Step 1: Switch to aggressive mode ===")
        auto_protect_config(enabled=True, mode="aggressive")
        time.sleep(2)
        print("  Mode set to aggressive (<4GB triggers L1)")

        # 2. 释放显存到干净状态
        print("\n=== Step 2: Free memory baseline ===")
        comfy_free()
        time.sleep(3)
        baseline = gpu_snapshot()
        print(f"  Baseline: used={baseline['used_mb']}MB, free={baseline['free_mb']}MB")

        # 3. 加载 SDXL（约 6.5GB）
        print("\n=== Step 3: Load SDXL via ComfyUI (1 step) ===")
        result = comfy_queue_prompt(SDXL_WORKFLOW)
        if "prompt_id" in result:
            comfy_wait_for_prompt(result["prompt_id"], timeout=120)
        time.sleep(2)
        after_sdxl = gpu_snapshot()
        print(f"  After SDXL: used={after_sdxl['used_mb']}MB, free={after_sdxl['free_mb']}MB")

        # 4. 加载 Ollama 9B（约 5-6GB），使空闲 <4GB
        print("\n=== Step 4: Load qwen3.5:9b via Ollama ===")
        ollama_start = time.time()
        ollama_result, ollama_elapsed = ollama_generate("qwen3.5:9b", "Say hello", timeout=120)
        time.sleep(3)
        after_llm = gpu_snapshot()
        print(f"  After 9B LLM: used={after_llm['used_mb']}MB, free={after_llm['free_mb']}MB (load took {ollama_elapsed}s)")

        # 5. 等待 auto_protect 触发
        print("\n=== Step 5: Wait for auto_protect trigger ===")
        trigger_start = time.time()
        ap_data, wait_sec = wait_for_auto_protect_trigger(timeout=180)
        trigger_time = time.time() - trigger_start

        if ap_data:
            last_trigger = ap_data.get("last_trigger", {})
            history = ap_data.get("history", [])
            print(f"  TRIGGERED after {trigger_time:.1f}s!")
            print(f"  last_trigger: {last_trigger}")
            print(f"  history count: {len(history)}")
            results["triggered"] = True
            results["trigger_wait_sec"] = round(trigger_time, 1)
            results["last_trigger"] = last_trigger
        else:
            print(f"  NOT triggered within {trigger_time:.1f}s")
            results["triggered"] = False
            results["trigger_wait_sec"] = round(trigger_time, 1)

        # 6. 等待显存恢复
        print("\n=== Step 6: Wait for VRAM recovery ===")
        recovery_snap, recovery_sec = wait_for_vram_recovery(target_free_mb=6000, timeout=120)
        print(f"  Recovery: free={recovery_snap['free_mb']}MB after {recovery_sec}s")
        results["recovery_sec"] = recovery_sec
        results["recovery_free_mb"] = recovery_snap["free_mb"]

        # 7. 总响应时间
        if results["triggered"]:
            results["total_response_sec"] = round(trigger_time + recovery_sec, 1)
        else:
            results["total_response_sec"] = None

    finally:
        # 恢复原配置
        print("\n=== Cleanup: Restore original mode ===")
        auto_protect_config(enabled=True, mode=initial_mode)
        comfy_free()
        time.sleep(2)
        final = gpu_snapshot()
        print(f"  Restored to {initial_mode}, free={final['free_mb']}MB")

    results["initial_mode"] = initial_mode
    results["test_mode"] = "aggressive"
    save_result("auto_protect_response", results)

    print(f"\n{'='*60}")
    print(f"  RESULT: triggered={results['triggered']}")
    print(f"  Trigger wait: {results.get('trigger_wait_sec')}s")
    print(f"  Recovery: {results.get('recovery_sec')}s")
    print(f"  Total response: {results.get('total_response_sec')}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
