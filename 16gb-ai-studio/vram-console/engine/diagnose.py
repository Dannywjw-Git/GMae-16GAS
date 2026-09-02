#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根因推断规则引擎（S2.5）— 基于 if-then 规则的故障根因分析（非 ML，保证可解释性）。

核心概念：
- Rule: 一条诊断规则，含 condition（事件模式匹配）、root_cause、confidence、suggested_action
- DiagnosisResult: 诊断结果，含匹配的规则列表（按置信度排序）+ 关联事件

规则匹配算法：
1. 拉取时间窗内所有事件（默认最近 300 秒）
2. 逐条规则检查 condition（事件模式 + 当前状态）
3. 匹配的规则按 confidence 降序排序
4. 返回 Top3 + 每条规则的关联事件
"""
import re
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from core.event_bus import event_bus


@dataclass
class Rule:
    """诊断规则。"""
    id: str  # 规则 ID，如 RC-001
    name: str  # 规则名称
    description: str  # 规则描述
    condition: Callable[[List[Dict], Dict], bool]  # 匹配函数：(事件列表, 当前状态) -> bool
    root_cause: str  # 根因描述
    confidence: int  # 置信度 0-100
    suggested_action: str  # 处置建议
    related_events_query: Dict[str, Any]  # 关联事件查询条件


@dataclass
class DiagnosisResult:
    """诊断结果。"""
    alert_type: str
    alert_time: str
    window_seconds: int
    matched_rules: List[Dict] = field(default_factory=list)  # 匹配的规则（含关联事件）
    matched_failure_scenarios: List[Dict] = field(default_factory=list)  # 匹配的故障场景（含处置步骤）
    total_events: int = 0
    default_diagnosis: Optional[str] = None


class RuleEngine:
    """规则引擎。"""

    def __init__(self):
        self._rules: List[Rule] = []

    def register(self, rule: Rule) -> None:
        """注册一条规则。"""
        self._rules.append(rule)

    def get_all_rules(self) -> List[Dict]:
        """获取所有规则的元信息。"""
        return [
            {"id": r.id, "name": r.name, "description": r.description,
             "root_cause": r.root_cause, "confidence": r.confidence,
             "suggested_action": r.suggested_action}
            for r in self._rules
        ]

    def diagnose(self, alert_type: str, alert_time: Optional[str] = None,
                 window_seconds: int = 300, current_status: Optional[Dict] = None) -> DiagnosisResult:
        """
        执行诊断。

        Args:
            alert_type: 告警类型，如 "vram_critical"
            alert_time: 告警时间（ISO 8601），默认当前时间
            window_seconds: 回溯时间窗，默认 300 秒
            current_status: 当前系统状态（/api/status 的数据），用于 condition 中的状态检查
        """
        # 拉取时间窗内事件
        events = event_bus.get_recent(seconds=window_seconds)
        current_status = current_status or {}

        result = DiagnosisResult(
            alert_type=alert_type,
            alert_time=alert_time or "",
            window_seconds=window_seconds,
            total_events=len(events)
        )

        # 逐条规则匹配
        matched = []
        for rule in self._rules:
            try:
                if rule.condition(events, current_status):
                    # 拉取关联事件
                    related = event_bus.query(
                        category=rule.related_events_query.get("category"),
                        event=rule.related_events_query.get("event"),
                        limit=20
                    )
                    matched.append({
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "root_cause": rule.root_cause,
                        "confidence": rule.confidence,
                        "suggested_action": rule.suggested_action,
                        "related_events": related,
                        "related_events_count": len(related)
                    })
            except Exception:
                continue  # 规则执行失败不影响其他规则

        # 按置信度降序排序，取 Top3
        matched.sort(key=lambda x: x["confidence"], reverse=True)
        result.matched_rules = matched[:3]

        # P1.2: 根据匹配的规则关联故障场景
        matched_rule_ids = {r["rule_id"] for r in matched}
        matched_scenarios = []
        for scenario in FAILURE_SCENARIOS:
            # 检查故障场景对应的规则是否有匹配
            scenario_rules = scenario.get("related_rules", [])
            matched_scenario_rules = [r for r in scenario_rules if r in matched_rule_ids]
            if matched_scenario_rules:
                scenario_copy = dict(scenario)
                scenario_copy["matched_rules"] = matched_scenario_rules
                scenario_copy["match_count"] = len(matched_scenario_rules)
                matched_scenarios.append(scenario_copy)
        # 按匹配规则数量降序排序
        matched_scenarios.sort(key=lambda x: x["match_count"], reverse=True)
        result.matched_failure_scenarios = matched_scenarios

        if not result.matched_rules:
            result.default_diagnosis = "未识别到明确根因，建议检查事件时间线。最近 10 条事件已附带。"
            result.matched_rules = [{
                "rule_id": "DEFAULT",
                "rule_name": "默认诊断",
                "root_cause": result.default_diagnosis,
                "confidence": 0,
                "suggested_action": "查看事件时间线，手动排查",
                "related_events": events[:10],
                "related_events_count": min(len(events), 10)
            }]

        return result


# ========== 故障场景库（P1.2） ==========
# 5个标准化故障场景，与规则引擎关联，为诊断中心提供知识库支撑
FAILURE_SCENARIOS = [
    {
        "id": "FC-001",
        "name": "显存耗尽/OOM风险",
        "level": "critical",
        "description": "free_vram < 1GB 持续10秒，存在OOM死机风险",
        "related_rules": ["RC-001", "RC-002", "RC-003", "RC-005"],
        "trigger_condition": "free_vram < 1GB 持续10秒",
        "alert_template": "显存剩余 {free_mb}MB，已持续 {duration}秒，存在OOM死机风险",
        "resolution_steps": [
            "1. 预览释放：GET /api/status 查看当前显存占用",
            "2. 一键释放：POST /api/free {'level': 'L1'} 释放未使用模型",
            "3. 如仍 critical：暂停队列任务",
            "4. 如仍 critical：切换到 idle 场景：POST /api/scene {'scene': 'idle'}",
            "5. 验证：GET /api/status 确认 free_vram > 4GB",
        ],
        "verification": "处置后10秒内 free_vram > 4GB，告警自动消除",
        "prevention": "避免同时加载多个大模型；生成高分辨率内容前先检查显存；启用自动防死机",
    },
    {
        "id": "FC-002",
        "name": "容器异常退出/频繁重启",
        "level": "warning",
        "description": "Docker die 事件 + 5分钟内重启 ≥3次，容器可能存在稳定性问题",
        "related_rules": ["RC-006"],
        "trigger_condition": "5分钟内 container_die 事件 ≥3次",
        "alert_template": "容器 {container_name} 在5分钟内重启了 {count} 次，可能存在稳定性问题",
        "resolution_steps": [
            "1. 查看容器日志：docker logs {container_name} --tail 100",
            "2. 检查是否 OOM killed：docker inspect {container_name} | grep OOMKilled",
            "3. 重启容器：POST /api/service {'name': '{container_name}', 'action': 'restart'}",
            "4. 如持续崩溃：停止容器并排查：POST /api/service {'name': '{container_name}', 'action': 'stop'}",
            "5. 验证：GET /api/status 确认容器稳定运行 >5分钟",
        ],
        "verification": "容器重启后稳定运行 >5分钟，5分钟内无新的 die 事件",
        "prevention": "定期检查容器日志；为关键容器配置重启策略；监控容器内存使用",
    },
    {
        "id": "FC-003",
        "name": "推理延迟升高",
        "level": "warning",
        "description": "模型推理 P95 响应时间 > 阈值持续3次，可能是显存不足或模型参数过大",
        "related_rules": ["RC-007"],
        "trigger_condition": "最近3次推理响应时间 > 阈值（LLM >30s/图 >120s）",
        "alert_template": "{model_name} 最近3次推理平均响应时间 {avg_time}秒，超过阈值",
        "resolution_steps": [
            "1. 检查显存状态：GET /api/status（确认显存是否不足）",
            "2. 如显存不足：释放显存 POST /api/free {'level': 'L1'}",
            "3. 降低模型参数：切换到更小的模型 POST /api/model {'name': '{smaller_model}', 'action': 'load'}",
            "4. 降低 context 长度（LLM）或分辨率（图像/视频）",
            "5. 验证：连续3次推理响应时间 < 阈值",
        ],
        "verification": "连续3次推理响应时间 < 阈值，GPU 利用率正常（<95%）",
        "prevention": "根据任务复杂度选择合适大小的模型；避免在显存不足时运行大模型",
    },
    {
        "id": "FC-004",
        "name": "任务队列堆积",
        "level": "info",
        "description": "ComfyUI 队列 pending >5 持续30秒，任务提交速度超过处理速度",
        "related_rules": ["RC-008"],
        "trigger_condition": "ComfyUI 队列 pending >5 持续30秒",
        "alert_template": "ComfyUI 队列当前有 {pending_count} 个待处理任务，已持续 {duration}秒",
        "resolution_steps": [
            "1. 查看队列状态：GET /api/queue",
            "2. 取消低优先级任务：POST /api/queue/cancel {'task_id': '{id}'}",
            "3. 检查 worker 是否卡住：查看 ComfyUI 日志 docker logs comfyui",
            "4. 如 worker 卡住：重启 ComfyUI 容器 POST /api/service {'name': 'comfyui', 'action': 'restart'}",
            "5. 验证：GET /api/queue 确认 pending_count <3",
        ],
        "verification": "队列 pending_count <3，任务正常推进，无卡住超过5分钟的任务",
        "prevention": "限制并发任务数（建议同时只运行1-2个生成任务）；高优先级任务优先提交",
    },
    {
        "id": "FC-005",
        "name": "服务不可达",
        "level": "danger",
        "description": "health check 连续3次失败，服务可能已崩溃",
        "related_rules": ["RC-009"],
        "trigger_condition": "health check 连续3次失败",
        "alert_template": "服务 {service_name} 健康检查连续3次失败，服务可能已崩溃",
        "resolution_steps": [
            "1. 检查服务状态：GET /api/status（确认哪些服务不可达）",
            "2. 检查端口是否被占用：netstat -ano | findstr :{port}",
            "3. 重启服务容器：POST /api/service {'name': '{service_name}', 'action': 'restart'}",
            "4. 查看服务日志：docker logs {service_name} --tail 100",
            "5. 如持续崩溃：停止服务并排查根因",
            "6. 验证：GET /api/health 确认服务健康",
        ],
        "verification": "服务健康检查通过（连续3次成功），服务端口可访问",
        "prevention": "为关键服务配置健康检查和自动重启；定期检查服务日志",
    },
]


# ========== 辅助函数 ==========

def _has_event(events: List[Dict], event_pattern: str, category: Optional[str] = None) -> bool:
    """检查事件列表中是否存在匹配的事件。event_pattern 支持正则。"""
    for e in events:
        if category and e.get("category") != category:
            continue
        if re.search(event_pattern, e.get("event", "")):
            return True
    return False


def _is_container_running(status: Dict, container_name: str) -> bool:
    """检查容器是否在运行。"""
    services = status.get("data", {}).get("services", {})
    return services.get(container_name, {}).get("ok", False)


def _get_vram_free_mb(status: Dict) -> int:
    """获取当前空闲显存。"""
    return status.get("data", {}).get("vram_ledger", {}).get("free_mb", 99999)


def _get_loaded_models(status: Dict, container: str) -> List[str]:
    """获取容器中加载的模型列表。"""
    if container == "ollama":
        return status.get("data", {}).get("ollama", {}).get("loaded_models", [])
    return []


# ========== 规则定义 ==========

# RC-001: ComfyUI 生成任务显存溢出
def rc001_condition(events: List[Dict], status: Dict) -> bool:
    return (
        _has_event(events, r"task_submit|comfyui_task|task_submitted", "task")
        and _is_container_running(status, "comfyui")
        and _get_vram_free_mb(status) < 1024
    )

# RC-002: 大模型加载导致显存不足
def rc002_condition(events: List[Dict], status: Dict) -> bool:
    loaded = _get_loaded_models(status, "ollama")
    has_large = any(any(s in m.lower() for s in ["7b", "9b", "14b", "27b", "32b"]) for m in loaded)
    return (
        _has_event(events, r"model_loaded", "model")
        and has_large
        and _get_vram_free_mb(status) < 2048
    )

# RC-003: Fooocus 场景切换后显存未释放
def rc003_condition(events: List[Dict], status: Dict) -> bool:
    return (
        _has_event(events, r"scene_switched|combo_switched", "user_action")
        and _is_container_running(status, "fooocus")
        and _get_vram_free_mb(status) < 2048
    )

# RC-004: 多服务并发占用累积
def rc004_condition(events: List[Dict], status: Dict) -> bool:
    services = status.get("data", {}).get("services", {})
    running_count = sum(1 for s in services.values() if s.get("ok"))
    return (
        running_count >= 3
        and not _has_event(events, r"task_submit|model_loaded|task_submitted", "task")
        and _get_vram_free_mb(status) < 4096
    )

# RC-005: 桌面应用占用显存
def rc005_condition(events: List[Dict], status: Dict) -> bool:
    desktop_vram = status.get("data", {}).get("desktop_vram", {}).get("total_mb", 0)
    return (
        desktop_vram > 2048
        and not _has_event(events, r"task_submit|model_loaded|scene_switched|task_submitted", "task")
        and _get_vram_free_mb(status) < 2048
    )


# RC-006: 容器异常退出/频繁重启
def rc006_condition(events: List[Dict], status: Dict) -> bool:
    """5 分钟内 container_die 事件 >=3 次（同一或不同容器）。"""
    die_count = sum(1 for e in events if e.get("category") == "container" and "die" in e.get("event", ""))
    return die_count >= 3


# RC-007: 推理延迟升高
def rc007_condition(events: List[Dict], status: Dict) -> bool:
    """显存不足 + 有推理任务（简化版，当前未采集推理响应时间）。"""
    has_inference = _has_event(events, r"task_submit|task_submitted|model_loaded", "task") or                     _has_event(events, r"model_loaded", "model")
    return has_inference and _get_vram_free_mb(status) < 2048


# RC-008: 任务队列堆积
def rc008_condition(events: List[Dict], status: Dict) -> bool:
    """有 task 事件 + 显存不足（简化版，当前未采集队列 pending 数）。"""
    task_count = sum(1 for e in events if e.get("category") == "task")
    return task_count >= 3 and _get_vram_free_mb(status) < 4096


# RC-009: 服务不可达
def rc009_condition(events: List[Dict], status: Dict) -> bool:
    """有 container_die/kill 事件 + 对应服务不在运行。"""
    has_crash = _has_event(events, r"container_die|container_kill", "container")
    services = status.get("data", {}).get("services", {})
    running_count = sum(1 for s in services.values() if s.get("ok"))
    return has_crash and running_count < 5  # 正常应有 9 个左右容器运行


# 全局规则引擎实例
rule_engine = RuleEngine()

# 注册初始 5 条规则
rule_engine.register(Rule(
    id="RC-001",
    name="ComfyUI 生成任务显存溢出",
    description="ComfyUI 正在运行且最近有任务提交，显存进入危险状态",
    condition=rc001_condition,
    root_cause="ComfyUI 生成任务显存溢出，高分辨率或大批量生成导致显存占用超出预期",
    confidence=85,
    suggested_action="暂停 ComfyUI 队列任务；降低生成分辨率或批量大小；执行 /api/free 释放 ComfyUI 显存",
    related_events_query={"category": "task", "event": "task_submitted"}
))

rule_engine.register(Rule(
    id="RC-002",
    name="大模型加载导致显存不足",
    description="Ollama 加载了 >7B 模型且最近有模型加载事件",
    condition=rc002_condition,
    root_cause="大参数模型（>7B）加载占用大量显存，与其他服务并发导致显存不足",
    confidence=80,
    suggested_action="卸载大模型（ollama rm 或 /api/model unload）；切换到小模型（如 qwen3:0.6b）；降低 context 长度",
    related_events_query={"category": "model", "event": "model_loaded"}
))

rule_engine.register(Rule(
    id="RC-003",
    name="Fooocus 场景切换后显存未释放",
    description="Fooocus 正在运行且最近有场景切换，显存未正常释放",
    condition=rc003_condition,
    root_cause="Fooocus 容器在场景切换后显存未正常释放，模型权重残留在显存中",
    confidence=70,
    suggested_action="重启 Fooocus 容器（docker restart fooocus）；切换到不含 Fooocus 的场景；执行 /api/free L2 释放",
    related_events_query={"category": "user_action", "event": "scene_switched"}
))

rule_engine.register(Rule(
    id="RC-004",
    name="多服务并发占用累积",
    description="多个容器同时运行且无新任务，显存被并发服务累积占用",
    condition=rc004_condition,
    root_cause="多个 AI 服务（Ollama/ComfyUI/Fooocus/OWUI）同时运行，显存被累积占用，无单一明显元凶",
    confidence=60,
    suggested_action="停止非必要服务（如 OWUI/Immich）；切换到独占场景（只运行一个 AI 服务）；执行 /api/free 释放空闲模型",
    related_events_query={"category": "container", "event": "container_start"}
))

rule_engine.register(Rule(
    id="RC-005",
    name="桌面应用占用显存",
    description="桌面进程显存 >2GB 且最近无容器操作，显存被桌面 GPU 应用占用",
    condition=rc005_condition,
    root_cause="桌面 GPU 应用（游戏、浏览器硬件加速、视频编辑等）占用大量显存，与 AI 服务竞争显存资源",
    confidence=75,
    suggested_action="关闭桌面 GPU 应用（游戏、浏览器等）；检查是否误开游戏；在 /api/desktop_vram 中查看具体进程并结束",
    related_events_query={"category": "system", "event": "desktop_"}
))

rule_engine.register(Rule(
    id="RC-006",
    name="容器异常退出/频繁重启",
    description="5 分钟内 container_die 事件 >=3 次，容器可能存在 OOM 或配置错误",
    condition=rc006_condition,
    root_cause="容器频繁异常退出，可能是 OOM killed、配置错误、依赖缺失或端口冲突",
    confidence=75,
    suggested_action="检查容器日志（docker logs）；检查是否 OOM killed（docker inspect）；释放显存后重启容器；如持续崩溃暂时停止容器",
    related_events_query={"category": "container", "event": "container_die"}
))

rule_engine.register(Rule(
    id="RC-007",
    name="推理延迟升高",
    description="显存不足且有推理任务，推理响应时间可能超过阈值",
    condition=rc007_condition,
    root_cause="显存不足导致模型交换或并发竞争，推理延迟升高；也可能是模型参数过大或 context 过长",
    confidence=65,
    suggested_action="释放空闲模型（/api/free L1）；降低模型参数或 context 长度；切换到小模型（如 qwen3:0.6b）；图生成降低分辨率或步数",
    related_events_query={"category": "task", "event": "task_submitted"}
))

rule_engine.register(Rule(
    id="RC-008",
    name="任务队列堆积",
    description="最近有多个任务提交且显存不足，任务队列可能堆积",
    condition=rc008_condition,
    root_cause="任务提交速度超过处理速度，队列堆积；可能是 worker 卡住、生成速度慢或批量提交过多",
    confidence=55,
    suggested_action="取消低优先级任务（/api/queue/cancel）；检查 ComfyUI worker 是否卡住（docker logs comfyui）；如 worker 卡住重启 ComfyUI；避免一次性提交大量任务",
    related_events_query={"category": "task", "event": "task_submitted"}
))

rule_engine.register(Rule(
    id="RC-009",
    name="服务不可达",
    description="有容器异常退出事件且运行中的服务数量低于正常水平",
    condition=rc009_condition,
    root_cause="服务崩溃或被停止，可能是 OOM、端口冲突、依赖缺失或手动停止",
    confidence=80,
    suggested_action="检查服务进程状态（docker ps -a）；检查端口占用（netstat）；重启崩溃的容器（docker restart）；查看服务日志定位原因（docker logs）",
    related_events_query={"category": "container", "event": "container_die"}
))
