#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae nvidia-smi 客户端
- 封装所有 nvidia-smi 命令行调用
- 提供显存状态、GPU 进程、容器内 GPU 进程查询
- 所有调用统一超时和错误处理
"""
import os
from core.logger import log_error
from core.utils import run_args


def query_gpu_memory() -> dict:
    """查询 GPU 显存总览（total/used/free/utilization）。

    Returns:
        dict: {"ok": bool, "total_mb": int, "used_mb": int, "free_mb": int, "utilization": int}
    """
    rc, out = run_args([
        "nvidia-smi",
        "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits"
    ], 10)
    if rc != 0:
        return {"ok": False, "error": out[:200]}
    parts = [x.strip() for x in out.strip().split(",")]
    util = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    return {
        "ok": True,
        "total_mb": int(parts[0]),
        "used_mb": int(parts[1]),
        "free_mb": int(parts[2]),
        "utilization": util,
    }


def query_compute_apps() -> dict:
    """查询宿主机 GPU 计算进程列表（pid + process_name）。

    Returns:
        dict: {"ok": bool, "processes": [{"pid": int, "name": str}], "count": int}
    """
    rc, out = run_args([
        "nvidia-smi",
        "--query-compute-apps=pid,process_name",
        "--format=csv,noheader"
    ], 10)
    processes = []
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            pid_s, name = parts[0], parts[1]
            if pid_s.isdigit() and name and name.lower() not in (
                    "[insufficient permissions]", "[not found]", "n/a", "[n/a]"):
                processes.append({
                    "pid": int(pid_s),
                    "name": os.path.basename(name.replace("\\", "/")),
                })
    return {"ok": rc == 0, "processes": processes, "count": len(processes)}


def query_container_compute_pids(container_name: str) -> list:
    """查询指定容器内的 GPU 计算进程 PID 列表。

    Args:
        container_name: Docker 容器名

    Returns:
        list: PID 字符串列表，失败返回空列表
    """
    rc, out = run_args([
        "docker", "exec", container_name,
        "nvidia-smi", "--query-compute-apps=pid",
        "--format=csv,noheader"
    ], 10)
    if rc != 0:
        return []
    return [l.strip() for l in out.splitlines() if l.strip().isdigit()]


def query_container_processes(container_name: str) -> dict:
    """查询容器内所有进程（pid + comm）。

    Args:
        container_name: Docker 容器名

    Returns:
        dict: {pid_str: comm_str}，失败返回空 dict
    """
    rc, out = run_args([
        "docker", "exec", container_name,
        "ps", "-eo", "pid=,comm="
    ], 10)
    if rc != 0:
        return {}
    pmap = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            pmap[parts[0]] = parts[1]
    return pmap


def query_container_compute_apps(container_name: str) -> dict:
    """查询容器内 GPU 计算进程的详细信息（pid + process_name + used_memory）。

    通过 docker exec 在容器内运行 nvidia-smi，获取容器内进程的实际显存占用。

    Args:
        container_name: Docker 容器名

    Returns:
        dict: {"ok": bool, "processes": [{"pid": int, "name": str, "used_mb": int}], "count": int}
    """
    rc, out = run_args([
        "docker", "exec", container_name,
        "nvidia-smi",
        "--query-compute-apps=pid,process_name,used_memory",
        "--format=csv,noheader,nounits"
    ], 15)
    processes = []
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            pid_s, name, used_s = parts[0], parts[1], parts[2]
            if not pid_s.isdigit():
                continue
            try:
                used_mb = int(float(used_s))
            except (ValueError, TypeError):
                used_mb = 0
            if name and name.lower() not in (
                    "[insufficient permissions]", "[not found]", "n/a", "[n/a]"):
                processes.append({
                    "pid": int(pid_s),
                    "name": os.path.basename(name.replace("\\", "/")),
                    "used_mb": used_mb,
                })
    return {"ok": rc == 0, "processes": processes, "count": len(processes)}


def query_container_process_cmdline(container_name: str, pid: str) -> str:
    """查询容器内指定 PID 的完整命令行（用于识别具体加载的模型）。

    Args:
        container_name: Docker 容器名
        pid: 进程 PID（字符串）

    Returns:
        str: 完整命令行，失败返回空字符串
    """
    rc, out = run_args([
        "docker", "exec", container_name,
        "cat", f"/proc/{pid}/cmdline"
    ], 10)
    if rc != 0:
        return ""
    # /proc/PID/cmdline 用 null 字节分隔参数
    return out.replace("\x00", " ").strip()


def query_compute_apps_with_memory() -> dict:
    """查询宿主机 GPU 计算进程的详细信息（pid + process_name + used_memory）。

    Returns:
        dict: {"ok": bool, "processes": [{"pid": int, "name": str, "used_mb": int}], "count": int}
    """
    rc, out = run_args([
        "nvidia-smi",
        "--query-compute-apps=pid,process_name,used_memory",
        "--format=csv,noheader,nounits"
    ], 10)
    processes = []
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            pid_s, name, used_s = parts[0], parts[1], parts[2]
            if not pid_s.isdigit():
                continue
            try:
                used_mb = int(float(used_s))
            except (ValueError, TypeError):
                used_mb = 0
            if name and name.lower() not in (
                    "[insufficient permissions]", "[not found]", "n/a", "[n/a]"):
                processes.append({
                    "pid": int(pid_s),
                    "name": os.path.basename(name.replace("\\", "/")),
                    "used_mb": used_mb,
                })
    return {"ok": rc == 0, "processes": processes, "count": len(processes)}
