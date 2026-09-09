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
import threading
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
    PORT, HOST, BASE_DIR, API_TOKEN, FRONTEND_VERSION, WEB_DIR,
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
from engine.alert_manager import alert_manager
from services.comfy_ws import ComfyWS, comfy_events, start_comfy_ws, _COMFY_EVENTS, _COMFY_EVENTS_LOCK
from engine.budget import budget_engine, vram_advice
from engine.eviction_guard import gpu_guard_check, gpu_guard_evict, GUARD_UNKNOWN_POLICY, GUARD_WARN_THRESHOLD
from engine.scanner import model_scan, scan_register, start_auto_scanner
from engine.queue import queue_enqueue, queue_snapshot, queue_cancel
from services.scene import (scene_switch, combo_switch, service_action, model_action,
    load_model_api, ollama_stop, _sync_ollama_models, _sync_comfyui_models)
from services.status import current_status, comfy_loaded_models, invalidate_status_cache
from core.status_cache import status_cache
from core.docker_events import docker_events
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

        # S3.5: 告警升级检查线程（每 60 秒检查持续未解决的告警并自动升级）
        def _alert_escalation_loop():
            while True:
                try:
                    alert_manager.check_escalation()
                except Exception as e:
                    log_error("exception_suppressed", error=e, context="server.py:108")
                time.sleep(60)
        _alert_esc_thread = threading.Thread(target=_alert_escalation_loop, daemon=True, name="alert-escalation")
        _alert_esc_thread.start()

        # S3.6: 门卫告警同步线程（每 30 秒把门卫检查结果同步到 AlertManager）
        def _guard_alert_sync_loop():
            from engine.eviction_guard import gpu_guard_check
            _guard_types = {
                "scene_conflict": ("Fooocus", "ComfyUI"),
                "unknown_gpu_process": ("未登记 GPU 进程",),
                "vram_discrepancy": ("显存差量",),
            }
            _guard_msgs = {
                "scene_conflict": "Fooocus 与 ComfyUI 同跑 = 显存叠加风险",
                "unknown_gpu_process": "存在未登记 GPU 进程，白占显存",
                "vram_discrepancy": "显存差量异常，可能有进程偷占显存",
            }
            while True:
                try:
                    guard = gpu_guard_check()
                    alerts = guard.get("alerts", []) or []
                    current = set()
                    for atype, keywords in _guard_types.items():
                        if any(any(kw in a for kw in keywords) for a in alerts):
                            current.add(atype)
                    active = {a["alert_type"] for a in alert_manager.get_active()}
                    for atype in current - active:
                        alert_manager.submit(atype, "warning", _guard_msgs[atype], {"source": "guard"})
                    for atype in (set(_guard_types) & active) - current:
                        alert_manager.resolve(atype)
                except Exception as e:
                    log_error("exception_suppressed", error=e, context="server.py:guard_sync")
                time.sleep(30)
        _guard_sync_thread = threading.Thread(target=_guard_alert_sync_loop, daemon=True, name="guard-alert-sync")
        _guard_sync_thread.start()

        # S6: 被暂停容器自动恢复线程（每60秒检查，显存宽松时自动恢复）
        def _paused_recover_loop():
            while True:
                try:
                    from services.docker import get_paused_containers, container_unpause
                    from gpu.monitor import gpu_status
                    paused = get_paused_containers()
                    if paused:
                        gpu = gpu_status()
                        free_mb = gpu.get("free_mb", 0)
                        # 显存空闲 > 8G 时，自动恢复被暂停的容器（按暂停时间顺序，先暂停的先恢复）
                        if free_mb > 8192:
                            for pname in sorted(paused.keys(), key=lambda k: paused[k]):
                                r = container_unpause(pname)
                                if r.get("ok"):
                                    log_event("paused_auto_recover", container=pname,
                                              free_before=free_mb, reason="vram free > 8G")
                                    break  # 每次只恢复一个，避免瞬间占满
                except Exception as e:
                    log_error("exception_suppressed", error=e, context="server.py:paused_recover")
                time.sleep(60)
        _paused_recover_thread = threading.Thread(target=_paused_recover_loop, daemon=True, name="paused-recover")
        _paused_recover_thread.start()

        # S1.2 Docker Events 监听：容器状态变化时失效缓存 + 宕机告警
        def _on_container_state_change(name, action):
            status_cache.invalidate()
            try:
                if action in ("die", "kill", "destroy"):
                    alert_manager.submit("container_down", "danger",
                        f"容器 {name} 异常退出（{action}）",
                        {"container": name, "action": action})
                elif action in ("start", "restart"):
                    alert_manager.resolve("container_down")
            except Exception as e:
                log_error("exception_suppressed", error=e, context="server.py:container_alert")
        docker_events.on_state_change = _on_container_state_change
        _docker_events_ok = docker_events.start()
        log_event("docker_events_started", available=_docker_events_ok)

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
    finally:
        # 优雅停止 Docker Events 监听
        try:
            docker_events.stop()
        except Exception as e:
            log_error("exception_suppressed", error=e, context="server.py:135")
