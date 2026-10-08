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
    journal, command_id, coordinator, token = None, None, None, None
    try:
        from core.registry import registry
        coordinator = registry.get('resource_coordinator')
        journal = registry.get('operation_journal')
        token = coordinator.current_token() if coordinator is not None else None
        active = coordinator.snapshot()['active'] if token else None
        executable = os.path.basename(str(args[0])).lower() if args else ''
        read_only = (executable in ('nvidia-smi', 'nvidia-smi.exe') and
                     any(str(arg).startswith('--query-') for arg in args[1:]) and
                     all(str(arg).startswith(('--query-', '--format=')) for arg in args[1:])) or (
            executable in ('docker', 'docker.exe') and len(args) > 1 and
            args[1] in ('ps', 'inspect', 'stats', 'version', 'info', 'events'))
        tracked = active and active.get('journal_id') and active['phase'] in ('running', 'releasing', 'stopping') and not read_only
        if journal is not None and tracked:
            command_id = journal.command_begin(active['journal_id'], args)
        p = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        if command_id:
            journal.command_finish(command_id, p.returncode)
            if p.returncode != 0:
                coordinator.transition(token, 'uncertain', {
                    'reason': '资源命令非成功返回，后端执行需核验', 'command_id': command_id})
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        if command_id:
            coordinator.transition(token, 'uncertain', {'reason': '命令超时，不能推断后端已结束', 'command_id': command_id})
            try:
                journal.command_finish(command_id, -1)
            except Exception:
                pass  # The durable inflight receipt still blocks recovery.
        return -1, "TIMEOUT"
    except Exception as e:
        if command_id:
            coordinator.transition(token, 'uncertain', {'reason': '命令执行或结束记录不可用', 'command_id': command_id})
        return -2, str(e)


def run_ps1(path: str, timeout: int = 120) -> tuple:
    """执行 PowerShell 脚本。"""
    return run_args(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path], timeout)


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
