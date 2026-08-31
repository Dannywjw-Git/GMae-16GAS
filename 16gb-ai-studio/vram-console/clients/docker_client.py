#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae Docker 客户端
- 封装所有 Docker 命令行调用
- 提供容器列表、容器操作、容器内命令执行等接口
- 所有调用统一超时和错误处理
"""
from core.logger import log_error
from core.utils import run_args


def list_running_containers() -> set:
    """列出所有运行中的容器名称。

    Returns:
        set: 容器名称集合
    """
    rc, out = run_args(["docker", "ps", "--format", "{{.Names}}"], 10)
    if rc != 0:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def container_exists(container_name: str) -> bool:
    """检查容器是否存在（运行中或已停止）。

    Args:
        container_name: 容器名

    Returns:
        bool: 存在返回 True
    """
    rc, out = run_args([
        "docker", "ps", "-a", "--filter", "name=" + container_name,
        "--format", "{{.Names}}"
    ], 10)
    return rc == 0 and container_name in out


def is_running(container_name: str) -> bool:
    """检查容器是否正在运行。

    Args:
        container_name: 容器名

    Returns:
        bool: 运行中返回 True
    """
    return container_name in list_running_containers()


def exec_command(container_name: str, command: list, timeout: int = 60) -> tuple:
    """在容器内执行命令。

    Args:
        container_name: 容器名
        command: 命令列表（如 ["ollama", "stop", "model"]）
        timeout: 超时秒数

    Returns:
        tuple: (return_code: int, output: str)
    """
    return run_args(["docker", "exec", container_name] + command, timeout)


def stop_container(container_name: str, timeout: int = 30) -> tuple:
    """停止指定容器。

    Args:
        container_name: 容器名
        timeout: 超时秒数

    Returns:
        tuple: (ok: bool, message: str)
    """
    rc, out = run_args(["docker", "stop", container_name], timeout)
    if rc != 0:
        return False, "stop failed: " + out[:200]
    return True, "stopped"


def start_container(container_name: str, timeout: int = 30) -> tuple:
    """启动指定容器。

    Args:
        container_name: 容器名
        timeout: 超时秒数

    Returns:
        tuple: (ok: bool, message: str)
    """
    rc, out = run_args(["docker", "start", container_name], timeout)
    if rc != 0:
        return False, "start failed: " + out[:200]
    return True, "started"


def kill_process_in_container(container_name: str, pid: int, timeout: int = 10) -> tuple:
    """在容器内 kill 指定 PID 的进程。

    Args:
        container_name: 容器名
        pid: 进程 ID
        timeout: 超时秒数

    Returns:
        tuple: (ok: bool, message: str)
    """
    rc, out = run_args(["docker", "exec", container_name, "kill", "-9", str(pid)], timeout)
    if rc != 0:
        return False, "kill failed: " + out[:200]
    return True, "killed"


def inspect_container(container_name: str, format_str: str, timeout: int = 10) -> tuple:
    """docker inspect 容器，返回原始输出。

    Args:
        container_name: 容器名
        format_str: --format 参数（如 "{{json .HostConfig.DeviceRequests}}"）
        timeout: 超时秒数

    Returns:
        tuple: (rc: int, output: str)
    """
    return run_args(["docker", "inspect", "--format", format_str, container_name], timeout)


def container_action(container_name: str, action: str, timeout: int = 60) -> tuple:
    """对容器执行 start/stop/restart 操作。

    Args:
        container_name: 容器名
        action: "start" / "stop" / "restart"
        timeout: 超时秒数

    Returns:
        tuple: (rc: int, output: str)
    """
    if action not in ("start", "stop", "restart"):
        return -1, "unsupported action: " + str(action)
    return run_args(["docker", action, container_name], timeout)
