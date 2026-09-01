#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 指挥家显存调度系统 - 入口文件
v2.0 模块化重构：所有业务逻辑已迁移到 core/ services/ gpu/ engine/ api/ 模块
本文件仅负责：导入模块 + 启动服务
"""
import os
import sys
import socket
import time
from http.server import ThreadingHTTPServer

# === 确保 Docker 命令在 PATH 中（Windows Docker Desktop 常见路径）===
_DOCKER_PATHS = [
    r"C:\Program Files\Docker\Docker\resources\bin",
    r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
]
for _dp in _DOCKER_PATHS:
    if os.path.exists(_dp) and _dp not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _dp + os.pathsep + os.environ.get("PATH", "")
        break

# === 模块化导入（v2.0 重构）===
from core.logger import logger, log_event, log_error, log_info, toast_notify, LOG_DIR, LOG_FILE
from core.config import (
    PORT, HOST, BASE_DIR, API_TOKEN, FRONTEND_VERSION, WEB_DIR, LEGACY_HTML,
    REGISTRY_PATH, REGISTRY, OLLAMA_CONTAINER, BIG_MODELS,
    HARDWARE_PROFILE_PATH, get_dyn_thresholds, get_threshold_value,
    GPU_RELEASE_PS1, GAME_ON_PS1, _V031_MODULES
)
from services.helper import (
    HELPER_PORT, HELPER_HOST, CONFIG_FILE, AUTO_PROTECT_MODES,
    helper_status, helper_start, helper_stop,
    desktop_vram_detail, desktop_kill
)
from core.utils import run_args, run_ps1, _safe_model_name, _hardware_info
from services.ollama import ollama_ps, ollama_tags, ollama_stop_all, ollama_stop
from services.comfy import comfy_system_stats, comfy_queue, comfy_free, comfy_loaded_models
from services.docker import (docker_containers, infer_scene, docker_action,
    _container_has_gpu, container_stop, _container_gpu_mb, wait_ready, free_all)
from gpu.monitor import (gpu_status, _container_pids, _gpu_app_pids,
    desktop_gpu_processes, gpu_processes, _update_process_lifecycle, _find_pid_container,
    _proc_lifecycle, _proc_events)
from gpu.process_guard import gpu_guard_kick, PROTECT_COMMS
from engine.reaper import service_activity, start_idle_reaper
from engine.qos import (qos_check, qos_status, qos_execute_suggestion, start_qos,
    auto_protect_status, auto_protect_config, QOS_CFG)
from services.comfy_ws import ComfyWS, comfy_events, start_comfy_ws, _COMFY_EVENTS, _COMFY_EVENTS_LOCK
from engine.budget import budget_engine, vram_advice
from engine.eviction_guard import gpu_guard_check, gpu_guard_evict, GUARD_UNKNOWN_POLICY, GUARD_WARN_THRESHOLD
from engine.scanner import model_scan, scan_register, start_auto_scanner
from engine.queue import queue_enqueue, queue_snapshot, queue_cancel
from services.scene import (scene_switch, combo_switch, service_action, model_action,
    load_model_api, ollama_stop, _sync_ollama_models, _sync_comfyui_models)
from services.status import current_status, comfy_loaded_models, invalidate_status_cache
from api.routes import Handler

# 兼容旧代码引用
_get_threshold_value = get_threshold_value
_dyn_thresholds = get_dyn_thresholds()

# 认证模块
from api import auth as auth_mod

# v0.3.1 模块
try:
    from core import hardware_probe
    from core import thresholds as thresholds_mod
    from engine import admission_gate
except ImportError as _e:
    log_error("v031_modules_import_failed_server", error=_e)


if __name__ == "__main__":
    try:
        # 防多实例：启动前探测端口，已被占用则直接退出
        try:
            _probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _probe.settimeout(1)
            _occupied = _probe.connect_ex(("127.0.0.1", PORT)) == 0
            _probe.close()
        except Exception:
            _occupied = False
        if _occupied:
            log_event("server_start_blocked", reason="port_already_in_use", host=HOST, port=PORT)
            raise SystemExit(0)

        server = ThreadingHTTPServer((HOST, PORT), Handler)

        # 启动后台线程
        start_idle_reaper()      # 后台空闲回收线程
        start_comfy_ws()         # ComfyUI WebSocket 实时事件监听
        start_qos()              # QoS 水位节拍线程
        start_auto_scanner()     # 自动扫描器（新模型自动登记）
        from observability.health_probe import health_probe
        health_probe.start()     # v2.0 服务健康探测引擎

        auth_note = "session+token" if auth_mod.has_admin() else "setup-required"
        log_event("server_start", host=HOST, port=PORT, auth=auth_note, log_file=LOG_FILE,
                  admin_exists=auth_mod.has_admin(), smtp_configured=bool(auth_mod.SMTP_PASSWORD))
        if not auth_mod.has_admin():
            log_event("auth_setup_required", message="no admin account set - please visit / to setup first admin")

        server.serve_forever()
    except KeyboardInterrupt:
        log_event("server_stop", reason="keyboard_interrupt")
    except Exception as e:
        log_error("server_crash", error=e)
        raise
