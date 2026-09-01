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


def log_event(event_type: str, **kwargs) -> None:
    """记录结构化事件日志，JSON 格式"""
    entry = {"ts": datetime.datetime.now().isoformat(), "event": event_type}
    entry.update(kwargs)
    logger.info(json.dumps(entry, ensure_ascii=False))


def log_error(event_type: str, error=None, **kwargs) -> None:
    """记录错误日志（error 支持位置参数和关键字参数）"""
    entry = {"ts": datetime.datetime.now().isoformat(), "event": event_type}
    if error is not None:
        entry["error"] = str(error)
    entry.update(kwargs)
    logger.error(json.dumps(entry, ensure_ascii=False))


def log_info(event_type: str, **kwargs) -> None:
    """记录信息日志"""
    entry = {"ts": datetime.datetime.now().isoformat(), "event": event_type}
    entry.update(kwargs)
    logger.info(json.dumps(entry, ensure_ascii=False))


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
        log_event("toast_sent", title=title, message=message, event_type=event_type)
        return True
    except Exception as e:
        log_error("toast_failed", error=e, title=title)
        return False


def set_toast_enabled(enabled: bool):
    """启用/禁用 toast 通知"""
    registry.set("toast_enabled", enabled)
