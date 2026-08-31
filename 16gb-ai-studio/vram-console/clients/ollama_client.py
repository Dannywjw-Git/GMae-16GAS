#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae Ollama API 客户端
- 封装所有 Ollama HTTP API 调用
- 提供模型列表、已加载模型、停止模型等接口
- 所有调用统一超时和错误处理
"""
import json
import urllib.request
from core.logger import log_error

OLLAMA_BASE = "http://127.0.0.1:11434"


def _get(path: str, timeout: int = 5) -> tuple:
    """发送 GET 请求到 Ollama API。

    Args:
        path: API 路径（如 /api/ps）
        timeout: 超时秒数

    Returns:
        tuple: (ok: bool, data: dict, error: str)
    """
    try:
        with urllib.request.urlopen(OLLAMA_BASE + path, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return True, data, ""
    except Exception as e:
        return False, {}, str(e)


def list_loaded_models() -> dict:
    """查询 Ollama 已加载模型（/api/ps）。

    Returns:
        dict: {"ok": bool, "models": [{"name": str, "size_gb": float, "until": str}]}
    """
    ok, d, err = _get("/api/ps", timeout=3)
    if not ok:
        return {"ok": False, "models": [], "error": "offline/timeout"}
    models = [{
        "name": m.get("name", ""),
        "size_gb": round(m.get("size", 0) / 1e9, 1),
        "until": (m.get("expires_at") or "")[11:19],
    } for m in d.get("models", [])]
    return {"ok": True, "models": models}


def list_installed_models() -> set:
    """获取已安装的 Ollama 模型名称集合（/api/tags）。

    Returns:
        set: 模型名称集合，失败返回空 set
    """
    ok, d, err = _get("/api/tags", timeout=5)
    if not ok:
        return set()
    return {m.get("name", "") for m in d.get("models", [])}


def is_online() -> bool:
    """检查 Ollama 服务是否在线。

    Returns:
        bool: 在线返回 True
    """
    ok, _, _ = _get("/api/tags", timeout=3)
    return ok
