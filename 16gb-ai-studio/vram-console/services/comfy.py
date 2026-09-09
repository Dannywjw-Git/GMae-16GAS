#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae ComfyUI 服务模块
- 系统状态/队列/已加载模型查询
- 显存释放（/free 端点）
"""
import time
from core.logger import log_event, log_error
from clients.comfyui_client import system_stats, queue_status, free_memory, history
from clients.docker_client import is_running
from core.utils import run_args


def comfy_system_stats() -> dict:
    """ComfyUI /system_stats：设备级显存实测（容器内服务自报，torch 视角）。"""
    return system_stats()


def comfy_queue() -> dict:
    """ComfyUI /queue：正在跑 / 排队任务。"""
    return queue_status()


def comfy_free() -> dict:
    """调用 ComfyUI 官方 /free 端点，卸载模型 + 释放显存缓存。"""
    from gpu.monitor import gpu_status

    if not is_running("comfyui"):
        return {"ok": False, "error": "comfyui 容器未运行，无需释放"}
    before = gpu_status()
    result = free_memory(unload_models=True, free_memory=True)
    if not result.get("ok"):
        log_error("comfy_free_failed", error=result.get("error"))
        return result
    time.sleep(1)
    after = gpu_status()
    log_event("comfy_free", http=result.get("http"),
              vram_free_before=before.get("free_mb"), vram_free_after=after.get("free_mb"))
    return {
        "ok": True, "http": result.get("http"),
        "free_mb_before": before.get("free_mb"),
        "free_mb_after": after.get("free_mb"),
        "freed_mb": max(0, after.get("free_mb", 0) - before.get("free_mb", 0)),
    }


def comfy_loaded_models() -> dict:
    """ComfyUI 已加载模型列表（从 /history 最近工作流解析）。

    原理：ComfyUI 没有直接的"已加载模型"API，但模型在执行工作流后会
    保留在显存中（取决于设置）。通过解析最近的 /history 工作流，提取
    使用的 Checkpoint/LoRA/VAE 等模型，作为"可能已加载"的模型列表。
    """
    from clients.comfyui_client import history
    if not is_running("comfyui"):
        return {"ok": False, "models": [], "error": "comfyui not running"}
    hist = history(max_items=3)
    if not hist.get("ok"):
        return {"ok": False, "models": [], "error": hist.get("error")}
    # 合并最近工作流使用的所有模型
    all_models = []
    for item in hist.get("items", []):
        for m in item.get("models", []):
            if m not in all_models:
                all_models.append(m)
    return {"ok": True, "models": all_models, "count": len(all_models),
            "source": "history_inference", "note": "从最近工作流推断，非实时已加载状态"}

# ===== ComfyUI 模型级显存分解 =====
# torch 只暴露进程级总显存；以 torch 实测为锚点（守恒），用最近工作流(/history)确定
# 加载了哪些模型，再按容器内模型文件大小估算各模型显存，差额记为框架/CUDA/缓存开销。
_COMFY_CONTAINER = "comfyui"
_COMFY_MODELS_DIR = "/opt/ComfyUI/models"
_file_index_cache = {"ts": 0.0, "index": {}}
_FILE_INDEX_TTL = 60.0


def _comfy_file_index() -> dict:
    """{模型相对路径/小写basename: 字节}，TTL 缓存；容器内 stat 读取，跨机器通用。"""
    now = time.time()
    idx = _file_index_cache["index"]
    if idx and now - _file_index_cache["ts"] < _FILE_INDEX_TTL:
        return idx
    # models 目录在镜像中常是符号链接（-> /workspace/models），先 readlink 解析真实路径；
    # find -printf 输出“字节 相对路径”；走 subprocess 参数数组，不经 shell/PowerShell 转义。
    _script = 'D=$(readlink -f "{0}"); find "$D" -type f -printf "%s %P\n"'.format(_COMFY_MODELS_DIR)
    rc, out = run_args(["docker", "exec", _COMFY_CONTAINER, "sh", "-c", _script], 25)
    new_idx = {}
    if rc == 0:
        for line in (out or "").splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            try:
                size = int(parts[0])
            except ValueError:
                continue
            rel = parts[1].strip().replace("\\", "/")
            new_idx[rel] = size
            new_idx[rel.split("/")[-1].lower()] = size
    _file_index_cache["ts"] = now
    _file_index_cache["index"] = new_idx
    return new_idx


def _match_model_size(name: str, idx: dict) -> int:
    """模型名（可带子目录）-> 字节；先相对路径精确，再 basename 兜底。"""
    if not name:
        return 0
    key = name.replace("\\", "/")
    if key in idx:
        return idx[key]
    return idx.get(key.split("/")[-1].lower(), 0)


def comfy_model_breakdown(max_items: int = 5) -> dict:
    """ComfyUI 显存按模型分解；恒有 model_total_mb + overhead_mb = torch_used_mb。"""
    stats = comfy_system_stats()
    torch_used = int(stats.get("torch_vram_used_mb", 0) or 0)
    result = {"ok": bool(stats.get("ok")), "torch_used_mb": torch_used,
              "models": [], "model_total_mb": 0, "overhead_mb": torch_used,
              "source": "torch+history+filesize"}
    if not is_running(_COMFY_CONTAINER) or not stats.get("ok"):
        return result
    hist = history(max_items=max_items)
    idx = _comfy_file_index()
    seen = set()
    for item in hist.get("items", []):
        kinds = item.get("model_kinds", {})
        for name in item.get("models", []):
            if name in seen:
                continue
            seen.add(name)
            size_mb = _match_model_size(name, idx) // 1024 // 1024
            if size_mb <= 0:
                continue  # 容器内找不到该模型文件（索引失败/路径不符），无法估算则跳过
            result["models"].append({"name": name, "kind": kinds.get(name, "model"),
                                     "size_mb": size_mb})
    model_total = sum(m["size_mb"] for m in result["models"])
    # 以 torch 实测为硬上限校准：/history 只表示“最近用过”，容器重启或切换工作流后
    # 旧模型可能已不在显存。若模型文件合计明显超过 torch 实测占用，判定当前无活跃模型，
    # 回退为单行框架占用，避免虚报显存。
    RESIDENT_TOL_MB = 300
    if model_total > torch_used + RESIDENT_TOL_MB:
        result["models"] = []
        result["model_total_mb"] = 0
        result["overhead_mb"] = torch_used
        result["resident"] = False
    else:
        result["model_total_mb"] = model_total
        result["overhead_mb"] = max(0, torch_used - model_total)
        result["resident"] = model_total > 0
    return result

