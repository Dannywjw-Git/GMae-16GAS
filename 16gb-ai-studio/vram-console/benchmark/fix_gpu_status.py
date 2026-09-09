"""修复 gpu_status：nvidia-smi 失败时回退到上次成功值（stale 模式）"""
import io

path = r"D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console\gpu\monitor.py"

# 读取原始内容（保持 BOM）
with open(path, "rb") as f:
    raw = f.read()

# 检测 BOM
has_bom = raw.startswith(b"\xef\xbb\xbf")
content = raw.decode("utf-8-sig")
# 统一换行符为 \n 进行匹配，写回时恢复原始
original_newline = "\r\n" if "\r\n" in content else "\n"
content_norm = content.replace("\r\n", "\n")

# 旧的 gpu_status 缓存部分
old_block = '''# === nvidia-smi 缓存（S1.4）===
# 5 秒 TTL，危险状态（free_mb < 2048MB）时缩短为 2 秒
_gpu_status_cache = {"data": None, "timestamp": 0}
_gpu_status_lock = threading.Lock()
_GPU_STATUS_TTL = 5.0  # 秒（正常状态）
_GPU_STATUS_DANGER_TTL = 2.0  # 秒（危险状态，free_mb < 阈值）
_GPU_STATUS_DANGER_FREE_MB = 2048  # free_mb 低于此值视为危险状态


def gpu_status(force_refresh: bool = False) -> dict:
    """查询 GPU 显存状态，带 5 秒 TTL 缓存（S1.4）。

    危险状态（free_mb < 2048MB）时 TTL 缩短为 2 秒，确保危险时数据更实时。
    force_refresh=True 时跳过缓存，强制执行 nvidia-smi 查询。

    Returns:
        dict: {"ok": bool, "total_mb": int, "used_mb": int, "free_mb": int, "utilization": int}
    """
    global _gpu_status_cache
    with _gpu_status_lock:
        now = time.time()
        if not force_refresh and _gpu_status_cache["data"] is not None:
            data = _gpu_status_cache["data"]
            # 根据 free_mb 判断危险状态，决定 TTL
            if data.get("ok") and data.get("free_mb", 99999) < _GPU_STATUS_DANGER_FREE_MB:
                ttl = _GPU_STATUS_DANGER_TTL
            else:
                ttl = _GPU_STATUS_TTL
            if now - _gpu_status_cache["timestamp"] < ttl:
                return data
        # 执行 nvidia-smi 查询（原有逻辑）
        data = query_gpu_memory()
        _gpu_status_cache["data"] = data
        _gpu_status_cache["timestamp"] = now
        return data'''

new_block = '''# === nvidia-smi 缓存（S1.4）===
# 5 秒 TTL，危险状态（free_mb < 2048MB）时缩短为 2 秒
_gpu_status_cache = {"data": None, "timestamp": 0}
_gpu_status_lock = threading.Lock()
_GPU_STATUS_TTL = 5.0  # 秒（正常状态）
_GPU_STATUS_DANGER_TTL = 2.0  # 秒（危险状态，free_mb < 阈值）
_GPU_STATUS_DANGER_FREE_MB = 2048  # free_mb 低于此值视为危险状态
# 上次成功查询的持久缓存（nvidia-smi 超时时回退使用，避免 auto_protect 被跳过）
_last_good_gpu_status = None


def gpu_status(force_refresh: bool = False) -> dict:
    """查询 GPU 显存状态，带 5 秒 TTL 缓存（S1.4）。

    危险状态（free_mb < 2048MB）时 TTL 缩短为 2 秒，确保危险时数据更实时。
    force_refresh=True 时跳过缓存，强制执行 nvidia-smi 查询。

    容错：nvidia-smi 超时/失败时，回退到上次成功值并标记 stale=True，
    确保 qos_check/auto_protect 在高显存压力下仍能触发（安全机制宁可信其有）。

    Returns:
        dict: {"ok": bool, "total_mb": int, "used_mb": int, "free_mb": int,
               "utilization": int, "stale": bool(可选), "stale_age_s": float(可选)}
    """
    global _gpu_status_cache, _last_good_gpu_status
    with _gpu_status_lock:
        now = time.time()
        if not force_refresh and _gpu_status_cache["data"] is not None:
            data = _gpu_status_cache["data"]
            # 根据 free_mb 判断危险状态，决定 TTL
            if data.get("ok") and data.get("free_mb", 99999) < _GPU_STATUS_DANGER_FREE_MB:
                ttl = _GPU_STATUS_DANGER_TTL
            else:
                ttl = _GPU_STATUS_TTL
            if now - _gpu_status_cache["timestamp"] < ttl:
                return data
        # 执行 nvidia-smi 查询
        data = query_gpu_memory()
        if data.get("ok"):
            # 查询成功：更新持久缓存
            _last_good_gpu_status = dict(data)
            _last_good_gpu_status["stale"] = False
            _gpu_status_cache["good_timestamp"] = now
        elif _last_good_gpu_status is not None:
            # 查询失败但有上次成功值：回退到 stale 数据（安全优先）
            good_ts = _gpu_status_cache.get("good_timestamp", now)
            stale_age = now - good_ts
            data = dict(_last_good_gpu_status)
            data["stale"] = True
            data["stale_age_s"] = round(stale_age, 1)
            data["error"] = "nvidia-smi failed, using last known good value"
            log_error("gpu_status_stale_fallback", stale_age_s=stale_age,
                      free_mb=data.get("free_mb"), used_mb=data.get("used_mb"))
        _gpu_status_cache["data"] = data
        _gpu_status_cache["timestamp"] = now
        return data'''

if old_block in content_norm:
    content_norm = content_norm.replace(old_block, new_block)
    # 恢复原始换行符
    content_out = content_norm.replace("\n", original_newline)
    # 写回（保持 BOM）
    out = content_out.encode("utf-8-sig") if has_bom else content_out.encode("utf-8")
    with open(path, "wb") as f:
        f.write(out)
    print("OK: gpu_status patched with stale fallback")
else:
    print("ERROR: old block not found")
    idx = content_norm.find("_gpu_status_cache")
    print(repr(content_norm[idx:idx+200]))
