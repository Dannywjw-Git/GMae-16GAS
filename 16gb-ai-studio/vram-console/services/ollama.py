#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae Ollama 服务模块
- 模型列表/已加载模型查询
- 批量停止模型
"""
from core.logger import log_event, log_error
from core.config import BIG_MODELS, OLLAMA_CONTAINER
from core.utils import _safe_model_name
from clients.ollama_client import list_loaded_models, list_installed_models
from clients.docker_client import exec_command


def ollama_ps() -> dict:
    """查询 Ollama 已加载模型。"""
    return list_loaded_models()


def ollama_tags() -> set:
    """获取已安装的 Ollama 模型列表，返回 set(name)。"""
    return list_installed_models()


def ollama_stop_all() -> tuple:
    """停止所有已加载的 ollama 模型。"""
    loaded = set()
    result = list_loaded_models()
    if result.get("ok"):
        for m in result.get("models", []):
            loaded.add(m.get("name", ""))
    targets = loaded | set(BIG_MODELS)
    bad = []
    outs = []
    for m in targets:
        if not m:
            continue
        rc, out = exec_command(OLLAMA_CONTAINER, ["ollama", "stop", m], 60)
        outs.append("{}:rc{}".format(m, rc))
        if rc != 0:
            bad.append(m)
    return (0 if not bad else 1), " | ".join(outs) + ("" if not bad else "  FAILED: " + ",".join(bad))


def ollama_stop(names: list) -> tuple:
    """逐个停止指定的 Ollama 模型（带模型名安全校验）。"""
    bad = []
    outs = []
    for n in names:
        ok, checked = _safe_model_name(n)
        if not ok:
            bad.append(n)
            outs.append("{}:SKIP({})".format(n, checked))
            continue
        rc, out = exec_command(OLLAMA_CONTAINER, ["ollama", "stop", checked], 60)
        outs.append("{}:rc{}".format(checked, rc))
        if rc != 0:
            bad.append(checked)
    return (0 if not bad else 1), " | ".join(outs) + ("" if not bad else "  FAILED: " + ",".join(bad))
