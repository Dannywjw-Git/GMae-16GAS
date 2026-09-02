#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警管理器（S3.3）— 告警聚合、静默、升级、历史记录。

核心数据结构：
- active_alerts: {alert_type: {level, message, metadata, first_triggered, last_triggered, count}}
- silenced_alerts: {alert_type: silence_until_timestamp}
- alert_history: deque(maxlen=100)，最近 100 条告警历史

核心功能：
- submit(alert_type, level, message, metadata): 提交告警，自动聚合/静默检查
- silence(alert_type, duration_minutes): 静默某类告警
- resolve(alert_type): 手动解决（移除）活跃告警
- get_active(): 获取活跃告警列表
- get_history(): 获取告警历史
- check_escalation(): 检查并执行告警升级（持续未解决自动升级）
"""

import threading
import time
import json
import os
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path


# 告警级别（数值越大越严重）
ALERT_LEVELS = {"info": 1, "warning": 2, "danger": 3, "critical": 4}
# 升级阈值（秒）：持续超过此时间未解决则升级
ALERT_ESCALATION_THRESHOLD = 600  # 10 分钟
# 最高级别
MAX_ALERT_LEVEL = "critical"


class AlertManager:
    """告警管理器。"""

    def __init__(self, history_limit: int = 100, silence_file: Optional[str] = None):
        self._active: Dict[str, Dict] = {}
        self._silenced: Dict[str, float] = {}  # alert_type -> silence_until (epoch)
        self._history: deque = deque(maxlen=history_limit)
        self._lock = threading.Lock()
        self._silence_file = Path(silence_file) if silence_file else None
        self._load_silenced()

    def submit(self, alert_type: str, level: str, message: str,
               metadata: Optional[Dict] = None) -> Dict:
        """
        提交告警。

        Returns:
            告警对象。如果被静默，返回 {"silenced": True}。
            如果被聚合，返回更新后的告警对象（count+1）。
        """
        now = time.time()

        with self._lock:
            # 检查静默
            if alert_type in self._silenced:
                if now < self._silenced[alert_type]:
                    return {"silenced": True, "alert_type": alert_type}
                else:
                    del self._silenced[alert_type]  # 静默过期

            # 检查聚合
            if alert_type in self._active:
                alert = self._active[alert_type]
                alert["count"] += 1
                alert["last_triggered"] = now
                alert["message"] = message  # 更新为最新消息
                alert["metadata"] = metadata or {}
                # 如果新告警级别更高，升级
                if ALERT_LEVELS.get(level, 0) > ALERT_LEVELS.get(alert["level"], 0):
                    alert["level"] = level
                self._record_history(alert, "aggregated")
                return dict(alert)

            # 新建告警
            alert = {
                "alert_type": alert_type,
                "level": level,
                "message": message,
                "metadata": metadata or {},
                "first_triggered": now,
                "last_triggered": now,
                "count": 1,
                "status": "active"
            }
            self._active[alert_type] = alert
            self._record_history(alert, "new")
            return dict(alert)

    def resolve(self, alert_type: str) -> bool:
        """解决（移除）一个活跃告警。"""
        with self._lock:
            if alert_type in self._active:
                alert = self._active.pop(alert_type)
                self._record_history(alert, "resolved")
                return True
            return False

    def silence(self, alert_type: str, duration_minutes: int = 30) -> Dict:
        """静默某类告警。"""
        until = time.time() + duration_minutes * 60
        with self._lock:
            self._silenced[alert_type] = until
            # 静默时也从活跃中移除
            if alert_type in self._active:
                alert = self._active.pop(alert_type)
                self._record_history(alert, "silenced")
        self._save_silenced()
        return {"alert_type": alert_type, "silenced_until": until, "duration_minutes": duration_minutes}

    def check_escalation(self) -> List[Dict]:
        """
        检查并执行告警升级（应定期调用，如每 60 秒）。
        返回本次升级的告警列表。
        """
        now = time.time()
        escalated = []
        with self._lock:
            for alert_type, alert in list(self._active.items()):
                duration = now - alert["first_triggered"]
                if duration > ALERT_ESCALATION_THRESHOLD:
                    current_level_num = ALERT_LEVELS.get(alert["level"], 1)
                    if current_level_num < ALERT_LEVELS[MAX_ALERT_LEVEL]:
                        # 升级一级
                        new_level_num = current_level_num + 1
                        for name, num in ALERT_LEVELS.items():
                            if num == new_level_num:
                                alert["level"] = name
                                alert["escalated"] = True
                                alert["last_escalated"] = now
                                escalated.append(dict(alert))
                                self._record_history(alert, "escalated")
                                break
                    # 重置 first_triggered，避免每 10 分钟反复升级
                    alert["first_triggered"] = now
        return escalated

    def get_active(self) -> List[Dict]:
        """获取所有活跃告警。"""
        with self._lock:
            now = time.time()
            result = []
            for alert in self._active.values():
                alert_copy = dict(alert)
                alert_copy["duration_seconds"] = int(now - alert["first_triggered"])
                result.append(alert_copy)
            return result

    def get_history(self, limit: int = 50) -> List[Dict]:
        """获取告警历史。"""
        with self._lock:
            return list(self._history)[-limit:]

    def get_silenced(self) -> List[Dict]:
        """获取静默中的告警。"""
        now = time.time()
        with self._lock:
            result = []
            for alert_type, until in self._silenced.items():
                if now < until:
                    result.append({
                        "alert_type": alert_type,
                        "silenced_until": until,
                        "remaining_seconds": int(until - now)
                    })
            return result

    def clear_all(self) -> None:
        """清空所有活跃告警（测试用）。"""
        with self._lock:
            self._active.clear()

    def _record_history(self, alert: Dict, action: str) -> None:
        """记录告警历史（调用方需持有锁）。"""
        self._history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,  # new/aggregated/resolved/silenced/escalated
            "alert_type": alert["alert_type"],
            "level": alert["level"],
            "message": alert["message"],
            "count": alert.get("count", 1)
        })

    def _load_silenced(self) -> None:
        """从文件加载静默配置。"""
        if self._silence_file and self._silence_file.exists():
            try:
                with open(self._silence_file, "r", encoding="utf-8") as f:
                    self._silenced = json.load(f)
            except Exception:
                self._silenced = {}

    def _save_silenced(self) -> None:
        """保存静默配置到文件。"""
        if self._silence_file:
            try:
                # 确保目录存在
                self._silence_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self._silence_file, "w", encoding="utf-8") as f:
                    json.dump(self._silenced, f)
            except Exception:
                pass


# 全局单例
alert_manager = AlertManager(
    history_limit=100,
    silence_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "alerts_silenced.json")
)
