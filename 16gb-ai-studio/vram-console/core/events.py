#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 结构化事件系统
- 内存环形缓冲（500条）
- 持久化 events.jsonl（最近10000条）
- 支持按 service/level/time/keyword 查询
- 与现有 log_event 兼容（升级后自动记录到事件系统）
"""
import json
import os
import time
import threading
import datetime
from collections import deque
from typing import Optional, List, Dict, Any

# === 配置 ===
EVENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(EVENT_DIR, exist_ok=True)
EVENT_FILE = os.path.join(EVENT_DIR, "events.jsonl")

MAX_MEMORY_EVENTS = 500
MAX_FILE_EVENTS = 10000

# 事件级别
LEVEL_INFO = "info"
LEVEL_WARNING = "warning"
LEVEL_ERROR = "error"
LEVEL_CRITICAL = "critical"

VALID_LEVELS = {LEVEL_INFO, LEVEL_WARNING, LEVEL_ERROR, LEVEL_CRITICAL}


class EventSystem:
    """结构化事件系统（单例）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._events = deque(maxlen=MAX_MEMORY_EVENTS)
        self._file_lock = threading.Lock()
        self._load_from_file()

    def _load_from_file(self):
        """从文件加载历史事件（只加载最近的）"""
        if not os.path.exists(EVENT_FILE):
            return
        try:
            lines = []
            with open(EVENT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(line)
            # 只加载最近 MAX_MEMORY_EVENTS 条
            for line in lines[-MAX_MEMORY_EVENTS:]:
                try:
                    evt = json.loads(line)
                    self._events.append(evt)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"[events] load error: {e}")

    def _append_to_file(self, event: Dict[str, Any]):
        """追加事件到文件（滚动截断）"""
        with self._file_lock:
            try:
                # 先检查文件大小，超过阈值则截断
                if os.path.exists(EVENT_FILE):
                    with open(EVENT_FILE, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    if len(lines) >= MAX_FILE_EVENTS:
                        # 保留最近的一半
                        lines = lines[-(MAX_FILE_EVENTS // 2):]
                        with open(EVENT_FILE, "w", encoding="utf-8") as f:
                            f.writelines(lines)

                with open(EVENT_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"[events] file append error: {e}")

    def log(
        self,
        event_type: str,
        level: str = LEVEL_INFO,
        service: str = "system",
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        related_metrics: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        记录结构化事件

        Args:
            event_type: 事件类型（如 scene_switch, vram_oom, service_down）
            level: 级别 info/warning/error/critical
            service: 来源服务（如 scene, docker, comfyui, ollama）
            message: 人类可读的消息
            metadata: 附加元数据
            related_metrics: 关联的指标快照（如 gpu_free_mb, queue_length）
            **kwargs: 兼容旧 log_event 的额外字段
        """
        if level not in VALID_LEVELS:
            level = LEVEL_INFO

        event = {
            "id": f"evt_{int(time.time() * 1000)}_{id(self) % 10000}",
            "ts": datetime.datetime.now().isoformat(),
            "timestamp": time.time(),
            "event_type": event_type,
            "level": level,
            "service": service,
            "message": message,
            "metadata": metadata or {},
            "related_metrics": related_metrics or {},
        }
        # 合并旧格式的额外字段
        if kwargs:
            event["legacy_fields"] = kwargs

        with self._lock:
            self._events.append(event)
        self._append_to_file(event)

        # 严重事件同时写 logger
        if level in (LEVEL_ERROR, LEVEL_CRITICAL):
            try:
                from core.logger import logger
                logger.error(f"[{service}] {event_type}: {message}")
            except Exception:
                pass

        return event

    def query(
        self,
        service: Optional[str] = None,
        level: Optional[str] = None,
        event_type: Optional[str] = None,
        keyword: Optional[str] = None,
        from_ts: Optional[float] = None,
        to_ts: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        查询事件

        Args:
            service: 按服务筛选
            level: 按级别筛选
            event_type: 按事件类型筛选
            keyword: 在 message/metadata 中搜索
            from_ts: 起始时间戳
            to_ts: 结束时间戳
            limit: 返回数量（默认100，最大500）
            offset: 偏移量
        """
        limit = min(limit, 500)
        results = []

        with self._lock:
            events_list = list(self._events)

        # 倒序遍历（最新的在前）
        for evt in reversed(events_list):
            if service and evt.get("service") != service:
                continue
            if level and evt.get("level") != level:
                continue
            if event_type and evt.get("event_type") != event_type:
                continue
            if from_ts and evt.get("timestamp", 0) < from_ts:
                continue
            if to_ts and evt.get("timestamp", 0) > to_ts:
                continue
            if keyword:
                search_text = (
                    evt.get("message", "")
                    + " " + json.dumps(evt.get("metadata", {}), ensure_ascii=False)
                    + " " + evt.get("event_type", "")
                )
                if keyword.lower() not in search_text.lower():
                    continue
            results.append(evt)

        return results[offset:offset + limit]

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的事件"""
        return self.query(limit=limit)

    def get_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取告警事件（warning及以上）"""
        alerts = []
        with self._lock:
            for evt in reversed(self._events):
                if evt.get("level") in (LEVEL_WARNING, LEVEL_ERROR, LEVEL_CRITICAL):
                    alerts.append(evt)
                    if len(alerts) >= limit:
                        break
        return alerts

    def get_stats(self) -> Dict[str, Any]:
        """获取事件统计"""
        stats = {
            "total": len(self._events),
            "by_level": {LEVEL_INFO: 0, LEVEL_WARNING: 0, LEVEL_ERROR: 0, LEVEL_CRITICAL: 0},
            "by_service": {},
        }
        with self._lock:
            for evt in self._events:
                lvl = evt.get("level", LEVEL_INFO)
                if lvl in stats["by_level"]:
                    stats["by_level"][lvl] += 1
                svc = evt.get("service", "unknown")
                stats["by_service"][svc] = stats["by_service"].get(svc, 0) + 1
        return stats

    def clear(self):
        """清空内存事件（不删文件）"""
        with self._lock:
            self._events.clear()


# 全局单例
events = EventSystem()


# === 兼容旧接口的便捷函数 ===

def log_event(event_type: str, **kwargs) -> Dict[str, Any]:
    """兼容旧 log_event 接口，自动升级为结构化事件"""
    return events.log(
        event_type=event_type,
        level=kwargs.pop("level", LEVEL_INFO),
        service=kwargs.pop("service", "system"),
        message=kwargs.pop("message", ""),
        metadata=kwargs.pop("metadata", None),
        related_metrics=kwargs.pop("related_metrics", None),
        **kwargs
    )


def log_warning(event_type: str, message: str = "", service: str = "system", **kwargs):
    """记录警告事件"""
    return events.log(event_type, level=LEVEL_WARNING, service=service, message=message, **kwargs)


def log_error_event(event_type: str, message: str = "", service: str = "system", error=None, **kwargs):
    """记录错误事件"""
    metadata = kwargs.pop("metadata", {})
    if error is not None:
        metadata["error"] = str(error)
    return events.log(event_type, level=LEVEL_ERROR, service=service, message=message, metadata=metadata, **kwargs)


def log_critical(event_type: str, message: str = "", service: str = "system", **kwargs):
    """记录严重事件"""
    return events.log(event_type, level=LEVEL_CRITICAL, service=service, message=message, **kwargs)
