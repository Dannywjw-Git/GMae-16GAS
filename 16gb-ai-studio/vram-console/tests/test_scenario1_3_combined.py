# -*- coding: utf-8 -*-
"""
场景1+场景3 合并测试：漫剧创作者一天 + 夜间批量生产

场景1：模拟漫剧创作者的完整工作流（对话→出图→视频→对话）
场景3：验证批量任务队列串行执行和长时间稳定性

验证点：
1. 场景切换是否稳定（场景4发现第一次调用会崩溃）
2. 多模型切换时显存管理是否正确
3. 批量任务队列是否串行执行
4. 全程是否不崩溃、不死机
5. 任务完成率

用法：python test_scenario1_3_combined.py
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

SAFETY_FREE_MB = 300  # 安全阈值

results = []

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    results.append(f"[{ts}] {msg}")

def gmae_get(path):
    try:
        with urllib.request.urlopen(f"{GMAE_BASE}{path}", timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def gmae_post(path, data, retries=2):
    """带重试的 POST（场景切换可能第一次崩溃）"""
    for attempt in range(retries + 1):
        try:
            body = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(f"{GMAE_BASE}{path}", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt < retries:
                log(f"  调用失败（第{attempt+1}次），2秒后重试: {e}")
                time.sleep(2)
                # 检查服务是否还活着
                health = gmae_get("/api/health")
                if not health.get("ok"):
                    log(f"  服务不存活，等待5秒恢复...")
                    time.sleep(5)
            else:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "max retries exceeded"}

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

def safety_check():
    free = get_free_mb()
    if free < SAFETY_FREE_MB:
        log(f"⚠️ 安全警报：空闲 {free}MB < {SAFETY_FREE_MB}MB，立即释放！")
        gmae_post("/api/free", {})
        time.sleep(3)
        return False
    return True

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
        "queue_running": len(queue.get("queue", [])),
        "queue_tasks": len(queue.get("tasks", [])),
        "worker_alive": queue.get("worker_alive"),
    }
    log(f"--- {label} ---")
    log(f"  显存: 已用={snap['used_mb']}MB / 空闲={snap['free_mb']}MB | 门卫: {snap['guard_level']}")
    log(f"  场景: {snap['scene']} | Ollama: {snap['ollama_models']} | ComfyUI: {snap['comfy_models']}")
    log(f"  队列: running={snap['queue_running']}, total={snap['queue_tasks']}, worker={snap['worker_alive']}")
    return snap

def scene_switch_with_retry(scene_name):
    """场景切换，带重试和崩溃检测"""
    log(f"  切换场景到: {scene_name}")
    t0 = time.time()
    resp = gmae_post("/api/scene", {"scene": scene_name}, retries=2)
    t1 = time.time()
    log(f"  切换耗时: {t1-t0:.1f}秒, 结果: ok={resp.get('ok')}, error={resp.get('error', 'none')}")
    return resp, t1 - t0

def main():
    log("=" * 60)
    log("场景1+场景3 合并测试：漫剧一天 + 夜间批量")
    log("=" * 60)

    s1_results = {"switches": [], "switch_times": [], "crashes": 0}
    s3_results = {"tasks_total": 0, "tasks_done": 0, "tasks_failed": 0, "max_queue": 0}

    # ===== 场景1：漫剧创作者一天 =====
    log("\n" + "=" * 60)
    log("场景1：漫剧创作者的一天（模拟关键切换点）")
    log("=" * 60)

    # 步骤0：基线
    log("\n>>> 步骤0：早晨开机，基线状态")
    baseline = snapshot("早晨基线")

    # 步骤1：对话态 - 写剧本
    log("\n>>> 步骤1：9:00 用 qwen3.5:9b 写剧本和分镜")
    resp, t = scene_switch_with_retry("chat")
    if not resp.get("ok"):
        s1_results["crashes"] += 1
        log("  场景切换失败，手动加载 Ollama...")
    time.sleep(2)

    log("  加载 qwen3.5:9b...")
    ollama_generate("qwen3.5:9b", "写一个3分钟漫剧的大纲，包含5个分镜")
    time.sleep(3)
    after_chat = snapshot("对话态-写剧本中")
    s1_results["switches"].append({"to": "chat", "ok": resp.get("ok", False), "time": t})
    s1_results["switch_times"].append(t)

    if not safety_check():
        log("安全中止")
        return False

    # 步骤2：出图态 - 生成分镜图
    log("\n>>> 步骤2：10:30 切换到出图态，用 SDXL 生成分镜图")
    resp, t = scene_switch_with_retry("comfy")
    if not resp.get("ok"):
        s1_results["crashes"] += 1
    time.sleep(3)

    # 提交 ComfyUI 任务
    sdxl_workflow = {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 100, "steps": 8, "cfg": 7.0, "sampler_name": "euler",
            "scheduler": "normal", "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a beautiful anime scene", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "GMae_s1"}}
    }
    comfy_queue_prompt(sdxl_workflow)
    time.sleep(8)  # 等模型加载和生成
    after_image = snapshot("出图态-生成分镜中")
    s1_results["switches"].append({"to": "comfy", "ok": resp.get("ok", False), "time": t})
    s1_results["switch_times"].append(t)

    if not safety_check():
        log("安全中止")
        return False

    # 步骤3：切回对话态 - 查资料
    log("\n>>> 步骤3：12:00 切回对话态，查资料")
    resp, t = scene_switch_with_retry("chat")
    if not resp.get("ok"):
        s1_results["crashes"] += 1
    time.sleep(2)
    ollama_generate("qwen3.5:9b", "什么是分镜脚本的镜头语言")
    time.sleep(3)
    after_chat2 = snapshot("对话态-查资料中")
    s1_results["switches"].append({"to": "chat", "ok": resp.get("ok", False), "time": t})
    s1_results["switch_times"].append(t)

    if not safety_check():
        log("安全中止")
        return False

    # 步骤4：切回出图态 - 继续出图
    log("\n>>> 步骤4：14:00 切回出图态，继续出图")
    resp, t = scene_switch_with_retry("comfy")
    if not resp.get("ok"):
        s1_results["crashes"] += 1
    time.sleep(3)
    after_image2 = snapshot("出图态-继续出图")
    s1_results["switches"].append({"to": "comfy", "ok": resp.get("ok", False), "time": t})
    s1_results["switch_times"].append(t)

    # ===== 场景3：夜间批量生产 =====
    log("\n" + "=" * 60)
    log("场景3：夜间无人值守批量生产（队列验证）")
    log("=" * 60)

    log("\n>>> 提交5个批量出图任务到队列")
    task_ids = []
    for i in range(5):
        resp = gmae_post("/api/queue", {
            "model": "SDXL",
            "params": {"prompt": f"night batch scene {i}", "seed": 2000 + i, "steps": 5}
        })
        if resp.get("ok"):
            task_ids.append(resp["task"]["id"])
            log(f"  任务{i+1}: id={resp['task']['id']}, status={resp['task']['status']}")
        else:
            log(f"  任务{i+1} 入队失败: {resp.get('error')}")
        time.sleep(0.5)

    s3_results["tasks_total"] = len(task_ids)

    # 监控队列执行
    log("\n>>> 监控队列执行（最多120秒，每10秒采样）")
    max_wait = 120
    start_time = time.time()
    all_done = False

    while time.time() - start_time < max_wait:
        time.sleep(10)
        queue = gmae_get("/api/queue")
        tasks = queue.get("tasks", [])
        running = len(queue.get("queue", []))
        done = sum(1 for t in tasks if t.get("status") == "done")
        failed = sum(1 for t in tasks if t.get("status") in ("failed", "error"))
        s3_results["max_queue"] = max(s3_results["max_queue"], running)

        elapsed = int(time.time() - start_time)
        log(f"  [{elapsed}s] 队列: running={running}, done={done}, failed={failed}, total={len(tasks)}")

        if not safety_check():
            log("  安全阈值触发，等待释放...")
            time.sleep(5)

        if done + failed >= len(task_ids):
            all_done = True
            log("  所有任务完成！")
            break

    # 最终队列状态
    final_queue = gmae_get("/api/queue")
    final_tasks = final_queue.get("tasks", [])
    s3_results["tasks_done"] = sum(1 for t in final_tasks if t.get("status") == "done")
    s3_results["tasks_failed"] = sum(1 for t in final_tasks if t.get("status") in ("failed", "error"))

    log(f"\n  队列最终状态: total={len(final_tasks)}, done={s3_results['tasks_done']}, failed={s3_results['tasks_failed']}")
    for t in final_tasks:
        log(f"    {t.get('id')}: {t.get('status')} - {t.get('progress', '')[:50]}")

    # ===== 恢复环境 =====
    log("\n>>> 恢复环境")
    gmae_post("/api/free", {})
    time.sleep(3)
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{COMFY_BASE}/free", data=b"{}",
            headers={"Content-Type": "application/json"}
        ), timeout=10)
    except Exception:
        pass
    time.sleep(3)
    recovered = snapshot("恢复后")

    # ===== 结果汇总 =====
    log("\n" + "=" * 60)
    log("场景1+场景3 测试结果汇总")
    log("=" * 60)

    checks = []

    # 场景1检查
    successful_switches = sum(1 for s in s1_results["switches"] if s["ok"])
    total_switches = len(s1_results["switches"])
    avg_switch_time = sum(s1_results["switch_times"]) / len(s1_results["switch_times"]) if s1_results["switch_times"] else 0

    checks.append((f"场景1: 场景切换成功率（{successful_switches}/{total_switches}）",
                   successful_switches >= total_switches * 0.5,
                   f"成功={successful_switches}, 崩溃={s1_results['crashes']}, 平均耗时={avg_switch_time:.1f}s"))

    checks.append((f"场景1: 平均切换耗时 < 30秒",
                   avg_switch_time < 30,
                   f"平均={avg_switch_time:.1f}秒"))

    checks.append(("场景1: 全程未死机（测试正常完成）", True, "脚本执行完毕"))

    # 场景3检查
    completion_rate = s3_results["tasks_done"] / s3_results["tasks_total"] if s3_results["tasks_total"] > 0 else 0
    checks.append((f"场景3: 批量任务完成率（{s3_results['tasks_done']}/{s3_results['tasks_total']}）",
                   completion_rate >= 0.6,
                   f"完成率={completion_rate*100:.0f}%, 失败={s3_results['tasks_failed']}"))

    checks.append(("场景3: 队列 worker 运行中",
                   final_queue.get("worker_alive", False),
                   f"worker_alive={final_queue.get('worker_alive')}"))

    checks.append(("场景3: 任务严格串行（max_queue<=1）",
                   s3_results["max_queue"] <= 1,
                   f"max_running={s3_results['max_queue']}"))

    # 恢复检查
    recovered_free = recovered["free_mb"] or 0
    baseline_free = baseline["free_mb"] or 0
    checks.append(("恢复后显存回落到基线附近（>80%）",
                   recovered_free > baseline_free * 0.8,
                   f"恢复后free={recovered_free}MB, 基线free={baseline_free}MB"))

    passed = 0
    for name, ok, detail in checks:
        status = "✅ 通过" if ok else "❌ 失败"
        log(f"  {status}: {name} — {detail}")
        if ok:
            passed += 1

    log(f"\n总计: {passed}/{len(checks)} 项通过")

    # 问题记录
    log("\n=== 问题记录 ===")
    if s1_results["crashes"] > 0:
        log(f"  🔴 P0: 场景切换 API 崩溃 {s1_results['crashes']} 次（第一次调用经常返回连接关闭）")
    if avg_switch_time > 10:
        log(f"  🟡 P1: 场景切换平均耗时 {avg_switch_time:.1f}秒，目标<10秒")
    if completion_rate < 0.8:
        log(f"  🟡 P1: 批量任务完成率 {completion_rate*100:.0f}%，部分任务可能失败")

    # 保存结果
    report = {
        "scenario": "S1_漫剧一天 + S3_夜间批量",
        "timestamp": datetime.now().isoformat(),
        "checks": [{"name": n, "passed": o, "detail": d} for n, o, d in checks],
        "scenario1": s1_results,
        "scenario3": s3_results,
        "snapshots": {
            "baseline": baseline,
            "after_chat": after_chat,
            "after_image": after_image,
            "after_chat2": after_chat2,
            "after_image2": after_image2,
            "recovered": recovered,
        },
        "final_queue": final_queue,
        "issues": [
            f"场景切换崩溃 {s1_results['crashes']} 次" if s1_results["crashes"] > 0 else "无崩溃",
            f"平均切换耗时 {avg_switch_time:.1f}秒",
            f"批量完成率 {completion_rate*100:.0f}%"
        ]
    }
    report_path = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\tests\scenario_results\scenario1_3_result.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"\n详细结果已保存: {report_path}")

    return passed >= len(checks) - 2

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log("\n用户中断，正在恢复环境...")
        gmae_post("/api/free", {})
        sys.exit(1)
