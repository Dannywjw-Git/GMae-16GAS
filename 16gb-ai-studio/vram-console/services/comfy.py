#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae ComfyUI 服务模块
- 系统状态/队列/已加载模型查询
- 显存释放（/free 端点）
"""
import time
from core.logger import log_event, log_error
from clients.comfyui_client import system_stats, queue_status, free_memory
from clients.docker_client import is_running


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
    """ComfyUI 已加载模型列表（从 /system_stats 解析）。"""
    stats = comfy_system_stats()
    if not stats.get("ok"):
        return {"ok": False, "models": [], "error": stats.get("error")}
    # ComfyUI /system_stats 没有直接的已加载模型列表，这里返回空
    # 实际实现需要从 ComfyUI 内部 API 获取，暂用占位
    return {"ok": True, "models": []}
