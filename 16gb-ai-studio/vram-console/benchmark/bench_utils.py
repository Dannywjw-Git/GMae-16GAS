"""
GMae 系统级 Benchmark 工具集
零外部依赖，Python 标准库即可运行。
用于测量：模型级显存分解准确率、场景切换耗时、自动防死机响应、全模态能力矩阵。
"""
import json
import time
import os
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

# === 配置 ===
GMAE_BASE = "http://127.0.0.1:8787"
COMFY_BASE = "http://127.0.0.1:8188"
OLLAMA_BASE = "http://127.0.0.1:11434"
RESULTS_DIR = "results"

# === API Token（优先环境变量，其次 .api_token 文件）===
def _load_api_token():
    env = os.environ.get("VRAM_CONSOLE_TOKEN", "")
    if env:
        return env
    token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".api_token")
    try:
        with open(token_path, "r", encoding="ascii") as f:
            return f.read().strip()
    except Exception:
        return ""

API_TOKEN = _load_api_token()
GMAE_HEADERS = {"X-API-Key": API_TOKEN} if API_TOKEN else {}


def _http_get(url, timeout=10, headers=None):
    """HTTP GET，返回 dict 或 None"""
    try:
        h = dict(headers or {})
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"_error": str(e)}


def _http_post(url, data, timeout=30, headers=None):
    """HTTP POST JSON，返回 dict 或 None"""
    try:
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"_error": str(e)}


# === nvidia-smi 显存采样 ===
def gpu_snapshot():
    """获取当前 GPU 显存快照，返回 dict"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader,nounits"],
            text=True, timeout=5
        ).strip()
        parts = [p.strip() for p in out.split(",")]
        return {
            "total_mb": int(parts[0]),
            "used_mb": int(parts[1]),
            "free_mb": int(parts[2]),
            "gpu_util_pct": int(parts[3]),
            "ts": time.time(),
        }
    except Exception as e:
        return {"_error": str(e)}


def gpu_sample_durations(duration_sec, interval=0.5):
    """持续采样显存 duration_sec 秒，返回采样列表和峰值"""
    samples = []
    start = time.time()
    while time.time() - start < duration_sec:
        snap = gpu_snapshot()
        if "_error" not in snap:
            samples.append(snap)
        time.sleep(interval)
    if not samples:
        return {"samples": [], "peak_used_mb": 0, "avg_used_mb": 0}
    peak = max(s["used_mb"] for s in samples)
    avg = sum(s["used_mb"] for s in samples) / len(samples)
    return {
        "samples": samples,
        "peak_used_mb": peak,
        "avg_used_mb": round(avg, 1),
        "sample_count": len(samples),
        "duration_sec": round(time.time() - start, 2),
    }


# === GMae API ===
def gmae_health():
    return _http_get(f"{GMAE_BASE}/api/health")


def gmae_status():
    """完整状态，包含 comfyui_models 模型级分解、vram_ledger 账本、gpu_processes 进程级"""
    return _http_get(f"{GMAE_BASE}/api/status", headers=GMAE_HEADERS)


def gmae_vram_ledger():
    """显存账本汇总（从 status 中提取）"""
    s = gmae_status()
    if "_error" in s or not s.get("ok"):
        return s
    return s.get("data", {}).get("vram_ledger", {})


def gmae_comfy_models():
    """ComfyUI 模型级显存分解（从 status 中提取）"""
    s = gmae_status()
    if "_error" in s or not s.get("ok"):
        return s
    return s.get("data", {}).get("comfyui_models", {})


def gmae_scenes():
    return _http_get(f"{GMAE_BASE}/api/scenes", headers=GMAE_HEADERS)


def gmae_switch_scene(scene_name):
    """切换场景，返回 (结果, 耗时秒)。场景名: dialogue/comfyui/fooocus/game/idle/maintenance"""
    start = time.time()
    result = _http_post(f"{GMAE_BASE}/api/scene", {"scene": scene_name},
                        timeout=120, headers=GMAE_HEADERS)
    elapsed = time.time() - start
    return result, round(elapsed, 3)


def gmae_budget(model_name, context_size=2048):
    """查询预算引擎"""
    return _http_get(f"{GMAE_BASE}/api/budget?model={model_name}&context={context_size}",
                     headers=GMAE_HEADERS)


def gmae_auto_protect_status():
    return _http_get(f"{GMAE_BASE}/api/auto-protect/status", headers=GMAE_HEADERS)


def gmae_auto_protect_enable(mode="standard"):
    return _http_post(f"{GMAE_BASE}/api/auto-protect/enable", {"mode": mode},
                      headers=GMAE_HEADERS)


def gmae_auto_protect_disable():
    return _http_post(f"{GMAE_BASE}/api/auto-protect/disable", {},
                      headers=GMAE_HEADERS)


# === ComfyUI API ===
def comfy_system_stats():
    return _http_get(f"{COMFY_BASE}/system_stats")


def comfy_queue_prompt(workflow_json):
    """提交工作流到 ComfyUI，返回 prompt_id"""
    result = _http_post(f"{COMFY_BASE}/prompt", workflow_json, timeout=30)
    return result


def comfy_history(prompt_id):
    return _http_get(f"{COMFY_BASE}/history/{prompt_id}")


def comfy_free():
    """释放 ComfyUI 显存"""
    return _http_post(f"{COMFY_BASE}/free", {"unload_models": True}, timeout=30)


def comfy_wait_for_prompt(prompt_id, timeout=300, poll_interval=2):
    """等待 ComfyUI 工作流完成，返回 (状态, 耗时秒, 输出)"""
    start = time.time()
    while time.time() - start < timeout:
        hist = comfy_history(prompt_id)
        if prompt_id in hist:
            elapsed = time.time() - start
            status = hist[prompt_id].get("status", {})
            return status.get("status_str", "unknown"), round(elapsed, 2), hist[prompt_id]
        time.sleep(poll_interval)
    return "timeout", round(time.time() - start, 2), None


# === Ollama API ===
def ollama_ps():
    return _http_get(f"{OLLAMA_BASE}/api/ps")


def ollama_generate(model, prompt, timeout=120):
    """生成一次回复，返回 (结果, 耗时秒)"""
    start = time.time()
    result = _http_post(f"{OLLAMA_BASE}/api/generate",
                        {"model": model, "prompt": prompt, "stream": False},
                        timeout=timeout)
    elapsed = time.time() - start
    return result, round(elapsed, 2)


def ollama_unload(model):
    """卸载模型（通过 /api/generate 设 keep_alive=0）"""
    return _http_post(f"{OLLAMA_BASE}/api/generate",
                      {"model": model, "prompt": "", "keep_alive": 0},
                      timeout=30)


# === Docker ===
def docker_start(container):
    try:
        subprocess.run(["docker", "start", container], capture_output=True, text=True, timeout=30)
        return True
    except Exception:
        return False


def docker_stop(container):
    try:
        subprocess.run(["docker", "stop", container], capture_output=True, text=True, timeout=30)
        return True
    except Exception:
        return False


def docker_is_running(container):
    try:
        out = subprocess.check_output(["docker", "inspect", "-f", "{{.State.Running}}", container],
                                      text=True, timeout=5).strip()
        return out == "true"
    except Exception:
        return False


# === 结果保存 ===
def save_result(name, data):
    """保存 benchmark 结果到 JSON 文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{RESULTS_DIR}/{name}_{timestamp}.json"
    data["benchmark_name"] = name
    data["timestamp"] = timestamp
    data["gpu_info"] = gpu_snapshot()
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[SAVED] {filename}")
    return filename


def print_header(title):
    print(f"\n{'='*60}")
    print(f"  BENCHMARK: {title}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")


if __name__ == "__main__":
    # 自检
    print("GMae health:", gmae_health())
    print("GPU snapshot:", gpu_snapshot())
