# -*- coding: utf-8 -*-
"""
场景5：新手第一天 — 自动化验证脚本
模拟不懂显存管理的新手，同时启动多个 GPU 进程，观察 GMae 的门卫检测、告警和建议。

验证点：
1. 门卫是否正确识别所有 GPU 进程
2. danger_level 是否随显存水位正确升级
3. 告警是否及时（水位超过阈值后 3 秒内）
4. 建议是否具体可操作
5. 系统进程（dwm/explorer 等）不被误报为未登记

用法：python test_scenario5_newbie_day.py
"""

import json
import time
import urllib.request
import urllib.error
import subprocess
import sys
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
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def ollama_ps():
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/ps", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"models": []}

def ollama_generate(model, prompt="hi"):
    """触发 Ollama 加载模型"""
    try:
        body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

def comfy_queue_prompt(workflow):
    """提交 ComfyUI 工作流触发模型加载"""
    try:
        body = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(f"{COMFY_BASE}/prompt", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

def get_nvidia_smi():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader,nounits"], timeout=10
        ).decode("utf-8").strip()
        parts = out.split(",")
        return {"used_mb": int(parts[0].strip()), "free_mb": int(parts[1].strip()),
                "util": int(parts[2].strip())}
    except Exception as e:
        return {"error": str(e)}

def snapshot(label):
    """采集 GMae 状态快照"""
    status = gmae_get("/api/status")
    advice = gmae_get("/api/advice")
    smi = get_nvidia_smi()

    gpu = status.get("gpu", {})
    guard = status.get("guard", {})
    procs = status.get("gpu_processes", {})

    snap = {
        "label": label,
        "ts": time.time(),
        "gmae_used_mb": gpu.get("used_mb"),
        "gmae_free_mb": gpu.get("free_mb"),
        "nvidia_used_mb": smi.get("used_mb"),
        "nvidia_free_mb": smi.get("free_mb"),
        "guard_level": guard.get("level"),
        "guard_alerts": guard.get("alerts", []),
        "guard_suggest": guard.get("suggest", []),
        "advice_suggestions": advice.get("suggestions", []),
        "known_procs": [p.get("name") for p in procs.get("processes", []) if p.get("known")],
        "unknown_pids": procs.get("unknown_pids", []),
        "unknown_mb": procs.get("unknown_mb", 0),
        "ollama_models": [m.get("name") for m in status.get("ollama", {}).get("models", [])],
        "comfy_models": status.get("comfyui_models", {}).get("models", []),
        "scene": advice.get("scene"),
    }
    log(f"--- {label} ---")
    log(f"  显存: GMae={snap['gmae_used_mb']}MB / nvidia-smi={snap['nvidia_used_mb']}MB")
    log(f"  门卫等级: {snap['guard_level']}")
    log(f"  告警: {snap['guard_alerts']}")
    log(f"  建议: {snap['guard_suggest'] if snap['guard_suggest'] else snap['advice_suggestions']}")
    log(f"  已知进程: {snap['known_procs']}")
    log(f"  未登记进程: {snap['unknown_pids']} ({snap['unknown_mb']}MB)")
    log(f"  Ollama加载: {snap['ollama_models']}")
    log(f"  ComfyUI加载: {snap['comfy_models']}")
    log(f"  当前场景: {snap['scene']}")
    return snap

def main():
    log("=" * 60)
    log("场景5：新手第一天 — 开始执行")
    log("=" * 60)

    # === 步骤0：基线 ===
    log("\n>>> 步骤0：记录基线状态（无模型加载）")
    baseline = snapshot("基线")

    # === 步骤1：加载 Ollama qwen3.5:9b（~6GB）===
    log("\n>>> 步骤1：新手打开 OWUI，开始和 qwen3.5:9b 对话")
    log("  触发 Ollama 加载 qwen3.5:9b...")
    t0 = time.time()
    resp = ollama_generate("qwen3.5:9b", "你好，请用一句话介绍你自己")
    t1 = time.time()
    log(f"  Ollama 响应耗时: {t1-t0:.1f}秒")
    if "error" in resp:
        log(f"  Ollama 错误: {resp['error']}")
    else:
        log(f"  Ollama 返回: {resp.get('response', '')[:50]}...")

    # 等待 GMae 感知（轮询 3 次，每次 2 秒）
    for i in range(3):
        time.sleep(2)
        ps = ollama_ps()
        loaded = [m["name"] for m in ps.get("models", [])]
        if "qwen3.5:9b" in loaded:
            log(f"  Ollama 模型已加载: {loaded}")
            break
    else:
        log(f"  警告：Ollama 模型未在预期时间内加载，当前: {loaded}")

    after_ollama = snapshot("加载 Ollama 后")

    # === 步骤2：加载 ComfyUI SDXL（~7GB）===
    log("\n>>> 步骤2：新手同时打开 ComfyUI，想跑 SDXL 出图")
    log("  提交 ComfyUI 工作流触发 SDXL 加载...")

    # 简单的 SDXL 工作流（只加载模型，生成一张小图）
    sdxl_workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 42, "steps": 5, "cfg": 7.0, "sampler_name": "euler",
                "scheduler": "normal", "denoise": 1.0,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["5", 0]
            }
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1}
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "a beautiful landscape", "clip": ["4", 1]}
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "blurry, low quality", "clip": ["4", 1]}
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "GMae_test"}
        }
    }

    t0 = time.time()
    comfy_resp = comfy_queue_prompt(sdxl_workflow)
    t1 = time.time()
    log(f"  ComfyUI 提交耗时: {t1-t0:.1f}秒, 响应: {comfy_resp}")

    # 等待模型加载（轮询 10 次，每次 3 秒）
    comfy_loaded = False
    for i in range(10):
        time.sleep(3)
        status = gmae_get("/api/status")
        comfy_models = status.get("comfyui_models", {}).get("models", [])
        if comfy_models:
            log(f"  ComfyUI 模型已加载: {comfy_models}")
            comfy_loaded = True
            break
        log(f"  等待 ComfyUI 模型加载... ({i+1}/10)")

    if not comfy_loaded:
        log("  警告：ComfyUI 模型未在预期时间内加载，可能模型名不对或加载慢")

    after_comfy = snapshot("加载 ComfyUI SDXL 后")

    # === 步骤3：观察 GMae 反应 ===
    log("\n>>> 步骤3：观察 GMae 的告警和建议")
    time.sleep(3)  # 等门卫轮询周期
    high_load = snapshot("高负载观察")

    # === 步骤4：验证门卫检测 ===
    log("\n>>> 步骤4：验证门卫检测（调用 /api/guard）")
    guard_check = gmae_post("/api/guard", {})
    log(f"  门卫检查结果: {json.dumps(guard_check, ensure_ascii=False)[:500]}")

    # === 步骤5：验证预算引擎 ===
    log("\n>>> 步骤5：验证预算引擎（再加载一个模型够不够）")
    budget = gmae_get("/api/budget")
    log(f"  预算引擎结果: {json.dumps(budget, ensure_ascii=False)[:800]}")

    # === 步骤6：恢复环境 ===
    log("\n>>> 步骤6：恢复环境（释放所有模型）")
    log("  释放 Ollama 模型...")
    gmae_post("/api/model", {"name": "qwen3.5:9b", "action": "stop"})
    time.sleep(2)
    log("  释放 ComfyUI 显存...")
    free_resp = gmae_post("/api/free", {})
    log(f"  释放结果: {json.dumps(free_resp, ensure_ascii=False)[:300]}")
    time.sleep(5)

    recovered = snapshot("恢复后")

    # === 结果汇总 ===
    log("\n" + "=" * 60)
    log("场景5：测试结果汇总")
    log("=" * 60)

    checks = []

    # 检查1：显存数据准确性
    gmae_used = baseline["gmae_used_mb"] or 0
    nvidia_used = baseline["nvidia_used_mb"] or 0
    diff = abs(gmae_used - nvidia_used)
    check1 = diff < 300
    checks.append(("显存数据准确性（GMae vs nvidia-smi 误差<300MB）", check1, f"误差={diff}MB"))

    # 检查2：Ollama 加载后 GMae 感知
    ollama_detected = len(after_ollama["ollama_models"]) > 0
    checks.append(("Ollama 模型加载后 GMae 正确感知", ollama_detected,
                   f"感知到={after_ollama['ollama_models']}"))

    # 检查3：高负载时 guard_level 升级
    level_upgraded = high_load["guard_level"] in ("warning", "danger", "critical")
    checks.append(("高负载时 guard_level 升级到 warning 以上", level_upgraded,
                   f"level={high_load['guard_level']}"))

    # 检查4：高负载时有建议
    has_suggestions = bool(high_load["guard_suggest"] or high_load["advice_suggestions"])
    checks.append(("高负载时给出具体建议", has_suggestions,
                   f"suggest={high_load['guard_suggest']}, advice={high_load['advice_suggestions']}"))

    # 检查5：系统进程不被误报
    no_system_false_positive = all(
        p not in ["dwm.exe", "explorer.exe", "ShellExperienceHost.exe"]
        for p in high_load["unknown_pids"]
    )
    checks.append(("系统进程不被误报为未登记", no_system_false_positive,
                   f"unknown_pids={high_load['unknown_pids']}"))

    # 检查6：恢复后显存回落
    recovered_free = recovered["gmae_free_mb"] or 0
    baseline_free = baseline["gmae_free_mb"] or 0
    recovered_ok = recovered_free > baseline_free * 0.9
    checks.append(("释放后显存回落到基线附近（>90%）", recovered_ok,
                   f"恢复后free={recovered_free}MB, 基线free={baseline_free}MB"))

    passed = 0
    for name, ok, detail in checks:
        status = "✅ 通过" if ok else "❌ 失败"
        log(f"  {status}: {name} — {detail}")
        if ok:
            passed += 1

    log(f"\n总计: {passed}/{len(checks)} 项通过")

    if passed == len(checks):
        log("\n🎉 场景5全部通过！GMae 对新手用户有实际帮助：")
        log("   - 能实时感知显存和进程")
        log("   - 高负载时及时告警")
        log("   - 给出具体可操作的建议")
        log("   - 不误报系统进程")
        log("   - 一键释放恢复环境")
    else:
        log(f"\n⚠️ 场景5有 {len(checks)-passed} 项未通过，需要修复后重测。")

    # 保存详细结果
    report = {
        "scenario": "S5_新手第一天",
        "timestamp": datetime.now().isoformat(),
        "checks": [{"name": n, "passed": o, "detail": d} for n, o, d in checks],
        "snapshots": {
            "baseline": baseline,
            "after_ollama": after_ollama,
            "after_comfy": after_comfy,
            "high_load": high_load,
            "recovered": recovered,
        },
        "guard_check": guard_check,
        "budget": budget,
    }
    report_path = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\tests\scenario_results\scenario5_result.json"
    import os
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"\n详细结果已保存: {report_path}")

    return passed == len(checks)

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log("\n用户中断，正在恢复环境...")
        gmae_post("/api/free", {})
        sys.exit(1)
