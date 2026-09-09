"""
Benchmark A: 模型级显存分解准确率
测量 GMae 报告的模型级显存 vs torch 真实显存的误差率。

方法：
1. 释放 ComfyUI 显存，确认基线
2. 提交 SDXL 工作流（20步，给足够时间采样）
3. 在生成过程中每 2 秒同时采样 GMae 和 torch，取峰值时刻对比
4. 误差率 = |GMae估算模型合计 - torch真实已用| / torch真实已用
"""
import sys
import time
sys.path.insert(0, ".")
from bench_utils import (
    print_header, gpu_snapshot, gmae_comfy_models,
    comfy_system_stats, comfy_free, comfy_queue_prompt, comfy_history,
    save_result, gmae_health,
)

# SDXL 工作流（20步，给采样留时间）
SDXL_WORKFLOW = {
    "prompt": {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 42, "steps": 20, "cfg": 7.0, "sampler_name": "euler",
            "scheduler": "normal", "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]
        }},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a beautiful landscape painting, mountains, lake, sunset, highly detailed", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "bench_acc"}}
    }
}


def get_torch_vram():
    stats = comfy_system_stats()
    if "_error" in stats:
        return None
    devices = stats.get("devices", [])
    if not devices:
        return None
    d = devices[0]
    # 注意：ComfyUI 字段名是 torch_vram_total/torch_vram_free，单位是字节
    total_bytes = d.get("torch_vram_total", 0)
    free_bytes = d.get("torch_vram_free", 0)
    total_mb = round(total_bytes / (1024 * 1024), 1)
    free_mb = round(free_bytes / (1024 * 1024), 1)
    return {"total_mb": total_mb, "free_mb": free_mb, "used_mb": round(total_mb - free_mb, 1)}


def get_gmae_comfy():
    """获取 GMae ComfyUI 模型分解，返回 (模型合计MB, torch字段MB, 模型数, 模型详情)"""
    cm = gmae_comfy_models()
    if "_error" in cm:
        return None
    models = cm.get("models", [])
    total_gb = sum(m.get("vram_gb", 0) for m in models)
    total_mb = round(total_gb * 1024, 1)
    return {
        "models_sum_mb": total_mb,
        "model_count": len(models),
        "models": models,
        "torch_vram_used_mb": cm.get("torch_vram_used_mb", 0),
        "likely_loaded": cm.get("likely_loaded", False),
        "total_vram_gb": cm.get("total_vram_gb", 0),
        "note": cm.get("note", ""),
    }


def run_test(model_name, workflow, label, sample_interval=2, max_wait=180):
    print(f"\n--- Test: {label} ({model_name}) ---")

    # 1. 释放并确认基线
    print("  Freeing ComfyUI memory...")
    comfy_free()
    time.sleep(3)
    baseline_torch = get_torch_vram()
    baseline_gmae = get_gmae_comfy()
    print(f"  Baseline: torch={baseline_torch['used_mb'] if baseline_torch else 'N/A'}MB, "
          f"gmae_models={baseline_gmae['models_sum_mb'] if baseline_gmae else 'N/A'}MB")

    # 2. 提交工作流
    print(f"  Submitting {label} workflow (20 steps)...")
    result = comfy_queue_prompt(workflow)
    if "_error" in result or "prompt_id" not in result:
        print(f"  FAILED: {result}")
        return None
    prompt_id = result["prompt_id"]
    submit_time = time.time()
    print(f"  prompt_id={prompt_id}")

    # 3. 生成过程中采样，直到完成
    samples = []
    peak_torch = 0
    peak_sample = None
    while time.time() - submit_time < max_wait:
        torch_vram = get_torch_vram()
        gmae = get_gmae_comfy()
        gpu = gpu_snapshot()
        ts = time.time() - submit_time

        torch_used = torch_vram["used_mb"] if torch_vram else 0
        gmae_sum = gmae["models_sum_mb"] if gmae else 0

        sample = {
            "t_sec": round(ts, 1),
            "torch_used_mb": torch_used,
            "gmae_models_sum_mb": gmae_sum,
            "gmae_torch_field_mb": gmae["torch_vram_used_mb"] if gmae else 0,
            "gmae_likely_loaded": gmae["likely_loaded"] if gmae else False,
            "gpu_used_mb": gpu["used_mb"],
        }
        samples.append(sample)

        if torch_used > peak_torch:
            peak_torch = torch_used
            peak_sample = sample

        # 检查是否完成
        hist = comfy_history(prompt_id)
        if prompt_id in hist:
            print(f"  Generation completed at t={ts:.1f}s")
            break

        time.sleep(sample_interval)

    # 4. 用峰值时刻的数据计算误差
    if peak_sample and peak_sample["torch_used_mb"] > 100:
        error_abs = abs(peak_sample["gmae_models_sum_mb"] - peak_sample["torch_used_mb"])
        error_pct = round(error_abs / peak_sample["torch_used_mb"] * 100, 2)
        print(f"\n  PEAK at t={peak_sample['t_sec']}s:")
        print(f"    Torch actual:     {peak_sample['torch_used_mb']}MB")
        print(f"    GMae models sum:  {peak_sample['gmae_models_sum_mb']}MB")
        print(f"    GMae torch field: {peak_sample['gmae_torch_field_mb']}MB")
        print(f"    GPU total used:   {peak_sample['gpu_used_mb']}MB")
        print(f"    Error: {error_abs}MB ({error_pct}%)")
    else:
        error_abs = None
        error_pct = None
        print(f"  WARNING: no valid peak sample (peak_torch={peak_torch}MB)")

    # 5. 释放
    comfy_free()
    time.sleep(2)

    return {
        "model": label,
        "workflow_model": model_name,
        "sample_count": len(samples),
        "peak": peak_sample,
        "error_abs_mb": error_abs,
        "error_pct": error_pct,
        "all_samples": samples,
    }


def main():
    print_header("Model-Level VRAM Decomposition Accuracy")

    health = gmae_health()
    if "_error" in health:
        print("ERROR: GMae service not reachable")
        return
    print(f"GMae: free={health['services']['gpu']['free_mb']}MB")

    results = []
    r1 = run_test("sd_xl_base_1.0.safetensors", SDXL_WORKFLOW, "SDXL 1.0")
    if r1:
        results.append(r1)

    errors = [r["error_pct"] for r in results if r["error_pct"] is not None]
    summary = {
        "test_count": len(results),
        "avg_error_pct": round(sum(errors) / len(errors), 2) if errors else None,
        "max_error_pct": max(errors) if errors else None,
        "results": results,
    }
    save_result("vram_accuracy", summary)

    print(f"\n{'='*60}")
    print(f"  RESULT: avg_error={summary['avg_error_pct']}%, max_error={summary['max_error_pct']}%")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
