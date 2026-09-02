#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 核心日志模块
- 结构化 JSON 日志（按天轮转，保留 30 天）
- Windows 桌面 toast 通知（三路通知：UI banner + 日志 + 桌面 toast）
"""
import json
import os
import time
import datetime
import logging
import subprocess
import inspect
from logging.handlers import TimedRotatingFileHandler
from core.registry import registry

# === 日志目录与文件 ===
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "vram-console.log")

# === Logger 初始化 ===
logger = logging.getLogger("gmae")
logger.setLevel(logging.INFO)
if not logger.handlers:
    # 文件日志：按天轮转，保留 30 天
    file_handler = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1, backupCount=30, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    logger.addHandler(file_handler)
    # 控制台日志
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    logger.addHandler(console_handler)


# === EventBus 对接（S2.1）===
_event_bus_instance = None
_event_bus_init_failed = False

def _get_event_bus():
    """延迟获取 EventBus 单例（避免循环导入）。"""
    global _event_bus_instance, _event_bus_init_failed
    if _event_bus_instance is not None:
        return _event_bus_instance
    if _event_bus_init_failed:
        return None
    try:
        from engine.event_bus import event_bus
        _event_bus_instance = event_bus
        return _event_bus_instance
    except Exception:
        _event_bus_init_failed = True
        return None


def _infer_category(event_type: str, kwargs: dict) -> str:
    """根据事件类型和参数推断事件类别（vram/container/model/task/user_action/system/guard）。"""
    event_lower = event_type.lower()
    # 显式指定 category 优先
    if "category" in kwargs:
        cat = str(kwargs["category"]).lower()
        if cat in ("vram", "container", "model", "task", "user_action", "system", "guard"):
            return cat
    # 按关键词推断
    if any(k in event_lower for k in ("vram", "gpu", "memory", "显存", "free_", "release")):
        return "vram"
    if any(k in event_lower for k in ("container", "docker", "容器", "comfyui", "fooocus", "ollama_start", "ollama_stop")):
        return "container"
    if any(k in event_lower for k in ("model", "ollama", "comfy", "load_model", "unload_model", "模型", "scan")):
        return "model"
    if any(k in event_lower for k in ("task", "queue", "任务", "enqueue", "cancel")):
        return "task"
    if any(k in event_lower for k in ("user_action", "audit", "用户", "操作", "service_stop", "service_start", "scene_switch", "scene_")):
        return "user_action"
    if any(k in event_lower for k in ("guard", "evict", "kick", "门卫", "驱逐")):
        return "guard"
    return "system"


def _infer_level(event_type: str, kwargs: dict, is_error: bool = False) -> str:
    """根据事件类型和参数推断事件级别（debug/info/warning/error/critical）。"""
    event_lower = event_type.lower()
    # 显式指定 level 优先
    if "level" in kwargs:
        lvl = str(kwargs["level"]).lower()
        if lvl in ("debug", "info", "warning", "error", "critical"):
            return lvl
    # log_error 调用默认 error
    if is_error:
        if any(k in event_lower for k in ("critical", "fatal", "死机", "溢出", "oom")):
            return "critical"
        return "error"
    # 按关键词推断
    if any(k in event_lower for k in ("critical", "fatal", "死机", "溢出", "oom", "danger")):
        return "critical"
    if any(k in event_lower for k in ("warn", "warning", "注意", "降级", "degraded", "unaccounted")):
        return "warning"
    if any(k in event_lower for k in ("fail", "error", "失败", "异常", "down", "crash")):
        return "error"
    if any(k in event_lower for k in ("debug", "trace", "详细")):
        return "debug"
    return "info"


def _build_message(event_type: str, kwargs: dict) -> str:
    """根据事件类型和参数生成人类可读的中文描述。"""
    # 显式指定 message 优先
    if "message" in kwargs:
        return str(kwargs["message"])
    # 常见事件类型的中文映射
    msg_map = {
        "server_start": "服务启动",
        "server_stop": "服务停止",
        "docker_events_started": "Docker Events 监听启动",
        "user_service_stop": "用户停止服务",
        "user_service_start": "用户启动服务",
        "scene_switch": "切换场景",
        "vram_free": "释放显存",
        "model_load": "加载模型",
        "model_unload": "卸载模型",
        "guard_evicted": "门卫驱逐进程",
        "toast_sent": "发送桌面通知",
    }
    if event_type in msg_map:
        base = msg_map[event_type]
    else:
        base = event_type.replace("_", " ")
    # 附加关键参数
    extras = []
    for key in ("service", "scene", "model", "name", "pid", "container", "level", "result"):
        if key in kwargs and kwargs[key] is not None:
            extras.append(f"{key}={kwargs[key]}")
    if extras:
        return f"{base}（{', '.join(extras)}）"
    return base


def _get_caller_source() -> str:
    """获取调用方模块名（用于 EventBus 的 source 字段）。"""
    try:
        frame = inspect.currentframe()
        # 向上找3层：log_event/log_error → 调用方
        for _ in range(3):
            if frame.f_back:
                frame = frame.f_back
            else:
                break
        filename = frame.f_code.co_filename
        # 提取模块名（去掉路径和扩展名）
        module = os.path.splitext(os.path.basename(filename))[0]
        return module
    except Exception:
        return "unknown"


def _publish_to_event_bus(event_type: str, kwargs: dict, is_error: bool = False) -> None:
    """发布事件到 EventBus（S2.1 对接）。失败静默，不影响日志记录。"""
    try:
        eb = _get_event_bus()
        if eb is None:
            return
        category = _infer_category(event_type, kwargs)
        level = _infer_level(event_type, kwargs, is_error)
        source = _get_caller_source()
        message = _build_message(event_type, kwargs)
        # metadata 排除已用于其他字段的键
        metadata = {k: v for k, v in kwargs.items()
                    if k not in ("category", "level", "message", "ts", "event")}
        eb.record(
            category=category,
            level=level,
            source=source,
            event=event_type,
            message=message,
            metadata=metadata,
        )
    except Exception:
        pass  # EventBus 失败不影响日志记录


def log_event(event_type: str, **kwargs) -> None:
    """记录结构化事件日志，JSON 格式 + 发布到 EventBus（S2.1）"""
    entry = {"ts": datetime.datetime.now().isoformat(), "event": event_type}
    entry.update(kwargs)
    logger.info(json.dumps(entry, ensure_ascii=False))
    # 发布到 EventBus
    _publish_to_event_bus(event_type, kwargs, is_error=False)


def log_error(event_type: str, error=None, **kwargs) -> None:
    """记录错误日志（error 支持位置参数和关键字参数）+ 发布到 EventBus（S2.1）"""
    entry = {"ts": datetime.datetime.now().isoformat(), "event": event_type}
    if error is not None:
        entry["error"] = str(error)
    entry.update(kwargs)
    logger.error(json.dumps(entry, ensure_ascii=False))
    # 发布到 EventBus（error 级别）
    _publish_to_event_bus(event_type, {**kwargs, "error": str(error) if error else None}, is_error=True)


def log_info(event_type: str, **kwargs) -> None:
    """记录信息日志 + 发布到 EventBus（S2.1）"""
    entry = {"ts": datetime.datetime.now().isoformat(), "event": event_type}
    entry.update(kwargs)
    logger.info(json.dumps(entry, ensure_ascii=False))
    # 发布到 EventBus
    _publish_to_event_bus(event_type, kwargs, is_error=False)


# === 桌面 toast 通知 ===
registry.set("toast_enabled", True)
registry.set("toast_cooldown", {})
_TOAST_PS_B64 = "CgBbAFcAaQBuAGQAbwB3AHMALgBVAEkALgBOAG8AdABpAGYAaQBjAGEAdABpAG8AbgBzAC4AVABvAGEAcwB0AE4AbwB0AGkAZgBpAGMAYQB0AGkAbwBuAE0AYQBuAGEAZwBlAHIALAAgAFcAaQBuAGQAbwB3AHMALgBVAEkALgBOAG8AdABpAGYAaQBjAGEAdABpAG8AbgBzACwAIABDAG8AbgB0AGUAbgB0AFQAeQBwAGUAIAA9ACAAVwBpAG4AZABvAHcAcwBSAHUAbgB0AGkAbQBlAF0AIAB8ACAATwB1AHQALQBOAHUAbABsAAoAWwBXAGkAbgBkAG8AdwBzAC4ARABhAHQAYQAuAFgAbQBsAC4ARABvAG0ALgBYAG0AbABEAG8AYwB1AG0AZQBuAHQALAAgAFcAaQBuAGQAbwB3AHMALgBEAGEAdABhAC4AWABtAGwALgBEAG8AbQAuAFgAbQBsAEQAbwBjAHUAbQBlAG4AdAAsACAAQwBvAG4AdABlAG4AdABUAHkAcABlACAAPQAgAFcAaQBuAGQAbwB3AHMAUgB1AG4AdABpAG0AZQBdACAAfAAgAE8AdQB0AC0ATgB1AGwAbAAKACQAdABpAHQAbABlACAAPQAgACQAYQByAGcAcwBbADAAXQAKACQAbQBzAGcAIAA9ACAAJABhAHIAZwBzAFsAMQBdAAoAJAB0AGUAbQBwAGwAYQB0AGUAIAA9ACAAIgA8AHQAbwBhAHMAdAAgAGQAdQByAGEAdABpAG8AbgA9ACcAcwBoAG8AcgB0ACcAPgA8AHYAaQBzAHUAYQBsAD4APABiAGkAbgBkAGkAbgBnACAAdABlAG0AcABsAGEAdABlAD0AJwBUAG8AYQBzAHQARwBlAG4AZQByAGkAYwAnAD4APAB0AGUAeAB0AD4AJAB0AGkAdABsAGUAPAAvAHQAZQB4AHQAPgA8AHQAZQB4AHQAPgAkAG0AcwBnADwALwB0AGUAeAB0AD4APAAvAGIAaQBuAGQAaQBuAGcAPgA8AC8AdgBpAHMAdQBhAGwAPgA8AC8AdABvAGEAcwB0AD4AIgAKACQAeABtAGwAIAA9ACAATgBlAHcALQBPAGIAagBlAGMAdAAgAFcAaQBuAGQAbwB3AHMALgBEAGEAdABhAC4AWABtAGwALgBEAG8AbQAuAFgAbQBsAEQAbwBjAHUAbQBlAG4AdAAKACQAeABtAGwALgBMAG8AYQBkAFgAbQBsACgAJAB0AGUAbQBwAGwAYQB0AGUAKQAKACQAdABvAGEAcwB0ACAAPQAgAE4AZQB3AC0ATwBiAGoAZQBjAHQAIABXAGkAbgBkAG8AdwBzAC4AVQBJAC4ATgBvAHQAaQBmAGkAYwBhAHQAaQBvAG4AcwAuAFQAbwBhAHMAdABOAG8AdABpAGYAaQBjAGEAdABpAG8AbgAgACQAeABtAGwACgBbAFcAaQBuAGQAbwB3AHMALgBVAEkALgBOAG8AdABpAGYAaQBjAGEAdABpAG8AbgBzAC4AVABvAGEAcwB0AE4AbwB0AGkAZgBpAGMAYQB0AGkAbwBuAE0AYQBuAGEAZwBlAHIAXQA6ADoAQwByAGUAYQB0AGUAVABvAGEAcwB0AE4AbwB0AGkAZgBpAGUAcgAoACIARwBNAGEAZQAiACkALgBTAGgAbwB3ACgAJAB0AG8AYQBzAHQAKQAKAA=="


def toast_notify(title: str, message: str, event_type: str = "general", cooldown_s: int = 30) -> bool:
    """发送 Windows 桌面 toast 通知（零依赖，PowerShell Windows.UI.Notifications）。
    三路通知：UI banner + 日志 + 桌面 toast。同类型事件 cooldown_s 秒内只弹一次。"""
    if not registry.get("toast_enabled", True):
        return False
    now = time.time()
    cooldown = registry.get("toast_cooldown", {})
    last = cooldown.get(event_type, 0)
    if now - last < cooldown_s:
        return False
    cooldown[event_type] = now
    registry.set("toast_cooldown", cooldown)
    try:
        import base64 as _b64
        ps = _b64.b64decode(_TOAST_PS_B64).decode('utf-16-le')
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps,
             str(title), str(message)],
            capture_output=True, timeout=10, check=False
        )
        log_event("toast_sent", title=title, message=message, toast_event_type=event_type)
        return True
    except Exception as e:
        log_error("toast_failed", error=e, title=title)
        return False


def set_toast_enabled(enabled: bool):
    """启用/禁用 toast 通知"""
    registry.set("toast_enabled", enabled)
