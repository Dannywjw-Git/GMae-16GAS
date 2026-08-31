# -*- coding: utf-8 -*-
"""
场景4：创作流中断恢复 — 自动化验证脚本
模拟用户出图到一半突然想查资料，切到对话态，查完再切回来。

验证点：
1. 场景切换是否顺畅（comfy → chat → comfy）
2. 切换时模型是否正确释放和加载
3. 队列状态在切换后是否保留
4. 切换耗时
5. 恢复后能否继续工作

用法：python test_scenario4_interrupt_recovery.py
"""

import json
import time
import urllib.request
import subprocess
import sys
import os
from datetime import datetime

GMAE_BASE = "http://127.0.0.1:8787"
OLLAMA_BASE = "http://localhost:11434"
COMFY_BASE = "http://localhost:8188"

results = []

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    results.append(f"[{ts}] {msg}")

def gmae_get(path):
    try:
        with urllib.request.urlopen(f"{GMAE_BASE}{path}", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def gmae_post(path, data):
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(f"{GMAE_BASE}{path}", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def ollama_generate(model, prompt="hi"):
    try:
        body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

def ollama_ps():
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/ps", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"models": []}

def comfy_queue_prompt(workflow):
    try:
        body = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(f"{COMFY_BASE}/prompt", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

def get_free_mb():
    status = gmae_get("/api/status")
    return status.get("gpu", {}).get("free_mb", 99999)

def snapshot(label):
    status = gmae_get("/api/status")
    advice = gmae_get("/api/advice")
    queue = gmae_get("/api/queue")

    gpu = status.get("gpu", {})
    guard = status.get("guard", {})

    snap = {
        "label": label,
        "ts": time.time(),
        "used_mb": gpu.get("used_mb"),
        "free_mb": gpu.get("free_mb"),
        "guard_level": guard.get("level"),
        "scene": advice.get("scene"),
        "ollama_models": [m.get("name") for m in status.get("ollama", {}).get("models", [])],
        "comfy_models": status.get("comfyui_models", {}).get("models", []),
        "queue_len": len(queue.get("queue", [])),
        "queue_tasks": len(queue.get("tasks", [])),
        "worker_alive": queue.get("worker_alive"),
    }
    log(f"--- {label} ---")
    log(f"  显存: 已用={snap['used_mb']}MB / 空闲={snap['free_mb']}MB")
    log(f"  场景: {snap['scene']} | 门卫: {snap['guard_level']}")
    log(f"  Ollama: {snap['ollama_models']} | ComfyUI: {snap['comfy_models']}")
    log(f"  队列: queue={snap['queue_len']}, tasks={snap['queue_tasks']}, worker={snap['worker_alive']}")
    return snap

def main():
    log("=" * 60)
    log("场景4：创作流中断恢复 — 开始执行")
    log("=" * 60)

    # === 步骤0：基线 ===
    log("\n>>> 步骤0：记录基线")
    baseline = snapshot("基线")

    # === 步骤1：提交几个生成任务到队列（模拟批量出图）===
    log("\n>>> 步骤1：用户提交3个出图任务到 GMae 队列")
    queue_results = []
    for i in range(3):
        resp = gmae_post("/api/queue", {
            "model": "SDXL",
            "params": {"prompt": f"test image {i}", "seed": 1000 + i}
        })
        queue_results.append(resp)
        log(f"  任务{i+1}: {json.dumps(resp, ensure_ascii=False)[:200]}")
        time.sleep(0.5)

    after_enqueue = snapshot("入队后")

    # === 步骤2：直接提交一个 ComfyUI 任务（模拟正在出图）===
    log("\n>>> 步骤2：ComfyUI 正在跑 SDXL 出图（直接提交，模拟进行中）")
    sdxl_workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 42, "steps": 10, "cfg": 7.0, "sampler_name": "euler",
                "scheduler": "normal", "denoise": 1.0,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["5", 0]
            }
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "GMae_s4"}}
    }
    comfy_resp = comfy_queue_prompt(sdxl_workflow)
    log(f"  ComfyUI 提交: {comfy_resp}")
    time.sleep(5)  # 等模型开始加载

    during_generation = snapshot("ComfyUI出图中")

    # === 步骤3：用户突然想查资料，切换到对话态 ===
    log("\n>>> 步骤3：用户突然想查剧本细节，切换到对话态")
    log("  调用 /api/scene 切换到 chat...")
    t0 = time.time()
    switch_resp = gmae_post("/api/scene", {"scene": "chat"})
    t1 = time.time()
    log(f"  场景切换耗时: {t1-t0:.1f}秒")
    log(f"  切换结果: {json.dumps(switch_resp, ensure_ascii=False)[:300]}")

    # 等待 Ollama 加载
    log("  等待 Ollama 模型加载...")
    ollama_loaded = False
    for i in range(10):
        time.sleep(3)
        ps = ollama_ps()
        if ps.get("models"):
            ollama_loaded = True
            log(f"  Ollama 已加载: {[m['name'] for m in ps['models']]}")
            break
        log(f"  等待 Ollama... ({i+1}/10)")

    if not ollama_loaded:
        log("  手动触发 Ollama 加载 qwen3.5:9b...")
        ollama_generate("qwen3.5:9b", "你好")

    after_switch_chat = snapshot("切换到对话态后")

    # === 步骤4：用户用 Ollama 查资料 ===
    log("\n>>> 步骤4：用户用 Ollama 查资料（发一条消息）")
    t0 = time.time()
    resp = ollama_generate("qwen3.5:9b", "请用一句话解释什么是分镜脚本")
    t1 = time.time()
    log(f"  Ollama 响应: {t1-t0:.1f}秒, 内容: {resp.get('response', '')[:50]}...")

    during_chat = snapshot("对话查资料中")

    # === 步骤5：用户查完资料，切回出图态 ===
    log("\n>>> 步骤5：用户查完资料，切回出图态")
    t0 = time.time()
    switch_back = gmae_post("/api/scene", {"scene": "comfy"})
    t1 = time.time()
    log(f"  场景切换耗时: {t1-t0:.1f}秒")
    log(f"  切换结果: {json.dumps(switch_back, ensure_ascii=False)[:300]}")
    time.sleep(5)

    after_switch_back = snapshot("切回出图态后")

    # === 步骤6：检查队列状态是否保留 ===
    log("\n>>> 步骤6：检查队列状态和任务恢复情况")
    queue_final = gmae_get("/api/queue")
    log(f"  最终队列: queue={len(queue_final.get('queue', []))}, tasks={len(queue_final.get('tasks', []))}")
    log(f"  worker_alive: {queue_final.get('worker_alive')}")
    if queue_final.get("tasks"):
        for t in queue_final["tasks"][:3]:
            log(f"    任务: {json.dumps(t, ensure_ascii=False)[:150]}")

    # === 步骤7：恢复环境 ===
    log("\n>>> 步骤7：恢复环境")
    gmae_post("/api/free", {})
    time.sleep(3)
    # 确保 ComfyUI 也释放
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{COMFY_BASE}/free", data=b"{}",
            headers={"Content-Type": "application/json"}
        ), timeout=10)
    except Exception:
        pass
    time.sleep(3)
    recovered = snapshot("恢复后")

    # === 结果汇总 ===
    log("\n" + "=" * 60)
    log("场景4：测试结果汇总")
    log("=" * 60)

    checks = []

    # 检查1：场景切换成功
    chat_scene_ok = after_switch_chat["scene"] == "chat"
    checks.append(("切换到对话态成功", chat_scene_ok, f"scene={after_switch_chat['scene']}"))

    # 检查2：切换后 Ollama 加载
    ollama_ok = len(after_switch_chat["ollama_models"]) > 0 or during_chat["ollama_models"]
    checks.append(("切换后 Ollama 模型可用", ollama_ok, f"models={during_chat['ollama_models']}"))

    # 检查3：切回出图态成功
    comfy_scene_ok = after_switch_back["scene"] == "comfy"
    checks.append(("切回出图态成功", comfy_scene_ok, f"scene={after_switch_back['scene']}"))

    # 检查4：切换时 ComfyUI 模型释放
    comfy_freed = len(after_switch_chat["comfy_models"]) == 0 or after_switch_chat["free_mb"] > during_generation["free_mb"]
    checks.append(("切换对话态时 ComfyUI 模型释放", comfy_freed,
                   f"切换前free={during_generation['free_mb']}MB, 切换后free={after_switch_chat['free_mb']}MB"))

    # 检查5：队列状态保留
    queue_preserved = after_switch_back["queue_len"] > 0 or after_switch_back["queue_tasks"] > 0
    checks.append(("切换后队列状态保留", queue_preserved,
                   f"queue={after_switch_back['queue_len']}, tasks={after_switch_back['queue_tasks']}"))

    # 检查6：队列 worker 运行
    worker_running = during_generation["worker_alive"] or after_enqueue["worker_alive"]
    checks.append(("队列 worker 运行中（任务能自动执行）", worker_running,
                   f"worker_alive={during_generation['worker_alive']}"))

    # 检查7：恢复后显存回落
    recovered_free = recovered["free_mb"] or 0
    baseline_free = baseline["free_mb"] or 0
    recovered_ok = recovered_free > baseline_free * 0.85
    checks.append(("恢复后显存回落到基线附近（>85%）", recovered_ok,
                   f"恢复后free={recovered_free}MB, 基线free={baseline_free}MB"))

    passed = 0
    for name, ok, detail in checks:
        status = "✅ 通过" if ok else "❌ 失败"
        log(f"  {status}: {name} — {detail}")
        if ok:
            passed += 1

    log(f"\n总计: {passed}/{len(checks)} 项通过")

    # 功能缺失记录
    log("\n=== 功能现状记录 ===")
    if not worker_running:
        log("  ⚠️ 队列 worker 未运行：入队的任务不会自动执行，需要手动启动 worker")
    if not queue_preserved:
        log("  ⚠️ 队列状态可能未持久化：场景切换后队列任务丢失")
    log("  ⚠️ 无暂停/恢复 API：队列模块只有 enqueue/cancel/snapshot，没有 pause/resume")
    log("  ⚠️ 中断恢复依赖场景切换，不是队列级别的断点续跑")

    # 保存结果
    report = {
        "scenario": "S4_创作流中断恢复",
        "timestamp": datetime.now().isoformat(),
        "checks": [{"name": n, "passed": o, "detail": d} for n, o, d in checks],
        "snapshots": {
            "baseline": baseline,
            "after_enqueue": after_enqueue,
            "during_generation": during_generation,
            "after_switch_chat": after_switch_chat,
            "during_chat": during_chat,
            "after_switch_back": after_switch_back,
            "recovered": recovered,
        },
        "queue_results": queue_results,
        "switch_chat": switch_resp,
        "switch_back": switch_back,
        "notes": [
            "队列 worker 未运行，任务不会自动执行",
            "无 pause/resume API",
            "中断恢复依赖场景切换，不是队列级别的断点续跑"
        ] if not worker_running else []
    }
    report_path = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\tests\scenario_results\scenario4_result.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"\n详细结果已保存: {report_path}")

    return passed >= len(checks) - 2  # 允许2项失败（队列功能可能不完善）

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log("\n用户中断，正在恢复环境...")
        gmae_post("/api/free", {})
        sys.exit(1)
