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
import threading
from collections import deque
from core.logger import log_event, log_error
from core.registry import registry
from clients.nvidia_smi import (query_gpu_memory, query_compute_apps,
                                 query_container_compute_pids, query_container_processes)
from clients.docker_client import list_running_containers


# === nvidia-smi 缓存（S1.4）===
# 5 秒 TTL，危险状态（free_mb < 2048MB）时缩短为 2 秒
_gpu_status_cache = {"data": None, "timestamp": 0}
_gpu_status_lock = threading.Lock()
_GPU_STATUS_TTL = 5.0  # 秒（正常状态）
_GPU_STATUS_DANGER_TTL = 2.0  # 秒（危险状态，free_mb < 阈值）
_GPU_STATUS_DANGER_FREE_MB = 2048  # free_mb 低于此值视为危险状态
# 上次成功查询的持久缓存（nvidia-smi 超时时回退使用，避免 auto_protect 被跳过）
_last_good_gpu_status = None


def gpu_status(force_refresh: bool = False) -> dict:
    """查询 GPU 显存状态，带 5 秒 TTL 缓存（S1.4）。

    危险状态（free_mb < 2048MB）时 TTL 缩短为 2 秒，确保危险时数据更实时。
    force_refresh=True 时跳过缓存，强制执行 nvidia-smi 查询。

    容错：nvidia-smi 超时/失败时，回退到上次成功值并标记 stale=True，
    确保 qos_check/auto_protect 在高显存压力下仍能触发（安全机制宁可信其有）。

    Returns:
        dict: {"ok": bool, "total_mb": int, "used_mb": int, "free_mb": int,
               "utilization": int, "stale": bool(可选), "stale_age_s": float(可选)}
    """
    global _gpu_status_cache, _last_good_gpu_status
    with _gpu_status_lock:
        now = time.time()
        if not force_refresh and _gpu_status_cache["data"] is not None:
            data = _gpu_status_cache["data"]
            # 根据 free_mb 判断危险状态，决定 TTL
            if data.get("ok") and data.get("free_mb", 99999) < _GPU_STATUS_DANGER_FREE_MB:
                ttl = _GPU_STATUS_DANGER_TTL
            else:
                ttl = _GPU_STATUS_TTL
            if now - _gpu_status_cache["timestamp"] < ttl:
                return data
        # 执行 nvidia-smi 查询
        data = query_gpu_memory()
        if data.get("ok"):
            # 查询成功：更新持久缓存
            _last_good_gpu_status = dict(data)
            _last_good_gpu_status["stale"] = False
            _gpu_status_cache["good_timestamp"] = now
        elif _last_good_gpu_status is not None:
            # 查询失败但有上次成功值：回退到 stale 数据（安全优先）
            good_ts = _gpu_status_cache.get("good_timestamp", now)
            stale_age = now - good_ts
            data = dict(_last_good_gpu_status)
            data["stale"] = True
            data["stale_age_s"] = round(stale_age, 1)
            data["error"] = "nvidia-smi failed, using last known good value"
            log_error("gpu_status_stale_fallback", stale_age_s=stale_age,
                      free_mb=data.get("free_mb"), used_mb=data.get("used_mb"))
        _gpu_status_cache["data"] = data
        _gpu_status_cache["timestamp"] = now
        return data


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


def _get_dynamic_baseline(used_mb: int, known_total: int, desktop_used_mb: int) -> int:
    """动态测量系统底噪（GPU驱动 + WDDM + WSL2/Docker基础开销）。

    测量逻辑：
    - 当已知AI进程=0 且 桌面进程<500MB 时，当前已用显存 ≈ 系统底噪
    - 记录最小值到 registry，避免异常值
    - 无历史数据时使用默认值 800MB
    """
    from core.registry import registry
    DEFAULT_BASELINE = 800  # 默认底噪（介于旧的400和1536之间）
    MEASURE_THRESHOLD = 500  # 桌面进程小于此值时才测量

    # 从 registry 获取历史底噪
    baseline_history = registry.get("system_baseline_history", {})
    baseline_mb = baseline_history.get("baseline_mb", DEFAULT_BASELINE)

    # 测量条件：已知进程=0 且 桌面进程<500MB
    if known_total == 0 and desktop_used_mb < MEASURE_THRESHOLD and used_mb > 0:
        measured = used_mb - desktop_used_mb  # 减去桌面进程，剩下的就是底噪
        if measured > 100 and measured < 4096:  # 合理范围：100MB - 4GB
            # 取最小值，避免异常值
            if measured < baseline_mb or baseline_mb == DEFAULT_BASELINE:
                baseline_mb = measured
                baseline_history["baseline_mb"] = baseline_mb
                baseline_history["last_measured_at"] = int(time.time())
                baseline_history["measured_used_mb"] = used_mb
                baseline_history["measured_desktop_mb"] = desktop_used_mb
                registry.set("system_baseline_history", baseline_history)

    return baseline_mb


def gpu_processes() -> dict:
    """进程级显存账本（重构版 v2：混合方案）。

    重构要点：
    - ollama: 使用 ollama_ps() 获取已加载模型和显存占用（按模型分配）
    - comfyui: 使用 comfy_system_stats() 获取 torch_vram_used_mb
    - fooocus: 尝试容器内 nvidia-smi，失败则估算
    - 桌面进程: 设为 0（不再倒推，WSL2 环境下无法准确获取）
    - unknown_mb = 实际已用 - 已知进程总和 - 系统底噪（400MB）
    - 保留进程生命周期跟踪和事件发布（S2 EventBus）
    """
    from services.ollama import ollama_ps
    from services.comfy import comfy_system_stats
    from clients.nvidia_smi import query_container_compute_apps

    gpu = gpu_status()
    names = list_running_containers()
    processes = []
    src = "hybrid_estimate"

    # ===== 1. ollama: 使用 ollama_ps() 获取已加载模型和显存占用 =====
    if "ollama" in names:
        ollama_models = ollama_ps().get("models", [])
        for m in ollama_models:
            model_name = m.get("name", "")
            size_gb = m.get("size_gb", 0)
            used_mb = int(size_gb * 1024)
            if used_mb > 0:
                processes.append({
                    "pid": f"ollama-{model_name}",
                    "name": f"ollama: {model_name}",
                    "app": "ollama",
                    "used_mb": used_mb,
                    "known": True,
                    "model": model_name,
                    "container": "ollama",
                    "until": m.get("until", ""),
                })
    # ===== 2. comfyui: torch 实测占用 + 模型级显存分解（对齐 ollama 粒度）=====
    if "comfyui" in names:
        try:
            from services.comfy import comfy_model_breakdown
            bd = comfy_model_breakdown()
            comfy_used_mb = bd.get("torch_used_mb", 0) or 0
            if comfy_used_mb > 0:
                resident = bd.get("models", []) if bd.get("resident") else []
                # 每个常驻模型一行（文件大小估算显存）
                for m in resident:
                    if (m.get("size_mb") or 0) > 0:
                        processes.append({
                            "pid": "comfyui-" + m["name"],
                            "name": "comfyui: " + m["name"],
                            "app": "comfyui",
                            "used_mb": m["size_mb"],
                            "known": True,
                            "model": m["name"],
                            "kind": m.get("kind", "model"),
                            "container": "comfyui",
                        })
                overhead_mb = bd.get("overhead_mb", 0) or 0
                if not resident:
                    # 无活跃模型（刚启动/已释放）：torch 占用整体作为框架/缓存一行
                    processes.append({
                        "pid": "comfyui-torch",
                        "name": "comfyui: 框架/CUDA/缓存（无活跃模型）",
                        "app": "comfyui",
                        "used_mb": comfy_used_mb,
                        "known": True,
                        "container": "comfyui",
                        "overhead": True,
                    })
                elif overhead_mb >= 100:
                    # 有模型时，无法归因到模型的差额（CUDA上下文/激活/缓存）单列一行
                    processes.append({
                        "pid": "comfyui-framework",
                        "name": "comfyui: 框架/CUDA上下文/缓存",
                        "app": "comfyui",
                        "used_mb": overhead_mb,
                        "known": True,
                        "container": "comfyui",
                        "overhead": True,
                    })
        except Exception as e:
            log_error("gpu_processes_comfy_stats_failed", error=e)

    # ===== 3. fooocus: 尝试容器内 nvidia-smi，失败则估算 =====
    if "fooocus" in names:
        fooocus_used = 0
        try:
            result = query_container_compute_apps("fooocus")
            if result.get("ok") and result.get("processes"):
                for p in result.get("processes", []):
                    if p.get("used_mb", 0) > 0:
                        processes.append({
                            "pid": str(p["pid"]),
                            "name": f"fooocus: {p.get('name', 'python')}",
                            "app": "fooocus",
                            "used_mb": p.get("used_mb", 0),
                            "known": True,
                            "container": "fooocus",
                        })
                        fooocus_used += p.get("used_mb", 0)
        except Exception as e:
            log_error("exception_suppressed", error=e, context="monitor.py:240")
        # 如果容器内 nvidia-smi 失败，使用估算（fooocus 通常占用约 6-7GB）
        if fooocus_used == 0:
            estimated = int(6.5 * 1024)
            processes.append({
                "pid": "fooocus-est",
                "name": "fooocus: python (estimated)",
                "app": "fooocus",
                "used_mb": estimated,
                "known": True,
                "estimated": True,
                "container": "fooocus",
            })

    # ===== 4. 计算统计数据（动态底噪测量） =====
    known_total = sum(p["used_mb"] for p in processes)
    unknown_pids = []
    # 先获取桌面进程显存（用于动态底噪测量）
    _desktop_for_baseline = 0
    try:
        from services.helper import get_windows_gpu_processes
        _win_gpu = get_windows_gpu_processes()
        if _win_gpu.get("ok"):
            _desktop_procs = [p for p in _win_gpu.get("processes", [])
                             if p.get("name", "").lower() not in ("vmwp", "vmmem", "vmmemwsl")]
            _desktop_for_baseline = int(sum(p.get("used_mb", 0) for p in _desktop_procs))
    except Exception:
        pass
    # 动态测量系统底噪（GPU驱动 + WDDM + WSL2/Docker基础开销）
    system_baseline = _get_dynamic_baseline(
        gpu.get("used_mb", 0) if gpu.get("ok") else 0,
        known_total,
        _desktop_for_baseline
    )
    unknown_mb = 0
    known_estimated = False
    if gpu.get("ok"):
        # 已知进程可用显存 = 已用 - 底噪 - 桌面（确保分类之和不超过已用）
        available_for_known = max(0, gpu["used_mb"] - system_baseline - _desktop_for_baseline)
        # 如果已知进程显存超过可用范围（如Ollama size_gb是模型文件大小而非实际显存），按比例缩放
        if known_total > available_for_known and known_total > 0:
            scale = available_for_known / known_total
            for p in processes:
                p["used_mb"] = int(p["used_mb"] * scale)
                p["estimated"] = True
            known_total = sum(p["used_mb"] for p in processes)
            known_estimated = True
        unknown_mb = max(0, gpu["used_mb"] - known_total - system_baseline - _desktop_for_baseline)

    # ===== 5. 进程生命周期跟踪和事件发布（S2 EventBus）=====
    gpu_pids = set(p["pid"] for p in processes if p["pid"].isdigit())
    _update_process_lifecycle(gpu_pids, processes)
    for p in processes:
        if p["pid"].isdigit():
            lc = _proc_lifecycle.get(p["pid"])
            if lc:
                p["first_seen"] = lc["first_seen"]
                p["first_used_mb"] = lc["first_used_mb"]
                p["exit_seen"] = lc.get("exit_seen")

    # ===== 6. 桌面进程（使用 PowerShell 性能计数器获取 Windows 进程显存）=====
    # 注意：排除 vmwp（WSL2 虚拟机进程）和 AI 推理进程，避免重复计算或错误分类
    desktop = desktop_gpu_processes()
    desktop_used_mb = 0
    # AI 推理进程黑名单：这些进程占用 GPU 显存但不属于"桌面"，应归为已知进程
    AI_PROCESS_NAMES = ("llama-server", "ollama", "ollama_llama_server", "python", "comfyui",
                        "fooocus", "stable-diffusion", "invokeai", "kohya", "sd-webui",
                        "text-generation-webui", "oobabooga", "kobold", "vllm", "tensorrt")
    ai_procs_from_desktop = []  # 从桌面进程中识别出的 AI 进程
    try:
        from services.helper import get_windows_gpu_processes
        win_gpu = get_windows_gpu_processes()
        if win_gpu.get("ok"):
            # 排除 vmwp/vmmem（WSL2）和 AI 推理进程
            all_win_procs = win_gpu.get("processes", [])
            desktop_procs = []
            for p in all_win_procs:
                pname = p.get("name", "").lower()
                if pname in ("vmwp", "vmmem", "vmmemwsl"):
                    continue  # WSL2 虚拟机进程，显存已在 nvidia-smi 统计中
                if any(ai in pname for ai in AI_PROCESS_NAMES):
                    ai_procs_from_desktop.append(p)  # AI 进程，移到已知进程
                    continue
                desktop_procs.append(p)
            desktop_used_mb = int(sum(p.get("used_mb", 0) for p in desktop_procs))
            # 把 Windows 桌面进程添加到 desktop_processes
            desktop["processes"] = [{"name": p["name"], "pid": p["pid"],
                                      "used_mb": p["used_mb"]} for p in desktop_procs[:20]]
            desktop["count"] = len(desktop["processes"])
    except Exception as e:
        log_error("gpu_processes_windows_gpu_failed", error=str(e))

    # 把从桌面进程中识别出的 AI 进程合并到已知进程列表（避免重复，按 PID 去重）
    if ai_procs_from_desktop:
        existing_pids = set(str(p.get("pid")) for p in processes)
        for ap in ai_procs_from_desktop:
            if str(ap.get("pid")) not in existing_pids:
                processes.append({
                    "name": ap.get("name", "unknown"),
                    "app": ap.get("name", "unknown"),
                    "pid": str(ap.get("pid", "")),
                    "used_mb": int(ap.get("used_mb", 0)),
                    "known": True,
                    "kind": "ai_inference",
                    "estimated": False,
                })
        known_total = sum(p["used_mb"] for p in processes)

    return {
        "ok": True, "processes": processes,
        "unknown_pids": unknown_pids, "unknown_mb": unknown_mb,
        "baseline_mb": system_baseline,  # 动态测量的系统底噪（不再硬编码1536）
        "known_total_mb": known_total,
        "desktop_processes": desktop.get("processes", []),
        "desktop_count": desktop.get("count", 0),
        "desktop_used_mb": desktop_used_mb,
        "system_baseline_mb": system_baseline,  # 与 baseline_mb 统一
        "baseline_dynamic": True,  # 标记为动态测量
        "known_estimated": known_estimated,  # 已知进程显存是否被缩放（模型文件大小vs实际显存）
        "gpu_pid_source": src,
        "events": list(_proc_events),
    }
