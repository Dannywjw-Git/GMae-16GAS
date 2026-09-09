#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 平台检测模块（轻量适配核心）

检测运行环境：Windows / Linux / WSL2 / Docker-in-WSL2
提供平台能力查询，供各模块优雅降级。

设计原则：
- 检测一次，缓存结果
- 不依赖第三方库（标准库 + /proc 检测）
- 每个能力字段有明确含义，调用方按需查询
"""
import os
import sys
import platform


def _detect_os() -> str:
    """检测操作系统：windows / linux / macos / other"""
    sysname = platform.system().lower()
    if sysname.startswith("win"):
        return "windows"
    if sysname == "linux":
        return "linux"
    if sysname == "darwin":
        return "macos"
    return "other"


def _detect_wsl() -> bool:
    """检测是否运行在 WSL2 中（Linux 侧）。"""
    if _os != "linux":
        return False
    # 方法1: /proc/version 包含 microsoft
    try:
        with open("/proc/version", "r") as f:
            if "microsoft" in f.read().lower():
                return True
    except Exception:
        pass
    # 方法2: 环境变量
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    return False


def _detect_wsl2_windows() -> bool:
    """检测是否是 Windows 上通过 WSL2 运行 Docker（Windows 侧）。

    GMae 本体跑在 Windows 上，但 Docker Desktop 后端是 WSL2。
    这是 GMae 的主要部署形态，影响 docker pause 是否释放 GPU 显存。
    """
    if _os != "windows":
        return False
    # Docker Desktop on Windows 默认使用 WSL2 后端
    # 检测 Docker Desktop 是否安装且使用 WSL2
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "info", "--format", "{{.Driver}}"],
            capture_output=True, text=True, timeout=10
        )
        # WSL2 后端的 Docker storage driver 通常是 overlay2
        # 更准确的检测：检查 wsl 命令是否存在且 docker-desktop distro 是否运行
        if result.returncode == 0:
            try:
                wsl_result = subprocess.run(
                    ["wsl", "-l", "-q"],
                    capture_output=True, text=True, timeout=10
                )
                if "docker-desktop" in wsl_result.stdout.lower():
                    return True
            except Exception:
                pass
    except Exception:
        pass
    # 兜底：Windows + Docker Desktop 大概率是 WSL2 后端
    # （Hyper-V 后端已被 Docker Desktop 弃用）
    return True


def _detect_docker_available() -> bool:
    """检测 Docker 是否可用。"""
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _detect_nvidia_available() -> bool:
    """检测 NVIDIA GPU 是否可用。"""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


# === 检测结果（模块加载时一次性检测）===
_os = _detect_os()
_is_wsl = _detect_wsl()
_is_wsl2_windows = _detect_wsl2_windows() if _os == "windows" else False
_docker_available = _detect_docker_available()
_nvidia_available = _detect_nvidia_available()


def get_platform_info() -> dict:
    """获取完整平台信息（用于 API 输出和调试）。"""
    return {
        "os": _os,
        "is_wsl": _is_wsl,
        "is_wsl2_windows": _is_wsl2_windows,
        "docker_available": _docker_available,
        "nvidia_available": _nvidia_available,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


# === 便捷查询函数 ===

def is_windows() -> bool:
    return _os == "windows"


def is_linux() -> bool:
    return _os == "linux"


def is_macos() -> bool:
    return _os == "macos"


def is_wsl() -> bool:
    """是否运行在 WSL2 Linux 侧。"""
    return _is_wsl


def is_wsl2_docker() -> bool:
    """是否是 Windows + WSL2 Docker 后端（GMae 主要部署形态）。

    影响：
    - docker pause 不释放 GPU 显存（必须用 docker stop）
    - nvidia-smi 从 Windows 侧调用，能看到 WSL2 容器内的 GPU 进程
    """
    return _is_wsl2_windows


def docker_pause_releases_gpu() -> bool:
    """docker pause 是否能释放 GPU 显存。

    WSL2 + Docker Desktop 下，docker pause 不释放 GPU 显存（实测仅降 15MB）。
    原生 Linux Docker 下，docker pause 通常能释放 GPU 显存。
    """
    if is_wsl2_docker():
        return False
    # 原生 Linux 下 pause 通常能释放（但不保证，保守返回 True）
    return not is_windows()


def has_docker() -> bool:
    return _docker_available


def has_nvidia_gpu() -> bool:
    return _nvidia_available


def supports_windows_toast() -> bool:
    """是否支持 Windows Toast 通知。"""
    return is_windows()


def supports_uac() -> bool:
    """是否支持 UAC 提权（Windows 专用）。"""
    return is_windows()


def supports_powershell() -> bool:
    """是否支持 PowerShell。"""
    return is_windows()


# === 独立运行：python platform.py ===
if __name__ == "__main__":
    info = get_platform_info()
    print("GMae Platform Detection")
    print("=" * 40)
    for k, v in info.items():
        print(f"  {k}: {v}")
    print()
    print("Capability queries:")
    print(f"  is_windows: {is_windows()}")
    print(f"  is_linux: {is_linux()}")
    print(f"  is_wsl: {is_wsl()}")
    print(f"  is_wsl2_docker: {is_wsl2_docker()}")
    print(f"  docker_pause_releases_gpu: {docker_pause_releases_gpu()}")
    print(f"  has_docker: {has_docker()}")
    print(f"  has_nvidia_gpu: {has_nvidia_gpu()}")
