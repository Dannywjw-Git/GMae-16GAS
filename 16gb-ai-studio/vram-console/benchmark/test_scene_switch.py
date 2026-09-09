"""
Benchmark B: 场景切换耗时
测量 GMae 场景一键切换的端到端耗时，包括 API 响应 + 显存释放 + 模型加载。

测试场景对：
1. game -> sdxl（冷启动出图）
2. sdxl -> game（释放到游戏态）
3. game -> chat（加载对话模型）
4. chat -> game（释放对话）
5. sdxl -> chat（出图切对话，需要释放大模型+加载LLM）
"""
import sys
import time
sys.path.insert(0, ".")
from bench_utils import (
    print_header, gpu_snapshot, gmae_status, gmae_switch_scene,
    gmae_scenes, ollama_ps, comfy_free, save_result, gmae_health,
)


def get_current_scene():
    s = gmae_status()
    if "_error" in s or not s.get("ok"):
        return None
    return s.get("data", {}).get("scene", "unknown")


def wait_for_vram_stable(target_free_mb=None, timeout=60, interval=2):
    """等待显存稳定，返回 (稳定时显存, 等待秒数)"""
    start = time.time()
    last_used = None
    stable_count = 0
    while time.time() - start < timeout:
        snap = gpu_snapshot()
        if "_error" in snap:
            time.sleep(interval)
            continue
        used = snap["used_mb"]
        if last_used is not None and abs(used - last_used) < 100:
            stable_count += 1
            if stable_count >= 2:
                return snap, round(time.time() - start, 1)
        else:
            stable_count = 0
        last_used = used
        time.sleep(interval)
    return gpu_snapshot(), round(time.time() - start, 1)


def run_switch(from_scene, to_scene, label):
    """执行一次场景切换测试"""
    print(f"\n--- Switch: {from_scene} -> {to_scene} ({label}) ---")

    # 确保在起始场景
    current = get_current_scene()
    if current != from_scene:
        print(f"  Current scene={current}, switching to {from_scene} first...")
        gmae_switch_scene(from_scene)
        time.sleep(5)

    before = gpu_snapshot()
    print(f"  Before: scene={get_current_scene()}, GPU used={before['used_mb']}MB, free={before['free_mb']}MB")

    # 执行切换并计时
    api_start = time.time()
    result, api_elapsed = gmae_switch_scene(to_scene)
    api_end = time.time()

    ok = result.get("ok", False) if isinstance(result, dict) else False
    print(f"  API response: ok={ok}, elapsed={api_elapsed}s")
    if not ok:
        print(f"  Result: {result}")

    # 等待显存稳定
    stable_snap, stable_elapsed = wait_for_vram_stable(timeout=90)
    total_elapsed = round(time.time() - api_start, 1)

    after = gpu_snapshot()
    print(f"  After:  scene={get_current_scene()}, GPU used={after['used_mb']}MB, free={after['free_mb']}MB")
    print(f"  Timing: API={api_elapsed}s, stabilize={stable_elapsed}s, total={total_elapsed}s")

    return {
        "from": from_scene,
        "to": to_scene,
        "label": label,
        "api_ok": ok,
        "api_elapsed_sec": api_elapsed,
        "stabilize_sec": stable_elapsed,
        "total_elapsed_sec": total_elapsed,
        "before_gpu_used_mb": before["used_mb"],
        "after_gpu_used_mb": after["used_mb"],
        "vram_delta_mb": after["used_mb"] - before["used_mb"],
    }


def main():
    print_header("Scene Switch Latency Benchmark")

    health = gmae_health()
    if "_error" in health:
        print("ERROR: GMae service not reachable")
        return
    print(f"GMae: free={health['services']['gpu']['free_mb']}MB")

    # 先回到游戏态（干净基线）
    print("\n=== Reset to game scene ===")
    gmae_switch_scene("game")
    time.sleep(5)
    comfy_free()
    time.sleep(2)

    results = []

    # 测试序列（场景名: dialogue/comfyui/fooocus/game/idle/maintenance）
    tests = [
        ("game", "comfyui", "冷启动出图（加载SDXL）"),
        ("comfyui", "game", "出图→游戏（释放SDXL）"),
        ("game", "dialogue", "冷启动对话（加载9B）"),
        ("dialogue", "game", "对话→游戏（释放LLM）"),
        ("game", "comfyui", "第二次冷启动出图（验证一致性）"),
        ("comfyui", "dialogue", "出图→对话（释放大模型+加载LLM）"),
    ]

    for from_s, to_s, label in tests:
        r = run_switch(from_s, to_s, label)
        results.append(r)
        time.sleep(2)  # 切换间休息

    # 回到游戏态
    gmae_switch_scene("game")

    # 汇总
    valid = [r for r in results if r["api_ok"]]
    if valid:
        avg_total = round(sum(r["total_elapsed_sec"] for r in valid) / len(valid), 1)
        max_total = max(r["total_elapsed_sec"] for r in valid)
        min_total = min(r["total_elapsed_sec"] for r in valid)
    else:
        avg_total = max_total = min_total = None

    summary = {
        "test_count": len(results),
        "success_count": len(valid),
        "avg_total_sec": avg_total,
        "max_total_sec": max_total,
        "min_total_sec": min_total,
        "results": results,
    }

    save_result("scene_switch_latency", summary)

    print(f"\n{'='*60}")
    print(f"  RESULT: {len(valid)}/{len(results)} success")
    print(f"  Avg total={avg_total}s, min={min_total}s, max={max_total}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
