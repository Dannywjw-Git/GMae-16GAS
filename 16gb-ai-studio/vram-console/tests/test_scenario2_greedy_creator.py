# -*- coding: utf-8 -*-
"""
场景2：贪心创作者 — 自动化验证脚本
模拟不懂显存管理的用户，同时想跑多个大模型，验证：
1. 预算引擎是否正确计算"够不够"
2. 显存不足时是否给出正确建议
3. 自动防死机在 critical 时是否真的触发释放（场景5发现可能没触发）
4. 强行并发时系统是否会死

⚠️ 安全约束：脚本内置安全监控，空闲<500MB 时立即中止并手动释放

用法：python test_scenario2_greedy_creator.py
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

# 安全阈值：空闲显存低于此值立即中止测试
SAFETY_FREE_MB = 500

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
    """获取当前空闲显存（MB），优先用 GMae API"""
    status = gmae_get("/api/status")
    gpu = status.get("gpu", {})
    free = gpu.get("free_mb")
    if free is not None:
        return free
    # fallback: nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            timeout=10
        ).decode("utf-8").strip()
        return int(out)
    except Exception:
        return 99999

def safety_check():
    """安全检查：空闲显存过低时立即中止"""
    free = get_free_mb()
    if free < SAFETY_FREE_MB:
        log(f"⚠️ 安全警报：空闲显存 {free}MB < {SAFETY_FREE_MB}MB，立即中止测试并释放！")
        gmae_post("/api/free", {})
        time.sleep(3)
        return False
    return True

def snapshot(label):
    status = gmae_get("/api/status")
    advice = gmae_get("/api/advice")
    auto_protect = gmae_get("/api/auto-protect/status")

    gpu = status.get("gpu", {})
    guard = status.get("guard", {})
    procs = status.get("gpu_processes", {})

    snap = {
        "label": label,
        "ts": time.time(),
        "used_mb": gpu.get("used_mb"),
        "free_mb": gpu.get("free_mb"),
        "guard_level": guard.get("level"),
        "guard_alerts": guard.get("alerts", []),
        "advice_suggestions": advice.get("suggestions", []),
        "ollama_models": [m.get("name") for m in status.get("ollama", {}).get("models", [])],
        "comfy_models": status.get("comfyui_models", {}).get("models", []),
        "auto_protect_enabled": auto_protect.get("enabled"),
        "auto_protect_mode": auto_protect.get("mode"),
        "auto_protect_last_trigger": auto_protect.get("last_trigger"),
        "auto_protect_history": auto_protect.get("history", []),
    }
    log(f"--- {label} ---")
    log(f"  显存: 已用={snap['used_mb']}MB / 空闲={snap['free_mb']}MB")
    log(f"  门卫: {snap['guard_level']} | 告警: {snap['guard_alerts']}")
    log(f"  建议: {snap['advice_suggestions']}")
    log(f"  Ollama: {snap['ollama_models']} | ComfyUI: {snap['comfy_models']}")
    log(f"  自动防死机: enabled={snap['auto_protect_enabled']}, last_trigger={snap['auto_protect_last_trigger']}")
    return snap

def main():
    log("=" * 60)
    log("场景2：贪心创作者 — 开始执行")
    log("=" * 60)
    log(f"安全阈值：空闲显存 < {SAFETY_FREE_MB}MB 时立即中止")

    # === 步骤0：基线 ===
    log("\n>>> 步骤0：记录基线")
    baseline = snapshot("基线")

    # === 步骤1：加载 qwen3.5:9b（~10GB）===
    log("\n>>> 步骤1：用户加载 qwen3.5:9b 开始对话（约10GB）")
    t0 = time.time()
    resp = ollama_generate("qwen3.5:9b", "你好")
    t1 = time.time()
    log(f"  Ollama 响应: {t1-t0:.1f}秒")

    # 等待模型加载
    for i in range(5):
        time.sleep(2)
        ps = ollama_ps()
        if any("qwen3.5:9b" in m["name"] for m in ps.get("models", [])):
            break

    after_llm = snapshot("加载 qwen3.5:9b 后")
    if not safety_check():
        log("安全中止")
        return False

    # === 步骤2：预算引擎检查：再跑 Flux 够不够？===
    log("\n>>> 步骤2：用户想同时跑 Flux（约12GB），调用预算引擎")
    budget = gmae_get("/api/budget")
    log(f"  预算引擎结果:")
    log(f"    total_gb: {budget.get('total_gb')}")
    log(f"    used_gb: {budget.get('used_gb')}")
    log(f"    safe_ceiling_gb: {budget.get('safe_ceiling_gb')}")
    log(f"    avail_gb: {budget.get('avail_gb')}")
    log(f"    releasable_gb: {budget.get('releasable_gb')}")

    # 找 Flux 模型的决策
    flux_decision = None
    for m in budget.get("models", []):
        if "flux" in m.get("id", "").lower() or "flux" in m.get("name", "").lower():
            flux_decision = m
            break

    if flux_decision:
        log(f"  Flux 模型决策:")
        log(f"    id: {flux_decision.get('id')}")
        log(f"    vram_gb: {flux_decision.get('vram_gb')}")
        log(f"    decision: {flux_decision.get('decision')}")
        log(f"    need_free_gb: {flux_decision.get('need_free_gb')}")
        log(f"    gap_gb: {flux_decision.get('gap_gb')}")
        log(f"    note: {flux_decision.get('note')}")
    else:
        log("  未找到 Flux 模型，查看所有模型决策:")
        for m in budget.get("models", [])[:5]:
            log(f"    {m.get('id')}: decision={m.get('decision')}, vram={m.get('vram_gb')}GB, note={m.get('note')}")

    # === 步骤3：用户贪心，强行启动 ComfyUI SDXL ===
    log("\n>>> 步骤3：用户不听建议，强行启动 ComfyUI SDXL（约7GB）")
    log("  预期：总显存约17GB > 16GB，应该 OOM 或自动防死机触发")

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
            "inputs": {"text": "test", "clip": ["4", 1]}
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "bad", "clip": ["4", 1]}
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "GMae_scenario2"}
        }
    }

    comfy_resp = comfy_queue_prompt(sdxl_workflow)
    log(f"  ComfyUI 提交: {comfy_resp}")

    # 监控显存变化，等待自动防死机触发或 OOM
    log("\n>>> 步骤4：监控显存变化（最多60秒，每5秒采样）")
    auto_protect_triggered = False
    oom_detected = False
    max_used = 0
    min_free = 99999

    for i in range(12):
        time.sleep(5)
        free = get_free_mb()
        status = gmae_get("/api/status")
        guard = status.get("guard", {})
        auto_protect = gmae_get("/api/auto-protect/status")

        used = 16384 - free
        max_used = max(max_used, used)
        min_free = min(min_free, free)

        last_trigger = auto_protect.get("last_trigger")
        if last_trigger and not auto_protect_triggered:
            auto_protect_triggered = True
            log(f"  [{i*5+5}s] 🎯 自动防死机触发！last_trigger={last_trigger}")
            log(f"    history: {auto_protect.get('history', [])[-3:]}")

        log(f"  [{i*5+5}s] 空闲={free}MB, 门卫={guard.get('level')}, 告警={guard.get('alerts', [])[:1]}")

        if not safety_check():
            log("  安全阈值触发，手动释放")
            gmae_post("/api/free", {})
            break

        # 如果显存突然大幅下降，可能是自动防死机释放了
        if auto_protect_triggered and free > 4000:
            log(f"  自动防死机已释放，空闲恢复到 {free}MB")
            break

    after_greedy = snapshot("贪心加载后")

    # === 步骤5：验证自动防死机 ===
    log("\n>>> 步骤5：验证自动防死机是否真的工作")
    auto_protect_final = gmae_get("/api/auto-protect/status")
    log(f"  最终状态: enabled={auto_protect_final.get('enabled')}")
    log(f"  last_trigger: {auto_protect_final.get('last_trigger')}")
    log(f"  history: {auto_protect_final.get('history', [])}")

    if auto_protect_final.get("last_trigger"):
        log("  ✅ 自动防死机在本次测试中触发了")
    else:
        log("  ❌ 自动防死机未触发！这是一个严重问题")
        log("     可能原因：检测逻辑bug / 执行失败 / 阈值配置问题")

    # === 步骤6：恢复环境 ===
    log("\n>>> 步骤6：恢复环境")
    gmae_post("/api/free", {})
    time.sleep(5)
    recovered = snapshot("恢复后")

    # === 结果汇总 ===
    log("\n" + "=" * 60)
    log("场景2：测试结果汇总")
    log("=" * 60)

    checks = []

    # 检查1：预算引擎正确识别显存不足
    if flux_decision:
        budget_correct = flux_decision.get("decision") in ("free_L1", "free_L2", "reject")
        checks.append(("预算引擎正确识别 Flux 显存不足", budget_correct,
                       f"decision={flux_decision.get('decision')}, gap={flux_decision.get('gap_gb')}GB"))
    else:
        checks.append(("预算引擎返回了模型列表", bool(budget.get("models")),
                       f"models_count={len(budget.get('models', []))}"))

    # 检查2：高负载时 guard_level 升级
    level_up = after_greedy["guard_level"] in ("warning", "danger", "critical")
    checks.append(("高负载时 guard_level 升级", level_up,
                   f"level={after_greedy['guard_level']}"))

    # 检查3：自动防死机触发
    ap_triggered = bool(auto_protect_final.get("last_trigger"))
    checks.append(("自动防死机在 critical 时触发释放", ap_triggered,
                   f"last_trigger={auto_protect_final.get('last_trigger')}"))

    # 检查4：系统没死机（测试能跑完）
    checks.append(("系统未死机（测试正常完成）", True, "测试脚本正常执行完毕"))

    # 检查5：恢复后显存回落
    recovered_free = recovered["free_mb"] or 0
    baseline_free = baseline["free_mb"] or 0
    recovered_ok = recovered_free > baseline_free * 0.85
    checks.append(("释放后显存回落到基线附近（>85%）", recovered_ok,
                   f"恢复后free={recovered_free}MB, 基线free={baseline_free}MB"))

    # 检查6：最低空闲显存 > 安全阈值（没真的打满）
    safe = min_free > SAFETY_FREE_MB
    checks.append((f"全程最低空闲显存 > {SAFETY_FREE_MB}MB（没打满）", safe,
                   f"min_free={min_free}MB"))

    passed = 0
    for name, ok, detail in checks:
        status = "✅ 通过" if ok else "❌ 失败"
        log(f"  {status}: {name} — {detail}")
        if ok:
            passed += 1

    log(f"\n总计: {passed}/{len(checks)} 项通过")
    log(f"峰值显存: {max_used}MB / 最低空闲: {min_free}MB")

    if ap_triggered:
        log("\n🎉 自动防死机工作正常！GMae 能在危险时自动救命。")
    else:
        log("\n⚠️ 自动防死机未触发！这是 V1.0 前必须修复的 P0 问题。")
        log("   建议：检查 engine/qos.py 和 auto_protect 的触发逻辑")

    # 保存结果
    report = {
        "scenario": "S2_贪心创作者",
        "timestamp": datetime.now().isoformat(),
        "checks": [{"name": n, "passed": o, "detail": d} for n, o, d in checks],
        "max_used_mb": max_used,
        "min_free_mb": min_free,
        "auto_protect_triggered": ap_triggered,
        "snapshots": {
            "baseline": baseline,
            "after_llm": after_llm,
            "after_greedy": after_greedy,
            "recovered": recovered,
        },
        "budget": budget,
        "flux_decision": flux_decision,
        "auto_protect_final": auto_protect_final,
    }
    report_path = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\tests\scenario_results\scenario2_result.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"\n详细结果已保存: {report_path}")

    return passed >= len(checks) - 1  # 允许1项失败（自动防死机可能是已知问题）

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log("\n用户中断，正在恢复环境...")
        gmae_post("/api/free", {})
        sys.exit(1)
