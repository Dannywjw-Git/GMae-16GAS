"""
GMae v0.3.1 — 硬件探测模块（HardwareProbe）

启动时自动探测硬件环境，生成 hardware_profile.json，为动态阈值提供数据基础。
替换 v0.3 中硬编码的 16GB / 1GB 底噪等假设。

设计原则：
- 探测失败不崩溃，返回降级配置（默认16GB + 1GB底噪）
- 底噪测量要求空载（无AI模型加载），否则标记为"可能偏高"
- 多卡数据结构预留，MVP 只管理单卡（gpu_index=0）
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from typing import Optional
from core.logger import logger


@dataclass
class GPUInfo:
    index: int
    name: str
    vram_total_mb: int
    driver_version: str
    cuda_version: str = ""


@dataclass
class HardwareProfile:
    gpus: list
    primary_gpu_index: int
    base_noise_mb: int
    base_noise_confidence: str  # "high" / "medium" / "low" / "estimated"
    ram_total_mb: int
    os_type: str  # "windows" / "linux" / "unknown"
    docker_available: bool
    detected_at: int
    profile_version: str = "1.0"


def _run_cmd(args: list, timeout: int = 10) -> tuple[int, str]:
    """运行命令，返回 (returncode, stdout)。失败返回 (-1, "")。"""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip()
    except Exception:
        return -1, ""


def probe_gpus() -> list:
    """
    调用 nvidia-smi 探测 GPU 列表。
    返回 [GPUInfo]，失败返回空列表。
    """
    gpus = []
    # 探测基本信息
    rc, out = _run_cmd([
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,driver_version",
        "--format=csv,noheader,nounits"
    ], 10)
    if rc != 0 or not out:
        return gpus
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            idx = int(parts[0])
            name = parts[1]
            vram_mb = int(float(parts[2]))
            driver = parts[3] if len(parts) > 3 else ""
            gpus.append(GPUInfo(
                index=idx,
                name=name,
                vram_total_mb=vram_mb,
                driver_version=driver
            ))
        except (ValueError, IndexError):
            continue
    return gpus


def _get_current_vram_used_mb(gpu_index: int = 0) -> Optional[int]:
    """获取当前 GPU 显存使用量（MB）。失败返回 None。"""
    rc, out = _run_cmd([
        "nvidia-smi",
        f"--id={gpu_index}",
        "--query-gpu=memory.used",
        "--format=csv,noheader,nounits"
    ], 5)
    if rc != 0 or not out:
        return None
    try:
        return int(float(out.strip()))
    except ValueError:
        return None


def measure_base_noise(gpu_index: int = 0, samples: int = 5, interval: float = 1.0,
                       require_idle: bool = True) -> tuple[int, str]:
    """
    测量显存底噪：空载时连续 samples 次测量取平均。

    Args:
        gpu_index: 目标 GPU
        samples: 采样次数
        interval: 采样间隔（秒）
        require_idle: 是否要求空载（检测 ollama/comfyui 无模型加载）

    Returns:
        (noise_mb, confidence)
        confidence: "high"（空载+多次测量稳定）/ "medium"（有轻微负载）/
                    "low"（有AI模型加载，底噪可能偏高）/ "estimated"（测量失败，用默认值）
    """
    # 检查是否空载（ollama ps 为空 + comfyui torch_vram < 500MB）
    idle = True
    if require_idle:
        # 检查 ollama
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=2) as r:
                d = json.loads(r.read().decode("utf-8"))
                if d.get("models"):
                    idle = False
        except Exception:
            pass  # ollama 未运行也算空载
        # 检查 comfyui
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2) as r:
                d = json.loads(r.read().decode("utf-8"))
                dev = (d.get("devices") or [{}])[0]
                torch_total = dev.get("torch_vram_total") or 0
                torch_free = dev.get("torch_vram_free") or 0
                if (torch_total - torch_free) > 500 * 1024 * 1024:  # >500MB
                    idle = False
        except Exception:
            pass  # comfyui 未运行也算空载

    readings = []
    for _ in range(samples):
        used = _get_current_vram_used_mb(gpu_index)
        if used is not None:
            readings.append(used)
        time.sleep(interval)

    if not readings:
        # 测量失败，用默认值 1200MB（v0.3 观察值）
        return 1200, "estimated"

    noise = int(sum(readings) / len(readings))
    # 稳定性判断：标准差 < 100MB 视为稳定
    if len(readings) >= 3:
        mean = sum(readings) / len(readings)
        variance = sum((x - mean) ** 2 for x in readings) / len(readings)
        std = variance ** 0.5
        stable = std < 100
    else:
        stable = True

    if idle and stable:
        confidence = "high"
    elif idle:
        confidence = "medium"
    else:
        confidence = "low"

    return noise, confidence


def probe_ram() -> int:
    """探测总内存（MB）。失败返回 0。"""
    if os.name == "nt":
        # Windows: wmic
        rc, out = _run_cmd(["wmic", "ComputerSystem", "get", "TotalPhysicalMemory", "/value"], 10)
        if rc == 0 and out:
            for line in out.splitlines():
                if "=" in line:
                    try:
                        return int(int(line.split("=")[1].strip()) / (1024 * 1024))
                    except ValueError:
                        pass
    else:
        # Linux: /proc/meminfo
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
        except Exception:
            pass
    return 0


def probe_os() -> str:
    """探测操作系统类型。"""
    if os.name == "nt":
        return "windows"
    if os.name == "posix":
        return "linux"
    return "unknown"


def probe_docker() -> bool:
    """检测 Docker 是否可用。"""
    rc, _ = _run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"], 10)
    return rc == 0


def generate_profile(gpu_index: int = 0, measure_noise: bool = True) -> HardwareProfile:
    """
    生成完整硬件配置文件。

    Args:
        gpu_index: 主 GPU 索引（多卡时指定管理哪张）
        measure_noise: 是否测量底噪（False 时用估算值，启动更快）

    Returns:
        HardwareProfile
    """
    gpus = probe_gpus()
    primary = gpu_index if any(g.index == gpu_index for g in gpus) else (gpus[0].index if gpus else 0)

    if measure_noise and gpus:
        noise_mb, confidence = measure_base_noise(primary)
    else:
        noise_mb = 1200  # v0.3 观察默认值
        confidence = "estimated"

    profile = HardwareProfile(
        gpus=[asdict(g) for g in gpus],
        primary_gpu_index=primary,
        base_noise_mb=noise_mb,
        base_noise_confidence=confidence,
        ram_total_mb=probe_ram(),
        os_type=probe_os(),
        docker_available=probe_docker(),
        detected_at=int(time.time()),
    )
    return profile


def save_profile(profile: HardwareProfile, path: str) -> bool:
    """保存硬件配置文件到 JSON。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(profile), f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_profile(path: str) -> Optional[HardwareProfile]:
    """加载已保存的硬件配置文件。失败返回 None。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return HardwareProfile(**d)
    except Exception:
        return None


def get_profile(path: str, force_refresh: bool = False) -> HardwareProfile:
    """
    获取硬件配置：优先加载已保存的，不存在或强制刷新时重新探测。
    这是 server.py 应该调用的入口函数。
    """
    if not force_refresh:
        existing = load_profile(path)
        if existing:
            return existing
    profile = generate_profile()
    save_profile(profile, path)
    return profile


# === 独立运行：python hardware_probe.py ===
if __name__ == "__main__":
    import sys
    profile_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "resources", "hardware_profile.json"
    )
    logger.info("GMae 硬件探测中...")
    p = generate_profile(measure_noise=True)
    logger.info(f"\nGPU: {p.gpus[0]['name'] if p.gpus else '未检测到'}")
    logger.info(f"显存: {p.gpus[0]['vram_total_mb'] if p.gpus else 0} MB")
    logger.info(f"底噪: {p.base_noise_mb} MB (置信度: {p.base_noise_confidence})")
    logger.info(f"内存: {p.ram_total_mb} MB")
    logger.info(f"系统: {p.os_type}")
    logger.info(f"Docker: {'可用' if p.docker_available else '不可用'}")
    if save_profile(p, profile_path):
        logger.info(f"\n配置已保存: {profile_path}")
    else:
        logger.info(f"\n保存失败: {profile_path}")
