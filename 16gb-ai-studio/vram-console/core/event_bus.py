#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件总线模块（S2.1 事件标准化 + EventBus）

统一事件格式，提供事件记录、查询、时间线 API 的数据基础。
是 S2 事件关联引擎、S3 告警降噪、S4 前端诊断中心的共享数据层。

事件格式（统一，与接口契约 §3.1 / 数据结构定义 §2.1 一致）：
{
    "timestamp": "2026-09-01T12:00:00.123456+00:00",  # ISO 8601 UTC
    "category": "vram",  # 枚举：vram/container/model/task/user_action/system/guard
    "level": "info",  # 枚举：debug/info/warning/error/critical
    "source": "qos_engine",  # 产生事件的模块名
    "event": "vram_danger_critical",  # 事件类型名（snake_case）
    "message": "显存剩余 0.8GB，进入 critical 状态",  # 人类可读描述
    "metadata": {...}  # 附加数据（任意 dict）
}

核心类：
- EventBus: 事件记录与查询，内存环形缓冲区（最近 1000 条）+ 持久化到 logs/events.jsonl

使用方式：
    from core.event_bus import event_bus

    # 记录事件
    event_bus.record(
        category="vram",
        level="critical",
        source="qos_engine",
        event="vram_danger_critical",
        message="显存剩余 0.8GB，进入 critical 状态",
        metadata={"free_mb": 800, "used_mb": 15500}
    )

    # 查询事件时间线
    events = event_bus.query(category="vram", level="critical", limit=50)

    # 统计最近 5 分钟各类别事件数量
    stats = event_bus.count_by_category(seconds=300)
"""
import json
import time
import threading
from collections import deque
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path


# 事件类别枚举（7 类，与数据结构定义 §3.1 一致）
EVENT_CATEGORIES = {"vram", "container", "model", "task", "user_action", "system", "guard"}
# 事件级别枚举（5 级，与数据结构定义 §3.2 一致）
EVENT_LEVELS = {"debug", "info", "warning", "error", "critical"}

# === 兼容旧 events.py 的级别常量 ===
LEVEL_DEBUG = "debug"
LEVEL_INFO = "info"
LEVEL_WARNING = "warning"
LEVEL_ERROR = "error"
LEVEL_CRITICAL = "critical"


class EventBus:
    """事件总线。

    内存环形缓冲区（最近 1000 条）+ 持久化到 logs/events.jsonl。
    线程安全，支持多维度过滤查询。
    """

    def __init__(self, max_events: int = 1000, log_file: Optional[str] = None):
        """初始化事件总线。

        Args:
            max_events: 内存环形缓冲区最大事件数，默认 1000
            log_file: 事件持久化文件路径，默认 logs/events.jsonl
        """
        self._events: deque = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._max_events = max_events

        # 持久化文件路径
        if log_file is None:
            # 默认路径：项目根目录下 logs/events.jsonl
            # engine/event_bus.py → 上两级是 vram-console 根目录
            base_dir = Path(__file__).resolve().parent.parent
            self._log_file = base_dir / "logs" / "events.jsonl"
        else:
            self._log_file = Path(log_file)

        # 确保日志目录存在
        try:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_error("exception_suppressed", error=e, context="event_bus.py:87")

        # 启动时从持久化文件加载最近的事件（最多 max_events 条）
        self._load_from_file()

    def record(self, category: str, level: str, source: str, event: str,
               message: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """记录一个事件。

        Args:
            category: 事件类别（vram/container/model/task/user_action/system/guard）
            level: 事件级别（debug/info/warning/error/critical）
            source: 产生事件的模块名
            event: 事件类型名（snake_case）
            message: 人类可读描述（中文，1 句话）
            metadata: 附加数据（任意 dict，可为 None）

        Returns:
            记录的事件对象
        """
        # 类别/级别校验：未知值归为 system/info
        if category not in EVENT_CATEGORIES:
            category = "system"
        if level not in EVENT_LEVELS:
            level = "info"

        evt = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "level": level,
            "source": source,
            "event": event,
            "message": message,
            "metadata": metadata or {},
        }

        # 写入内存环形缓冲区
        with self._lock:
            self._events.append(evt)

        # 持久化到日志文件（同步追加，简单可靠）
        self._append_to_file(evt)

        return evt

    def query(self, start_time: Optional[str] = None, end_time: Optional[str] = None,
              category: Optional[str] = None, level: Optional[str] = None,
              source: Optional[str] = None, event: Optional[str] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        """查询事件，按时间倒序。

        Args:
            start_time: ISO 8601 起始时间（可选，含）
            end_time: ISO 8601 结束时间（可选，含）
            category: 事件类别过滤（可选）
            level: 事件级别过滤（可选）
            source: 事件来源过滤（可选）
            event: 事件类型过滤（可选，精确匹配）
            limit: 返回数量，默认 100，最大 500

        Returns:
            事件列表（按时间倒序）
        """
        # limit 上限保护
        limit = min(max(limit, 1), 500)

        with self._lock:
            events = list(self._events)

        # 多维度过滤
        if start_time:
            events = [e for e in events if e["timestamp"] >= start_time]
        if end_time:
            events = [e for e in events if e["timestamp"] <= end_time]
        if category:
            events = [e for e in events if e["category"] == category]
        if level:
            events = [e for e in events if e["level"] == level]
        if source:
            events = [e for e in events if e["source"] == source]
        if event:
            events = [e for e in events if e["event"] == event]

        # 按时间倒序
        events.sort(key=lambda e: e["timestamp"], reverse=True)
        return events[:limit]

    def get_recent(self, seconds: int = 300, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取最近 N 秒的事件。

        Args:
            seconds: 时间窗（秒），默认 300（5 分钟）
            category: 事件类别过滤（可选）

        Returns:
            事件列表（按时间倒序）
        """
        cutoff = datetime.now(timezone.utc).timestamp() - seconds
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        return self.query(start_time=cutoff_iso, category=category, limit=500)

    def count_by_category(self, seconds: int = 300) -> Dict[str, int]:
        """统计最近 N 秒各类别事件数量。

        Args:
            seconds: 时间窗（秒），默认 300（5 分钟）

        Returns:
            {category: count} 字典，包含所有 7 个类别（无事件的类别为 0）
        """
        recent = self.get_recent(seconds=seconds)
        counts = {cat: 0 for cat in sorted(EVENT_CATEGORIES)}
        for e in recent:
            counts[e["category"]] = counts.get(e["category"], 0) + 1
        return counts

    def get_all(self) -> List[Dict[str, Any]]:
        """获取所有内存中的事件（按时间倒序）。"""
        with self._lock:
            events = list(self._events)
        events.sort(key=lambda e: e["timestamp"], reverse=True)
        return events

    def clear(self) -> None:
        """清空内存中的事件（不删除持久化文件）。"""
        with self._lock:
            self._events.clear()

    # === 兼容旧 events.py 接口 ===

    def log(self, event_type: str, level: str = LEVEL_INFO, service: str = "system",
            message: str = "", metadata: Optional[Dict[str, Any]] = None,
            related_metrics: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """兼容旧 events.log 接口，自动转换为新格式。

        Args:
            event_type: 事件类型（旧），映射为新格式的 event 字段
            level: 级别（旧），映射为新格式的 level 字段
            service: 服务名（旧），映射为新格式的 source 字段
            message: 人类可读消息
            metadata: 附加元数据
            related_metrics: 关联指标（合并到 metadata）
            **kwargs: 其他参数（合并到 metadata.legacy_fields）
        """
        # 合并 metadata 和 related_metrics
        meta = dict(metadata or {})
        if related_metrics:
            meta["related_metrics"] = related_metrics
        if kwargs:
            meta["legacy_fields"] = kwargs

        # 推断 category（旧接口没有 category，根据 service/event_type 推断）
        category = "system"
        if service in ("vram", "gpu", "qos", "guard"):
            category = "vram"
        elif service in ("docker", "container", "comfyui", "ollama"):
            category = "container" if service == "docker" else "model"
        elif "model" in event_type or "ollama" in event_type or "comfy" in event_type:
            category = "model"
        elif "task" in event_type or "queue" in event_type:
            category = "task"
        elif "user" in event_type or "action" in event_type:
            category = "user_action"
        elif "guard" in event_type or "evict" in event_type:
            category = "guard"

        return self.record(
            category=category,
            level=level,
            source=service,
            event=event_type,
            message=message,
            metadata=meta,
        )

    def query_legacy(self, service: Optional[str] = None, level: Optional[str] = None,
                     event_type: Optional[str] = None, keyword: Optional[str] = None,
                     from_ts: Optional[float] = None, to_ts: Optional[float] = None,
                     limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """兼容旧 events.query 接口。

        旧接口参数：service, level, event_type, keyword, from_ts, to_ts, limit, offset
        新接口参数：start_time, end_time, category, level, source, event, limit
        """
        from datetime import datetime, timezone

        start_time = None
        end_time = None
        if from_ts:
            start_time = datetime.fromtimestamp(from_ts, tz=timezone.utc).isoformat()
        if to_ts:
            end_time = datetime.fromtimestamp(to_ts, tz=timezone.utc).isoformat()

        results = self.query(
            start_time=start_time,
            end_time=end_time,
            level=level,
            source=service,
            event=event_type,
            limit=limit + offset,  # 多取 offset 条用于分页
        )

        # 关键词过滤（新接口不支持，这里后处理）
        if keyword:
            import json
            filtered = []
            for evt in results:
                search_text = (
                    evt.get("message", "")
                    + " " + json.dumps(evt.get("metadata", {}), ensure_ascii=False)
                    + " " + evt.get("event", "")
                )
                if keyword.lower() in search_text.lower():
                    filtered.append(evt)
            results = filtered

        return results[offset:offset + limit]

    def get_stats(self) -> Dict[str, Any]:
        """兼容旧 events.get_stats 接口，返回事件统计。"""
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
                svc = evt.get("source", "unknown")
                stats["by_service"][svc] = stats["by_service"].get(svc, 0) + 1
        return stats

    def get_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """兼容旧 events.get_alerts 接口，返回告警事件（warning及以上）。"""
        alerts = []
        with self._lock:
            for evt in reversed(self._events):
                if evt.get("level") in (LEVEL_WARNING, LEVEL_ERROR, LEVEL_CRITICAL):
                    alerts.append(evt)
                    if len(alerts) >= limit:
                        break
        return alerts

    def _append_to_file(self, evt: Dict[str, Any]) -> None:
        """追加事件到持久化文件。"""
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(evt, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 持久化失败不影响内存记录

    def _load_from_file(self) -> None:
        """启动时从持久化文件加载最近的事件（最多 max_events 条）。"""
        try:
            if not self._log_file.exists():
                return
            # 读取文件最后 max_events 行
            with open(self._log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # 只取最后 max_events 条
            for line in lines[-self._max_events:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    # 基本校验：必须有 timestamp/category/event
                    if all(k in evt for k in ("timestamp", "category", "event")):
                        with self._lock:
                            self._events.append(evt)
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass  # 加载失败不影响功能


# 全局单例（模块导入时创建，自动加载持久化事件）
event_bus = EventBus(
    max_events=1000,
    log_file=None,  # 使用默认路径 logs/events.jsonl
)

# === 兼容旧 events.py 的全局别名 ===
# 旧代码使用 `from core.events import events`，现在可以用 `from core.event_bus import events`
events = event_bus
