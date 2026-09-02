#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健康度评分引擎（S5）— 多维度健康分计算

核心概念：
- HealthDimension: 一个健康维度（GPU/容器/服务/告警），含分数(0-100)、状态、详情
- HealthReport: 健康报告，含各维度分数 + 综合健康分 + 建议

评分规则：
- 90-100: excellent（优秀，绿色）
- 70-89: good（良好，青色）
- 50-69: fair（一般，黄色）
- 30-49: poor（较差，橙色）
- 0-29: critical（危险，红色）
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class HealthDimension:
    """健康维度。"""
    id: str  # 维度 ID，如 gpu_vram
    name: str  # 维度名称
    score: int  # 分数 0-100
    status: str  # excellent/good/fair/poor/critical
    description: str  # 描述
    metrics: Dict[str, Any] = field(default_factory=dict)  # 详细指标
    issues: List[str] = field(default_factory=list)  # 问题列表
    suggestions: List[str] = field(default_factory=list)  # 建议列表


@dataclass
class HealthReport:
    """健康报告。"""
    overall_score: int  # 综合健康分 0-100
    overall_status: str  # 综合状态
    dimensions: List[HealthDimension] = field(default_factory=list)
    generated_at: str = ""
    summary: str = ""  # 摘要
    top_issues: List[str] = field(default_factory=list)  # 主要问题
    top_suggestions: List[str] = field(default_factory=list)  # 主要建议


class HealthScoreEngine:
    """健康度评分引擎。"""

    def __init__(self):
        self._weights = {
            "gpu_vram": 0.35,      # GPU 显存权重最高
            "containers": 0.25,    # 容器状态
            "services": 0.20,      # 服务响应
            "alerts": 0.20,        # 告警状态
        }

    def _score_to_status(self, score: int) -> str:
        """分数转状态。"""
        if score >= 90:
            return "excellent"
        elif score >= 70:
            return "good"
        elif score >= 50:
            return "fair"
        elif score >= 30:
            return "poor"
        else:
            return "critical"

    def _evaluate_gpu_vram(self, status: Dict) -> HealthDimension:
        """评估 GPU 显存健康度。"""
        gpu = status.get("gpu", {}) or {}
        ledger = status.get("vram_ledger", {}) or {}

        total_mb = gpu.get("total_mb", 16384)
        used_mb = gpu.get("used_mb", 0)
        free_mb = gpu.get("free_mb", total_mb - used_mb)
        usage_pct = (used_mb / total_mb * 100) if total_mb > 0 else 0

        danger_level = ledger.get("danger_level", "safe")
        ledger_state = ledger.get("state", "consistent")

        # 评分逻辑
        score = 100
        issues = []
        suggestions = []

        if usage_pct > 90:
            score -= 50
            issues.append(f"显存使用率 {usage_pct:.0f}%，接近满载")
            suggestions.append("立即释放显存，停止非必要任务")
        elif usage_pct > 80:
            score -= 30
            issues.append(f"显存使用率 {usage_pct:.0f}%，较高")
            suggestions.append("考虑释放未使用模型，避免同时运行多个大模型")
        elif usage_pct > 70:
            score -= 15
            issues.append(f"显存使用率 {usage_pct:.0f}%，偏高")
            suggestions.append("关注显存变化，必要时释放部分模型")
        elif usage_pct > 50:
            score -= 5

        if danger_level == "critical":
            score -= 40
            issues.append("显存危险等级：critical，随时可能 OOM 死机")
            suggestions.append("立即执行一键释放，切换到 idle 场景")
        elif danger_level == "danger":
            score -= 25
            issues.append("显存危险等级：danger")
            suggestions.append("尽快释放显存，避免启动新任务")
        elif danger_level == "warning":
            score -= 10
            issues.append("显存危险等级：warning")

        if ledger_state == "inconsistent":
            score -= 10
            issues.append("显存账本数据不一致（nvidia-smi 与模型明细差异大）")

        score = max(0, min(100, score))

        return HealthDimension(
            id="gpu_vram",
            name="GPU 显存",
            score=score,
            status=self._score_to_status(score),
            description=f"显存使用率 {usage_pct:.0f}%，空闲 {free_mb/1024:.1f}GB",
            metrics={
                "total_mb": total_mb,
                "used_mb": used_mb,
                "free_mb": free_mb,
                "usage_pct": round(usage_pct, 1),
                "danger_level": danger_level,
                "ledger_state": ledger_state,
            },
            issues=issues,
            suggestions=suggestions,
        )

    def _evaluate_containers(self, status: Dict) -> HealthDimension:
        """评估容器健康度。"""
        containers = status.get("containers", {}) or {}
        all_containers = containers.get("all", []) or []

        # 处理字符串类型（容器名称）或字典类型
        def get_container_name(c):
            return c if isinstance(c, str) else c.get("name", "unknown")

        def get_container_status(c):
            if isinstance(c, str):
                # 字符串类型来自 containers.all，只包含运行中的容器
                return "running"
            return c.get("status", "stopped")

        running = [c for c in all_containers if get_container_status(c) == "running"]
        stopped = [c for c in all_containers if get_container_status(c) != "running"]

        # 额外统计已停止但不在 all 列表中的容器（如 fooocus）
        # containers.fooocus = False 表示 fooocus 已停止（不在 all 列表中）
        extra_stopped = []
        for key in ["fooocus"]:
            if key in containers and containers[key] is False:
                # 检查是否已在 all 列表中
                if not any(get_container_name(c) == key for c in all_containers):
                    extra_stopped.append(key)

        total = len(all_containers) + len(extra_stopped)
        running_count = len(running)
        stopped_count = len(stopped) + len(extra_stopped)

        # 关键容器
        key_containers = ["ollama", "comfyui"]
        key_running_names = [get_container_name(c) for c in running if get_container_name(c) in key_containers]
        key_stopped = [c for c in key_containers if c not in key_running_names]

        score = 100
        issues = []
        suggestions = []

        if key_stopped:
            score -= 40
            issues.append(f"关键容器未运行: {', '.join(key_stopped)}")
            suggestions.append(f"启动未运行的关键容器: {', '.join(key_stopped)}")

        if stopped_count > 0 and not key_stopped:
            score -= 10
            issues.append(f"{stopped_count} 个非关键容器未运行")

        running_pct = (running_count / total * 100) if total > 0 else 0

        score = max(0, min(100, score))

        return HealthDimension(
            id="containers",
            name="容器状态",
            score=score,
            status=self._score_to_status(score),
            description=f"{running_count}/{total} 个容器运行中",
            metrics={
                "total": total,
                "running": running_count,
                "stopped": stopped_count,
                "running_pct": round(running_pct, 1),
                "key_running": len(key_running_names),
                "key_stopped": key_stopped,
            },
            issues=issues,
            suggestions=suggestions,
        )

    def _evaluate_services(self, status: Dict) -> HealthDimension:
        """评估服务健康度。"""
        activity = status.get("activity", {}) or {}
        services = activity.get("services", {}) or {}
        helper_running = status.get("helper_running", False)

        score = 100
        issues = []
        suggestions = []

        busy_services = [name for name, s in services.items() if s.get("busy")]
        if len(busy_services) > 2:
            score -= 15
            issues.append(f"{len(busy_services)} 个服务同时忙碌，可能存在资源竞争")
            suggestions.append("考虑错峰执行任务，避免多个服务同时运行")

        if not helper_running:
            score -= 10
            issues.append("Helper 进程未运行，进程级显存采集可能不完整")
            suggestions.append("启动 Helper 进程以获得更精确的进程级显存数据")

        # 检查服务响应
        ollama = status.get("ollama", {}) or {}
        if not ollama.get("ok", True):
            score -= 20
            issues.append("Ollama 服务响应异常")

        score = max(0, min(100, score))

        return HealthDimension(
            id="services",
            name="服务响应",
            score=score,
            status=self._score_to_status(score),
            description=f"{len(busy_services)} 个服务忙碌，Helper {'运行中' if helper_running else '未运行'}",
            metrics={
                "busy_services": busy_services,
                "helper_running": helper_running,
                "total_services": len(services),
            },
            issues=issues,
            suggestions=suggestions,
        )

    def _evaluate_alerts(self, status: Dict) -> HealthDimension:
        """评估告警健康度。"""
        guard = status.get("guard", {}) or {}
        guard_level = guard.get("level", "ok")
        guard_alerts = guard.get("alerts", []) or []

        # 处理字符串类型的告警（旧格式）或字典类型的告警（新格式）
        def get_alert_level(a):
            if isinstance(a, dict):
                return a.get("level", "warning")
            # 字符串类型默认 warning
            return "warning"

        def get_alert_message(a):
            if isinstance(a, dict):
                return a.get("message", str(a))
            return str(a)

        score = 100
        issues = []
        suggestions = []

        critical_alerts = [a for a in guard_alerts if get_alert_level(a) == "critical"]
        warning_alerts = [a for a in guard_alerts if get_alert_level(a) == "warning"]

        if guard_level == "critical":
            score -= 50
            issues.append("门卫状态：critical，存在严重告警")
            suggestions.append("立即处理 critical 级别告警")
        elif guard_level == "danger":
            score -= 35
            issues.append("门卫状态：danger")
        elif guard_level == "warning":
            score -= 15
            issues.append("门卫状态：warning")

        if critical_alerts:
            score -= 20
            issues.append(f"{len(critical_alerts)} 条 critical 告警")
        if warning_alerts:
            score -= 10
            issues.append(f"{len(warning_alerts)} 条 warning 告警")

        score = max(0, min(100, score))

        return HealthDimension(
            id="alerts",
            name="告警状态",
            score=score,
            status=self._score_to_status(score),
            description=f"门卫状态: {guard_level}，{len(guard_alerts)} 条活跃告警",
            metrics={
                "guard_level": guard_level,
                "total_alerts": len(guard_alerts),
                "critical_alerts": len(critical_alerts),
                "warning_alerts": len(warning_alerts),
            },
            issues=issues,
            suggestions=suggestions,
        )

    def evaluate(self, status: Dict) -> HealthReport:
        """执行健康度评估。

        Args:
            status: /api/status 的完整数据

        Returns:
            HealthReport 健康报告
        """
        dimensions = [
            self._evaluate_gpu_vram(status),
            self._evaluate_containers(status),
            self._evaluate_services(status),
            self._evaluate_alerts(status),
        ]

        # 加权计算综合健康分
        overall_score = 0
        for dim in dimensions:
            weight = self._weights.get(dim.id, 0.25)
            overall_score += dim.score * weight
        overall_score = int(round(overall_score))

        overall_status = self._score_to_status(overall_score)

        # 收集所有问题和建议
        all_issues = []
        all_suggestions = []
        for dim in dimensions:
            all_issues.extend(dim.issues)
            all_suggestions.extend(dim.suggestions)

        # 摘要
        if overall_status == "excellent":
            summary = "系统运行状态优秀，所有维度健康"
        elif overall_status == "good":
            summary = "系统运行状态良好，存在少量可优化项"
        elif overall_status == "fair":
            summary = "系统状态一般，建议关注部分维度"
        elif overall_status == "poor":
            summary = "系统状态较差，需要及时处理问题"
        else:
            summary = "系统状态危险，需要立即处理严重问题"

        return HealthReport(
            overall_score=overall_score,
            overall_status=overall_status,
            dimensions=dimensions,
            generated_at=datetime.now().isoformat(),
            summary=summary,
            top_issues=all_issues[:5],
            top_suggestions=all_suggestions[:5],
        )


# 全局单例
health_engine = HealthScoreEngine()
