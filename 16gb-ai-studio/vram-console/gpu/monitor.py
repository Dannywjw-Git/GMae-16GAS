#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae GPU 监控模块
- 显存状态查询（gpu_status）
- 容器进程 PID 映射
- GPU 计算进程探测
- 桌面 GPU 进程账本
- 进程级显存账本（gpu_processes）
- 进程生命周期追踪
"""
import time
from collections import deque
from core.logger import log_event, log_error
from core.registry import registry
from clients.nvidia_smi import (query_gpu_memory, query_compute_apps,
                                 query_container_compute_pids, query_container_processes)
from clients.docker_client import list_running_containers


def gpu_status() -> dict:
    """查询 GPU 显存状态。"""
    return query_gpu_memory()


def _container_pids(cont):
    """容器内进程 PID → comm 映射。"""
    return query_container_processes(cont)


def _gpu_app_pids(names=None):
    """从在跑的受管容器拿 GPU 计算进程 PID 列表。"""
    if names is None:
        names = list_running_containers()
    for cont in ("comfyui", "ollama", "fooocus"):
        if cont in names:
            pids = query_container_compute_pids(cont)
            if pids:
                return pids, cont
    return [], None


def desktop_gpu_processes() -> dict:
    """宿主机侧 nvidia-smi 进程表 → Windows 桌面 GPU 进程。"""
    return query_compute_apps()


# === 进程生命周期追踪 — 已迁移到 registry（状态包装）===
_lifecycle_state = registry.get("lifecycle_state")
if _lifecycle_state is None:
    _lifecycle_state = {
        "proc_lifecycle": {},
        "proc_events": deque(maxlen=200),
        "last_known_pids": set(),
        "lifecycle_init": False,
    }
    registry.set("lifecycle_state", _lifecycle_state)

# 可变对象直接引用（修改字段不需要 global）
_proc_lifecycle = _lifecycle_state["proc_lifecycle"]
_proc_events = _lifecycle_state["proc_events"]


def _update_process_lifecycle(gpu_pids, processes):
    """进程状态差分：新 PID 记首见+up 事件；消失 PID 记退出+down 事件。"""
    now = int(time.time())
    cur = set(gpu_pids)
    by_pid = {p["pid"]: p for p in processes}
    if not _lifecycle_state["lifecycle_init"]:
        for pid in cur:
            p = by_pid.get(pid)
            _proc_lifecycle[pid] = {
                "first_seen": now, "last_seen": now,
                "name": p.get("name") if p else "",
                "app": p.get("app") if p else "",
                "first_used_mb": p.get("used_mb", 0) if p else 0,
            }
        _lifecycle_state["last_known_pids"] = cur
        _lifecycle_state["lifecycle_init"] = True
        return
    new_pids = cur - _lifecycle_state["last_known_pids"]
    gone_pids = _lifecycle_state["last_known_pids"] - cur
    for pid in new_pids:
        p = by_pid.get(pid)
        _proc_lifecycle[pid] = {
            "first_seen": now, "last_seen": now,
            "name": p.get("name") if p else "",
            "app": p.get("app") if p else "",
            "first_used_mb": p.get("used_mb", 0) if p else 0,
        }
        _proc_events.append({"ts": now, "event": "up", "pid": pid,
                             "name": _proc_lifecycle[pid]["name"],
                             "app": _proc_lifecycle[pid]["app"],
                             "used_mb": _proc_lifecycle[pid]["first_used_mb"]})
    for pid in gone_pids:
        if pid in _proc_lifecycle:
            lc = _proc_lifecycle[pid]
            lc["exit_seen"] = now
            lc["alive_s"] = now - lc["first_seen"]
            _proc_events.append({"ts": now, "event": "down", "pid": pid,
                                 "name": lc["name"], "app": lc["app"],
                                 "alive_s": lc["alive_s"]})
    for pid in cur:
        if pid in _proc_lifecycle:
            _proc_lifecycle[pid]["last_seen"] = now
    _lifecycle_state["last_known_pids"] = cur


def _find_pid_container(pid):
    """找 PID 归属的容器（受管优先，再遍历全部）。返回容器名或 None。"""
    names = list_running_containers()
    for cont in ("comfyui", "ollama", "fooocus"):
        if cont in names and pid in _container_pids(cont):
            return cont
    for cont in names:
        if pid in _container_pids(cont):
            return cont
    return None


def gpu_processes() -> dict:
    """进程级显存账本。"""
    from services.ollama import ollama_ps
    from services.comfy import comfy_system_stats

    gpu = gpu_status()
    names = list_running_containers()
    cont_pids = {}
    for cont, app in (("comfyui", "comfyui"), ("ollama", "ollama"), ("fooocus", "fooocus")):
        if cont in names:
            for pid, comm in _container_pids(cont).items():
                cont_pids[pid] = (app, comm)
    gpu_pids, src = _gpu_app_pids(names)
    if not gpu_pids:
        gpu_pids = [pid for pid, (app, comm) in cont_pids.items()
                    if (app == "ollama" and "llama-server" in comm.lower())
                    or (app == "comfyui" and ("python" in comm.lower() or "comfy" in comm.lower()))
                    or (app == "fooocus" and "python" in comm.lower())]
        src = "ps_fallback" if gpu_pids else None
    ollama_models = ollama_ps().get("models", [])
    ollama_used_mb = sum(int(m.get("size_gb", 0) * 1024) for m in ollama_models)
    comfy_stat = comfy_system_stats()
    comfy_used_mb = comfy_stat.get("torch_vram_used_mb", 0) or 0
    processes = []
    for pid in gpu_pids:
        if pid not in cont_pids:
            continue
        app, comm = cont_pids[pid]
        if app == "ollama":
            used = ollama_used_mb if ("llama" in comm.lower() or comm.lower() == "ollama") else 0
        elif app == "comfyui":
            used = comfy_used_mb if ("python" in comm.lower() or "comfy" in comm.lower()) else 0
        elif app == "fooocus":
            used = int(6.9 * 1024)
        else:
            used = 0
        processes.append({"pid": pid, "name": comm, "app": app, "used_mb": used, "known": True})
    known_pids = {p["pid"] for p in processes}
    unknown_pids = [pid for pid in gpu_pids if pid not in known_pids]
    known_total = sum(p["used_mb"] for p in processes)
    unknown_mb = 0
    if gpu.get("ok"):
        unknown_mb = max(0, gpu["used_mb"] - 1536 - known_total)
    _update_process_lifecycle(gpu_pids, processes)
    for p in processes:
        lc = _proc_lifecycle.get(p["pid"])
        if lc:
            p["first_seen"] = lc["first_seen"]
            p["first_used_mb"] = lc["first_used_mb"]
            p["exit_seen"] = lc.get("exit_seen")
    desktop = desktop_gpu_processes()
    desktop_used_mb = 0
    if gpu.get("ok"):
        desktop_used_mb = max(0, gpu["used_mb"] - known_total - 400)
    return {
        "ok": True, "processes": processes,
        "unknown_pids": unknown_pids, "unknown_mb": unknown_mb,
        "baseline_mb": 1536, "known_total_mb": known_total,
        "desktop_processes": desktop.get("processes", []),
        "desktop_count": desktop.get("count", 0),
        "desktop_used_mb": desktop_used_mb,
        "system_baseline_mb": 400,
        "gpu_pid_source": src,
        "events": list(_proc_events),
    }
