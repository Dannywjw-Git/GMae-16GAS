#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 生成时间统计模块
- 记录每个模型的生成次数、总时长、平均时长
- 用于预算引擎估算生成时间和显存占用
- 从 engine/queue.py 迁移，打破 budget.py <-> queue.py 循环依赖
"""
import json
import os
from core.logger import log_error

# 生成时间统计文件路径
_GEN_STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "resources", "generation_stats.json")


def load_gen_stats() -> dict:
    """读取生成时间统计 {model_id: {count, total_seconds, avg_seconds}}。"""
    try:
        with open(_GEN_STATS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_gen_stats(stats: dict) -> None:
    """保存生成时间统计。"""
    try:
        os.makedirs(os.path.dirname(_GEN_STATS_PATH), exist_ok=True)
        with open(_GEN_STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("gen_stats_save_error", error=e)


def update_gen_stats(model_id: str, seconds: float) -> None:
    """任务完成后更新该模型的生成时间统计。"""
    if not model_id or seconds <= 0 or seconds > 3600:
        return
    stats = load_gen_stats()
    s = stats.get(model_id, {"count": 0, "total_seconds": 0, "avg_seconds": 0})
    s["count"] += 1
    s["total_seconds"] = round(s["total_seconds"] + seconds, 1)
    s["avg_seconds"] = round(s["total_seconds"] / s["count"], 1)
    stats[model_id] = s
    save_gen_stats(stats)
