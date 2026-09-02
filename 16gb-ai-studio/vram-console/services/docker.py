#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae Docker 容器管理模块
- 容器列表/场景推断
- 容器启停/GPU挂载检测
- 一键释放（free_all）
"""
import json
import re
import time
import urllib.request
from core.logger import log_event, log_error
from core.config import REGISTRY
from clients.docker_client import (list_running_containers, container_action,
                                    inspect_container, stop_container)


def docker_containers() -> list:
    """获取运行中的 Docker 容器名称列表。

    优先从 Docker Events 内存表获取（S1.2，零延迟），
    不可用或未初始化时回退到 docker ps 命令。
    """
    # 延迟导入，避免模块加载时的循环依赖
    from core.docker_events import docker_events
    if docker_events.is_available():
        states = docker_events.get_all_states()
        if states:  # events 表已初始化（有容器记录，不管 running/exited）
            return [name for name, state in states.items() if state == "running"]
    # 回退：docker ps
    return list(list_running_containers())


def infer_scene(containers: list) -> str:
    """根据运行中的容器推断当前场景。"""
    if "fooocus" in containers:
        return "fooocus"
    if "comfyui" in containers:
        return "comfy"
    return "dialogue"


def docker_action(name: str, action: str) -> tuple:
    """启停 Docker 容器，白名单校验。"""
    if name not in ("comfyui", "fooocus"):
        return -1, "unsupported container: " + str(name)
    if action not in ("start", "stop", "restart"):
        return -1, "unsupported action: " + str(action)
    return container_action(name, action, 60)


def _container_has_gpu(name):
    """检查 Docker 容器是否挂载了 GPU。"""
    try:
        rc, out = inspect_container(name, "{{json .HostConfig.DeviceRequests}}", 10)
        if rc != 0 or not out.strip():
            return False
        data = json.loads(out)
        if not data:
            return False
        for req in data:
            for cap_list in req.get("Capabilities", []):
                if "gpu" in [c.lower() for c in cap_list]:
                    return True
        return False
    except Exception:
        return False


def container_stop(name: str) -> dict:
    """停止指定 Docker 容器。"""
    if not name or not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$', name):
        return {"ok": False, "error": "invalid container name: " + str(name)}
    if name not in docker_containers():
        return {"ok": False, "error": "container not running: " + name}
    ok, msg = stop_container(name, 60)
    log_event("container_stop", name=name, ok=ok, message=msg[-200:])
    return {"ok": ok, "name": name, "message": msg[-200:]}


def _container_gpu_mb(name):
    """估算指定容器的 GPU 显存占用。"""
    if name == "ollama":
        try:
            from services.ollama import ollama_ps
            models = ollama_ps().get("models", [])
            return sum(int(float(m.get("size_gb", 0)) * 1024) for m in models)
        except Exception:
            return 0
    if name == "comfyui":
        try:
            from services.comfy import comfy_system_stats
            return comfy_system_stats().get("torch_vram_used_mb") or 0
        except Exception:
            return 0
    return 0


def wait_ready(port, timeout=90):
    """轮询容器 HTTP 端口就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:{}/".format(port), timeout=2):
                return True, int(timeout - (deadline - time.time()))
        except Exception:
            time.sleep(2)
    return False, timeout


def free_all() -> dict:
    """一键释放：遍历 registry gpu_guard.managed 列表，按 evict 方式释放。
    返回格式兼容前端 showFreeResult：{freed_mb, free_mb_before, free_mb_after,
    stopped, running, success_count, total_count, actions}"""
    from gpu.monitor import gpu_status, gpu_processes
    from services.ollama import ollama_ps, ollama_stop
    from services.comfy import comfy_free
    from core.registry import registry
    from core.status_cache import status_cache

    before = gpu_status()
    actions = []
    stopped = []
    guard = REGISTRY.get("gpu_guard", {})
    managed = guard.get("managed", [])
    containers = docker_containers()
    # 受保护的进程（不显示在 running 中或标记为受保护）
    protect_comms = guard.get("PROTECT_COMMS", []) or guard.get("protect_comms", [])
    for item in managed:
        name = item.get("name", "")
        evict = item.get("evict", "")
        if not name or name not in containers:
            continue
        if evict == "stop models" and name == "ollama":
            # 逐个停止已加载的模型，并循环验证确保真正停止（防止 ollama keepalive 重新加载）
            ps_result = ollama_ps()
            loaded_models = []
            if ps_result.get("ok"):
                loaded_models = [m.get("name", "") for m in ps_result.get("models", []) if m.get("name")]
            if loaded_models:
                for model_name in loaded_models:
                    # 第一次停止
                    rc, out = ollama_stop([model_name])
                    ok = rc == 0
                    # 循环验证：最多重试3次，确保模型真正停止
                    for attempt in range(3):
                        time.sleep(2)  # 等待2秒让模型卸载
                        verify_ps = ollama_ps()
                        verify_models = [m.get("name", "") for m in verify_ps.get("models", []) if m.get("name")]
                        if model_name not in verify_models:
                            break  # 模型已停止，跳出循环
                        # 模型还在，再次停止
                        rc2, out2 = ollama_stop([model_name])
                        if rc2 == 0:
                            out = out2  # 更新输出
                    actions.append({
                        "name": "ollama: " + model_name,
                        "action": "stop model",
                        "ok": ok,
                        "output": out[-200:],
                    })
                    if ok:
                        stopped.append({"name": "ollama: " + model_name, "method": "stop_model"})
            else:
                # 没有已加载模型，记录一个空操作
                actions.append({"name": name, "action": "stop models", "ok": True, "output": "no loaded models"})
        elif evict == "/free" and name == "comfyui":
            r = comfy_free()
            ok = r.get("ok", False)
            actions.append({"name": name, "action": "/free", "ok": ok,
                            "freed_mb": r.get("freed_mb", 0)})
            if ok:
                stopped.append({"name": name, "method": "/free"})
        elif evict == "docker stop":
            r = container_stop(name)
            ok = r.get("ok", False)
            actions.append({"name": name, "action": "docker stop", "ok": ok})
            if ok:
                stopped.append({"name": name, "method": "docker_stop"})
    # 通用扫描：未登记但挂载 GPU 的容器
    if guard.get("system", {}).get("gpu_container_scan", False):
        for cont in docker_containers():
            if any(m.get("name") == cont for m in managed):
                continue
            if _container_has_gpu(cont):
                r = container_stop(cont)
                ok = r.get("ok", False)
                actions.append({"name": cont, "action": "docker stop (auto-scan)", "ok": ok})
                if ok:
                    stopped.append({"name": cont, "method": "docker_stop"})
    # 最后等待5秒确保所有模型完全卸载，然后清除状态缓存
    time.sleep(5)
    try:
        # 同时失效 registry 旧缓存和 status_cache 新缓存
        _cache = registry.get("status_cache", {})
        _cache["ts"] = 0
        registry.set("status_cache", _cache)
        status_cache.invalidate()
    except Exception as e:
        log_error("exception_suppressed", error=e, context="docker.py:free_all_cache_invalidate")
    after = gpu_status(force_refresh=True)  # 强制刷新，避免读取释放前的缓存数据
    # 构建 running 数组：释放后仍在运行且占用 GPU 的进程
    running = []
    try:
        # 先强制刷新 gpu_status 缓存，确保 gpu_processes 内部读取到最新数据
        gpu_status(force_refresh=True)
        proc_info = gpu_processes()
        for p in proc_info.get("processes", []):
            if p.get("used_mb", 0) > 0:
                app = p.get("app", p.get("name", "unknown"))
                is_protected = any(pr.lower() in p.get("name", "").lower() for pr in protect_comms)
                running.append({
                    "name": app,
                    "gpu_mb": p.get("used_mb", 0),
                    "protected": is_protected,
                    "pid": p.get("pid"),
                })
    except Exception as e:
        log_error("free_all_running_scan_failed", error=e)
    total_count = len(actions)
    success_count = sum(1 for a in actions if a.get("ok", False))
    return {
        "ok": True,
        "free_mb_before": before.get("free_mb", 0),
        "free_mb_after": after.get("free_mb", 0),
        "freed_mb": max(0, after.get("free_mb", 0) - before.get("free_mb", 0)),
        "actions": actions,
        "stopped": stopped,
        "running": running,
        "success_count": success_count,
        "total_count": total_count,
    }
