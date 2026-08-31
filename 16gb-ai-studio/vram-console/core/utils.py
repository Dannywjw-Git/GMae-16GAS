#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 核心工具模块
- 安全命令执行（run_args / run_ps1）
- 模型名校验（_safe_model_name）
- 硬件信息（_hardware_info）
"""
import json
import os
import re
import subprocess
from core.logger import log_error
from core.config import (
    _V031_MODULES, HARDWARE_PROFILE_PATH, get_dyn_thresholds,
    get_threshold_value, REGISTRY
)

# 兼容旧引用
_get_threshold_value = get_threshold_value
_dyn_thresholds = get_dyn_thresholds()

# Ollama 模型名安全格式
_MODEL_NAME_RE = re.compile(r'^[A-Za-z0-9._:/\-]+$')


def _safe_model_name(name: str) -> tuple:
    """校验模型名是否安全，返回 (ok, name_or_error)。"""
    if not name or not isinstance(name, str):
        return False, "empty model name"
    if len(name) > 128:
        return False, "model name too long"
    if ".." in name:
        return False, "invalid model name (path traversal '..' not allowed)"
    if name.startswith("/") or name.startswith("\\"):
        return False, "invalid model name (absolute path not allowed)"
    if not _MODEL_NAME_RE.match(name):
        return False, "invalid model name (only letters, digits, . : / - allowed)"
    return True, name


def run_args(args: list, timeout: int = 30) -> tuple:
    """安全执行命令（shell=False + 参数数组）。"""
    try:
        p = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -2, str(e)


def run_ps1(path: str, timeout: int = 120) -> tuple:
    """执行 PowerShell 脚本。"""
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
            shell=False, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -2, str(e)


def _hardware_info() -> dict:
    """返回硬件配置 + 动态阈值（前端展示用）。"""
    info = {"ok": True, "v031_modules": _V031_MODULES}
    th = get_dyn_thresholds()
    if th is not None:
        info["thresholds"] = th.to_dict()
    else:
        info["thresholds"] = None
    try:
        with open(HARDWARE_PROFILE_PATH, "r", encoding="utf-8") as f:
            info["profile"] = json.load(f)
    except Exception:
        info["profile"] = None
    return info
