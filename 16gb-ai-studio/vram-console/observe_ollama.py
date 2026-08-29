"""GMae 观察脚本：持续记录 GPU 状态 + ollama ps 到日志文件。
用法: python observe_ollama.py [间隔秒] [持续秒]
"""
import subprocess, time, json, sys, os
from datetime import datetime

LOG = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\logs\ollama_observation.log"
interval = int(sys.argv[1]) if len(sys.argv) > 1 else 15
duration = int(sys.argv[2]) if len(sys.argv) > 2 else 1800  # 默认30分钟
start = time.time()

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
        return r.stdout.strip()
    except Exception as e:
        return "ERROR: %s" % e

with open(LOG, "a", encoding="utf-8") as f:
    f.write("\n===== 观察开始 %s (间隔%ds, 持续%ds) =====\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), interval, duration))

last_ps = ""
last_gpu_used = 0

while time.time() - start < duration:
    ts = datetime.now().strftime("%H:%M:%S")
    # GPU 状态
    gpu_out = run('nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits')
    parts = [p.strip() for p in gpu_out.split(",")]
    used_mb = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
    free_mb = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    util = parts[2] if len(parts) > 2 else "?"
    
    # ollama ps
    ps_out = run('docker exec ollama ollama ps', timeout=15)
    ps_lines = [l for l in ps_out.split("\n") if l.strip() and not l.startswith("NAME")]
    
    # 检测变化
    ps_changed = ps_out != last_ps
    gpu_changed = abs(used_mb - last_gpu_used) > 200  # 变化超过200MB才记录
    
    if ps_changed or gpu_changed or (time.time() - start) % 60 < interval:
        line = "[%s] GPU: 已用%.1fGB/可用%.1fGB 利用率%s%% | ollama加载: %d个模型" % (
            ts, used_mb/1024, free_mb/1024, util, len(ps_lines))
        if ps_lines:
            for pl in ps_lines:
                line += "\n    模型: %s" % pl[:80]
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)
    
    last_ps = ps_out
    last_gpu_used = used_mb
    time.sleep(interval)

with open(LOG, "a", encoding="utf-8") as f:
    f.write("===== 观察结束 %s =====\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("观察结束")
