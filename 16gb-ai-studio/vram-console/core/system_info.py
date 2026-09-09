#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 系统信息探测模块（SystemInfo）

为系统拓扑图提供宿主机硬件和平台软件信息。
跨平台设计：Windows / Linux / macOS 均可运行，探测失败降级为 null。

探测内容：
- CPU：型号、核心数、使用率
- 内存：总量、已用、使用率
- 磁盘：型号、总量、已用、读写速率
- 网络：IP、上下行速率
- OS：名称、版本、构建号
- WSL：版本（仅Windows）
- Docker：版本、运行状态
- Python：版本

设计原则：
- 每个探测器独立 try-except，一个失败不影响其他
- 探测失败返回 None，前端显示"—"
- 优先使用 psutil（跨平台），降级到平台原生命令
"""
import os
import sys
import time
import platform
from typing import Dict, List, Any, Optional

# 尝试导入 psutil（跨平台系统信息库）
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

from core.logger import logger


class SystemInfo:
    """系统信息收集器。"""

    def __init__(self):
        self._last_net_io = None
        self._last_net_time = None

    def collect(self) -> Dict[str, Any]:
        """收集全部系统信息。

        Returns:
            包含 cpu/memory/disks/network/os/wsl/docker/python 的字典
        """
        return {
            "cpu": self._probe_cpu(),
            "memory": self._probe_memory(),
            "disks": self._probe_disks(),
            "network": self._probe_network(),
            "os": self._probe_os(),
            "wsl": self._probe_wsl(),
            "docker": self._probe_docker(),
            "python": self._probe_python(),
            "collected_at": int(time.time()),
        }

    # ===== CPU =====
    def _probe_cpu(self) -> Dict[str, Any]:
        """探测 CPU 信息。"""
        result = {
            "name": None,
            "cores": None,
            "threads": None,
            "usage_pct": None,
            "freq_mhz": None,
        }
        try:
            if _HAS_PSUTIL:
                result["cores"] = psutil.cpu_count(logical=False)
                result["threads"] = psutil.cpu_count(logical=True)
                result["usage_pct"] = psutil.cpu_percent(interval=0.5)
                freq = psutil.cpu_freq()
                if freq:
                    result["freq_mhz"] = int(freq.current)
            # CPU 型号（平台特定）
            if sys.platform == "win32":
                result["name"] = self._probe_cpu_windows()
            elif sys.platform == "linux":
                result["name"] = self._probe_cpu_linux()
            elif sys.platform == "darwin":
                result["name"] = self._probe_cpu_macos()
        except Exception as e:
            logger.warning(f"CPU probe failed: {e}")
        return result

    def _probe_cpu_windows(self) -> Optional[str]:
        """Windows: 从注册表获取 CPU 型号。"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            return name.strip()
        except Exception:
            return platform.processor() or None

    def _probe_cpu_linux(self) -> Optional[str]:
        """Linux: 从 /proc/cpuinfo 获取 CPU 型号。"""
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return platform.processor() or None

    def _probe_cpu_macos(self) -> Optional[str]:
        """macOS: 用 sysctl 获取 CPU 型号。"""
        try:
            import subprocess
            out = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                timeout=5, text=True
            ).strip()
            return out
        except Exception:
            return platform.processor() or None

    # ===== 内存 =====
    def _probe_memory(self) -> Dict[str, Any]:
        """探测内存信息。"""
        result = {
            "total_mb": None,
            "used_mb": None,
            "available_mb": None,
            "usage_pct": None,
        }
        try:
            if _HAS_PSUTIL:
                mem = psutil.virtual_memory()
                result["total_mb"] = int(mem.total / (1024 * 1024))
                result["used_mb"] = int(mem.used / (1024 * 1024))
                result["available_mb"] = int(mem.available / (1024 * 1024))
                result["usage_pct"] = round(mem.percent, 1)
            elif sys.platform == "win32":
                # Windows 降级：wmic
                try:
                    import subprocess
                    out = subprocess.check_output(
                        ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory", "/value"],
                        timeout=10, text=True
                    )
                    for line in out.splitlines():
                        if "=" in line:
                            total_bytes = int(line.split("=")[1].strip())
                            result["total_mb"] = int(total_bytes / (1024 * 1024))
                            break
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Memory probe failed: {e}")
        return result

    # ===== 磁盘 =====
    def _probe_disks(self) -> List[Dict[str, Any]]:
        """探测磁盘信息。"""
        disks = []
        # Windows: 预取所有物理磁盘型号（wmic 已在 Win11 移除，用 CIM 替代）
        disk_models = self._probe_all_disk_models_windows() if sys.platform == "win32" else []
        try:
            if _HAS_PSUTIL:
                for idx, part in enumerate(psutil.disk_partitions(all=False)):
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        disk = {
                            "device": part.device,
                            "mountpoint": part.mountpoint,
                            "fstype": part.fstype,
                            "total_gb": round(usage.total / (1024 ** 3), 1),
                            "used_gb": round(usage.used / (1024 ** 3), 1),
                            "free_gb": round(usage.free / (1024 ** 3), 1),
                            "usage_pct": usage.percent,
                        }
                        # 磁盘型号：按分区顺序匹配物理磁盘
                        if disk_models and idx < len(disk_models):
                            disk["model"] = disk_models[idx]
                        elif disk_models:
                            disk["model"] = disk_models[-1]
                        disks.append(disk)
                    except (PermissionError, OSError):
                        continue
                # 磁盘 IO 速率
                try:
                    io = psutil.disk_io_counters()
                    if io:
                        for d in disks:
                            d["read_mbps"] = 0
                            d["write_mbps"] = 0
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Disk probe failed: {e}")
        return disks

    def _probe_all_disk_models_windows(self) -> List[str]:
        """Windows: 获取所有物理磁盘型号列表（PowerShell CIM，替代已弃用的 wmic）。"""
        try:
            import subprocess
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_DiskDrive).Model"],
                timeout=10, text=True
            )
            return [m.strip() for m in out.splitlines() if m.strip()]
        except Exception:
            return []

    # ===== 网络 =====
    def _probe_network(self) -> Dict[str, Any]:
        """探测网络信息。"""
        result = {
            "ip": None,
            "upload_mbps": None,
            "download_mbps": None,
            "interfaces": [],
        }
        try:
            if _HAS_PSUTIL:
                # 获取所有网络接口
                all_ips = []
                addrs = psutil.net_if_addrs()
                for iface, addr_list in addrs.items():
                    for addr in addr_list:
                        if addr.family == 2:  # AF_INET
                            if not addr.address.startswith("127."):
                                all_ips.append({"name": iface, "ip": addr.address})
                                result["interfaces"].append({
                                    "name": iface,
                                    "ip": addr.address,
                                })
                # 优先选择局域网 IP（192.168.x.x / 10.x.x.x），其次是其他
                for ip_info in all_ips:
                    ip = ip_info["ip"]
                    if ip.startswith("192.168.") or ip.startswith("10."):
                        result["ip"] = ip
                        break
                if not result["ip"] and all_ips:
                    result["ip"] = all_ips[0]["ip"]
                # 网络速率（需要两次采样）
                io = psutil.net_io_counters()
                now = time.time()
                if self._last_net_io and self._last_net_time:
                    dt = now - self._last_net_time
                    if dt > 0:
                        result["upload_mbps"] = round(
                            (io.bytes_sent - self._last_net_io.bytes_sent) / dt / (1024 * 1024), 2
                        )
                        result["download_mbps"] = round(
                            (io.bytes_recv - self._last_net_io.bytes_recv) / dt / (1024 * 1024), 2
                        )
                self._last_net_io = io
                self._last_net_time = now
        except Exception as e:
            logger.warning(f"Network probe failed: {e}")
        return result

    # ===== OS =====
    def _probe_os(self) -> Dict[str, Any]:
        """探测操作系统信息。"""
        result = {
            "name": None,
            "version": None,
            "build": None,
            "type": None,
        }
        try:
            if sys.platform == "win32":
                result["type"] = "windows"
                result["name"] = "Windows"
                try:
                    ver = sys.getwindowsversion()
                    result["build"] = str(ver.build)
                    # 版本号映射
                    build = ver.build
                    if build >= 22000:
                        result["version"] = "11"
                    elif build >= 10240:
                        result["version"] = "10"
                    else:
                        result["version"] = platform.version()
                except Exception:
                    result["version"] = platform.version()
            elif sys.platform == "linux":
                result["type"] = "linux"
                try:
                    with open("/etc/os-release", "r") as f:
                        for line in f:
                            if line.startswith("PRETTY_NAME="):
                                result["name"] = line.split("=", 1)[1].strip().strip('"')
                                break
                except Exception:
                    result["name"] = "Linux"
                result["version"] = platform.release()
            elif sys.platform == "darwin":
                result["type"] = "macos"
                result["name"] = "macOS"
                result["version"] = platform.mac_ver()[0]
            else:
                result["type"] = "unknown"
                result["name"] = platform.system()
                result["version"] = platform.release()
        except Exception as e:
            logger.warning(f"OS probe failed: {e}")
        return result

    # ===== WSL =====
    def _probe_wsl(self) -> Dict[str, Any]:
        """探测 WSL 版本（仅 Windows）。"""
        result = {
            "available": False,
            "version": None,
            "default_distro": None,
        }
        if sys.platform != "win32":
            return result
        try:
            import subprocess
            # wsl 输出可能是 gbk 编码，用 errors='replace' 避免崩溃
            raw = subprocess.check_output(
                ["wsl", "--version"],
                timeout=10, stderr=subprocess.STDOUT
            )
            out = raw.decode("gbk", errors="replace")
            result["available"] = True
            for line in out.splitlines():
                if "WSL 版本" in line or "WSL version" in line:
                    result["version"] = line.split(":")[-1].strip()
                    break
            # 默认发行版
            try:
                raw2 = subprocess.check_output(
                    ["wsl", "-l", "-v"],
                    timeout=10, stderr=subprocess.STDOUT
                )
                # wsl -l -v 输出可能是 UTF-16 LE，尝试多种编码
                for enc in ["utf-16-le", "gbk", "utf-8"]:
                    try:
                        out2 = raw2.decode(enc)
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                else:
                    out2 = raw2.decode("utf-8", errors="replace")
                for line in out2.splitlines():
                    if "*" in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            result["default_distro"] = parts[1]
                            break
            except Exception:
                pass
        except Exception:
            pass  # WSL 未安装
        return result

    # ===== Docker =====
    def _probe_docker(self) -> Dict[str, Any]:
        """探测 Docker 信息。"""
        result = {
            "available": False,
            "version": None,
            "running": False,
            "container_count": None,
        }
        try:
            import subprocess
            # Docker 版本
            out = subprocess.check_output(
                ["docker", "--version"],
                timeout=10, text=True, stderr=subprocess.STDOUT
            )
            result["available"] = True
            # 解析版本号：Docker version 24.0.6, build ...
            parts = out.split()
            for i, p in enumerate(parts):
                if p == "version" and i + 1 < len(parts):
                    result["version"] = parts[i + 1].rstrip(",")
                    break
            # Docker 运行状态
            try:
                out2 = subprocess.check_output(
                    ["docker", "info", "--format", "{{.ServerVersion}}"],
                    timeout=10, text=True, stderr=subprocess.STDOUT
                )
                result["running"] = bool(out2.strip())
            except Exception:
                result["running"] = False
            # 容器数量
            try:
                out3 = subprocess.check_output(
                    ["docker", "ps", "-a", "--format", "{{.ID}}"],
                    timeout=10, text=True, stderr=subprocess.STDOUT
                )
                result["container_count"] = len([l for l in out3.splitlines() if l.strip()])
            except Exception:
                pass
        except Exception:
            pass  # Docker 未安装
        return result

    # ===== Python =====
    def _probe_python(self) -> Dict[str, Any]:
        """探测 Python 版本（永远成功）。"""
        return {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        }


# 全局单例
system_info = SystemInfo()
