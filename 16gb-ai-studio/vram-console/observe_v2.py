"""GMae 第二轮观察脚本（增强版）：同时记录 nvidia-smi + ollama ps + GMae vram_ledger + QoS。
用于验证 6 项改进：P0-1 双源化、P0-2 context、P0-3 自动扫描、P1-4 并发、P1-5 利用率、P2-6 加载进度。
用法: python observe_v2.py [间隔秒] [持续秒]
"""
import subprocess, time, json, sys, os, urllib.request
from datetime import datetime

LOG = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\logs\gmae_observation_v2.log"
TOKEN = "o5NLMbpeJcTD8Z7vmXriuRjVB0WsQwzU"
BASE = "http://127.0.0.1:8787"
interval = int(sys.argv[1]) if len(sys.argv) > 1 else 10
duration = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
start = time.time()

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
        return r.stdout.strip()
    except Exception as e:
        return "ERROR: %s" % e

def api_get(path, timeout=8):
    try:
        req = urllib.request.Request(BASE + path, headers={"X-API-Key": TOKEN})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def ollama_ps():
    out = run("docker exec ollama ollama ps", 12)
    models = []
    for line in out.split("\n")[1:]:
        if line.strip():
            parts = line.split()
            if len(parts) >= 4:
                name = parts[0]
                size = parts[2] if len(parts) > 2 else "?"
                ctx = parts[4] if len(parts) > 4 else "?"
                models.append("%s(%s,ctx=%s)" % (name, size, ctx))
    return models

def registry_auto_count():
    try:
        with open(r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\resources\registry.json", encoding="utf-8") as f:
            r = json.load(f)
        auto = [m["id"] for m in r.get("ollama", {}).get("models", []) if m.get("auto_registered")]
        total = len(r.get("ollama", {}).get("models", []))
        return total, auto
    except:
        return 0, []

with open(LOG, "a", encoding="utf-8") as f:
    f.write("\n===== GMae 第二轮观察开始 %s (间隔%ds, 持续%ds) =====\n" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), interval, duration))

last_ps_str = ""
last_vram_state = ""
last_qos_level = ""
registry_check_counter = 0

while time.time() - start < duration:
    ts = datetime.now().strftime("%H:%M:%S")
    # 1. GPU
    gpu_out = run("nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits")
    parts = [p.strip() for p in gpu_out.split(",")]
    used_mb = int(parts[0]) if parts and parts[0].isdigit() else 0
    free_mb = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    util = parts[2].replace("%", "") if len(parts) > 2 else "?"

    # 2. ollama ps
    models = ollama_ps()
    ps_str = " | ".join(models) if models else "(空)"

    # 3. GMae status (vram_ledger + qos)
    status = api_get("/api/status")
    vl = status.get("vram_ledger", {})
    qos = status.get("qos", {})
    vram_state = vl.get("state", "?")
    vram_diff = vl.get("diff_mb", 0)
    qos_level = qos.get("level", "?")
    qos_util = qos.get("utilization", "?")
    qos_adjust = qos.get("adjust_note", "")

    # 4. loading_progress (if loading)
    load_msg = ""
    if vram_state == "loading" and vl.get("loading_progress"):
        lp = vl["loading_progress"]
        load_msg = " [加载中: %.1fGB/%d%%, ETA %ds]" % (lp.get("loaded_mb", 0)/1024, lp.get("percent", 0), lp.get("eta_seconds", 0))
    elif vram_state == "releasing" and vl.get("releasing_progress"):
        rp = vl["releasing_progress"]
        load_msg = " [释放中: %.1fGB, ETA %ds]" % (rp.get("releasing_mb", 0)/1024, rp.get("eta_seconds", 0))

    # 5. registry 自动登记检查（每 60 秒，即 6 次间隔）
    registry_check_counter += 1
    reg_msg = ""
    if registry_check_counter >= max(1, 60 // interval):
        registry_check_counter = 0
        total, auto = registry_auto_count()
        reg_msg = " [登记: %d个, 自动登记: %s]" % (total, ",".join(auto) if auto else "无")

    # 输出（变化时或每 60 秒强制输出）
    changed = (ps_str != last_ps_str) or (vram_state != last_vram_state) or (qos_level != last_qos_level)
    force_output = (int(time.time() - start) % 60) < interval
    if changed or force_output or load_msg or reg_msg:
        line = "[%s] GPU:%.1fGB/可用%.1fGB/%s%% | ollama:%d模型 | 账本:%s(差%.1fGB)%s | QoS:%s(util:%s)%s%s" % (
            ts, used_mb/1024, free_mb/1024, util, len(models),
            vram_state, vram_diff/1024, load_msg,
            qos_level, qos_util,
            " [%s]" % qos_adjust if qos_adjust else "",
            reg_msg)
        if models:
            line += "\n    模型: %s" % ps_str
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)

    last_ps_str = ps_str
    last_vram_state = vram_state
    last_qos_level = qos_level
    time.sleep(interval)

with open(LOG, "a", encoding="utf-8") as f:
    f.write("===== GMae 第二轮观察结束 %s =====\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("观察结束")
