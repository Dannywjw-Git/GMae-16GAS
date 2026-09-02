#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 核心配置模块
- 服务端口/主机/基础路径
- API Token 认证
- 资源注册表（registry.json）
- 硬件探测与动态阈值
"""
import json
import os
from .logger import log_event, log_error

# === 服务配置 ===
PORT = int(os.environ.get("VRAM_CONSOLE_PORT", "8787"))
HOST = os.environ.get("VRAM_CONSOLE_HOST", "0.0.0.0")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# === 前端版本控制 ===
FRONTEND_VERSION = os.environ.get("FRONTEND_VERSION", "v2").lower()
WEB_DIR = os.path.join(BASE_DIR, "web")
LEGACY_HTML = os.path.join(BASE_DIR, "legacy", "v1-index.html")

# === 脚本路径 ===
GPU_RELEASE_PS1 = os.environ.get("GPU_RELEASE_PS1",
    os.path.join(BASE_DIR, "..", "scripts", "vram_cleanup.ps1"))
GAME_ON_PS1 = os.environ.get("GAME_ON_PS1",
    os.path.join(BASE_DIR, "..", "scripts", "game-on.ps1"))

# === API Token ===
def _load_token() -> str:
    """Token 认证配置：优先环境变量 VRAM_CONSOLE_TOKEN，其次本地 .api_token 文件。"""
    env = os.environ.get("VRAM_CONSOLE_TOKEN", "")
    if env:
        return env
    try:
        with open(os.path.join(BASE_DIR, ".api_token"), "r", encoding="ascii") as f:
            return f.read().strip()
    except Exception:
        return ""

API_TOKEN = _load_token()

# === 资源注册表 ===
REGISTRY_PATH = os.path.join(BASE_DIR, "resources", "registry.json")


def load_registry() -> dict:
    """加载资源注册表，失败时返回空 dict（使用硬编码兜底）"""
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_error("registry_load_failed", error=e, path=REGISTRY_PATH)
        return {}


REGISTRY = load_registry()

# 从注册表读取配置
OLLAMA_CONTAINER = REGISTRY.get("ollama", {}).get("container", "ollama")
BIG_MODELS = [m["id"] for m in REGISTRY.get("ollama", {}).get("models", [])
              if m.get("category") == "llm"] or ["qwen3.5:9b", "qwen3:0.6b", "qwythos-9b:q4km", "darkidol-8b:q4km"]

log_event("registry_loaded", models_count=len(BIG_MODELS), container=OLLAMA_CONTAINER)

# === 显存计算常量（消除魔法数字）===
VRAM_BASELINE_NOISE_MB = 1200          # 系统底噪（桌面+驱动+CUDA context）
COMFY_MODEL_RESIDENT_THRESHOLD_MB = 1024  # ComfyUI torch 显存超过此值视为模型已常驻
VRAM_DIFF_THRESHOLD_MB = 1000          # 显存账本双源差异阈值（超过视为加载/释放中）
VRAM_LOADING_SPEED_MB_PER_S = 500      # 模型加载速度估算（MB/s）
VRAM_LOADING_OVERHEAD_MB = 2000        # 加载进度估算的额外开销（MB）
VRAM_DESKTOP_PROCESS_MIN_MB = 100      # 桌面进程建议结束的最小显存占用
VRAM_UNKNOWN_MIN_MB = 500              # 未归因显存建议提示的最小值

# === 硬件探测与动态阈值 ===
HARDWARE_PROFILE_PATH = os.path.join(BASE_DIR, "resources", "hardware_profile.json")
_dyn_thresholds = None

try:
    from core import hardware_probe
    from core import thresholds as thresholds_mod
    _V031_MODULES = True
except ImportError as _e:
    _V031_MODULES = False
    log_error("v031_modules_import_failed", error=_e)

if _V031_MODULES:
    try:
        if os.path.exists(HARDWARE_PROFILE_PATH):
            _dyn_thresholds = thresholds_mod.get_thresholds(HARDWARE_PROFILE_PATH)
            log_event("hardware_profile_loaded",
                      vram_total_gb=_dyn_thresholds.vram_total_mb / 1024,
                      base_noise_gb=round(_dyn_thresholds.base_noise_mb / 1024, 2),
                      source="cached")
        else:
            _profile = hardware_probe.generate_profile(measure_noise=False)
            hardware_probe.save_profile(_profile, HARDWARE_PROFILE_PATH)
            _dyn_thresholds = thresholds_mod.get_thresholds(HARDWARE_PROFILE_PATH)
            log_event("hardware_profile_created",
                      vram_total_gb=_profile.gpus[0]["vram_total_mb"] / 1024 if _profile.gpus else 16,
                      source="auto_detect")
    except Exception as _e:
        log_error("hardware_init_failed", error=_e)
        _dyn_thresholds = None


def get_dyn_thresholds():
    """获取动态阈值实例。无硬件配置时返回 None，调用方用硬编码兜底。"""
    return _dyn_thresholds


def get_threshold_value(attr: str, fallback: int) -> int:
    """安全获取动态阈值，失败返回 fallback。"""
    if _dyn_thresholds is not None:
        try:
            return int(getattr(_dyn_thresholds, attr))
        except Exception as e:
            log_error("exception_suppressed", error=e, context="config.py:118")
    return fallback
