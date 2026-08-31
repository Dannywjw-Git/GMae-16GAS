#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae ComfyUI API 客户端
- 封装所有 ComfyUI HTTP API 调用
- 提供系统状态、队列、显存释放等接口
- 所有调用统一超时和错误处理
"""
import json
import urllib.request
from core.logger import log_error

COMFY_BASE = "http://127.0.0.1:8188"


def _get(path: str, timeout: int = 5) -> tuple:
    """发送 GET 请求到 ComfyUI API。

    Args:
        path: API 路径（如 /system_stats）
        timeout: 超时秒数

    Returns:
        tuple: (ok: bool, data: dict, error: str)
    """
    try:
        with urllib.request.urlopen(COMFY_BASE + path, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return True, data, ""
    except Exception as e:
        return False, {}, str(e)


def _post(path: str, body: dict, timeout: int = 30) -> tuple:
    """发送 POST 请求到 ComfyUI API。

    Args:
        path: API 路径
        body: 请求体 dict
        timeout: 超时秒数

    Returns:
        tuple: (ok: bool, http_code: int, error: str)
    """
    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            COMFY_BASE + path, data=data,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.getcode(), ""
    except Exception as e:
        return False, 0, str(e)


def system_stats() -> dict:
    """ComfyUI /system_stats：设备级显存实测（容器内服务自报，torch 视角）。

    Returns:
        dict: {"ok": bool, "device": str, "vram_total_mb": int, "vram_free_mb": int,
               "torch_vram_used_mb": int}
    """
    ok, d, err = _get("/system_stats", timeout=5)
    if not ok:
        return {"ok": False, "error": err}
    dev = (d.get("devices") or [{}])[0]
    torch_total = dev.get("torch_vram_total") or 0
    torch_free = dev.get("torch_vram_free") or 0
    return {
        "ok": True,
        "device": dev.get("name", ""),
        "vram_total_mb": (dev.get("vram_total") or 0) // 1024 // 1024,
        "vram_free_mb": (dev.get("vram_free") or 0) // 1024 // 1024,
        "torch_vram_used_mb": max(0, (torch_total - torch_free)) // 1024 // 1024,
    }


def queue_status() -> dict:
    """ComfyUI /queue：正在跑 / 排队任务。

    Returns:
        dict: {"ok": bool, "running": [...], "pending": [...]}
    """
    ok, d, err = _get("/queue", timeout=5)
    if not ok:
        return {"ok": False, "error": err}

    def brief(items):
        out = []
        for it in (items or []):
            if not isinstance(it, (list, tuple)) or not it:
                continue
            nodes = next((x for x in it if isinstance(x, dict)), None)
            cls = ""
            if nodes:
                for _k, v in nodes.items():
                    if isinstance(v, dict) and v.get("class_type"):
                        cls = v["class_type"]
                        break
            pid = it[1] if len(it) > 1 and isinstance(it[1], str) else (it[0] if it else "")
            out.append({"prompt_id": str(pid)[:8], "node": cls})
        return out

    return {
        "ok": True,
        "running": brief(d.get("queue_running")),
        "pending": brief(d.get("queue_pending")),
    }


def free_memory(unload_models: bool = True, free_memory: bool = True) -> dict:
    """调用 ComfyUI /free 端点，卸载模型 + 释放显存缓存。

    Args:
        unload_models: 是否卸载模型
        free_memory: 是否释放显存缓存

    Returns:
        dict: {"ok": bool, "http": int, "error": str}
    """
    ok, http_code, err = _post("/free", {
        "unload_models": unload_models,
        "free_memory": free_memory,
    }, timeout=30)
    if not ok:
        return {"ok": False, "error": "ComfyUI /free 调用失败: " + err}
    return {"ok": True, "http": http_code}


def is_online() -> bool:
    """检查 ComfyUI 服务是否在线。

    Returns:
        bool: 在线返回 True
    """
    ok, _, _ = _get("/system_stats", timeout=3)
    return ok
