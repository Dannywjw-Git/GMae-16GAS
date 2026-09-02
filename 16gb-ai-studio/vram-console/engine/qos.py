#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae QoS 服务等级引擎
- 显存水位分级（ok/warning/emergency）
- 降级建议生成与执行
- 自动防死机（用户授权后分级自动释放）
"""
import time
import threading
from collections import deque
from core.logger import log_event, log_error, toast_notify
from core.config import get_threshold_value
from core.registry import registry
from core.utils import run_args
from engine.reaper import service_activity
from gpu.monitor import gpu_status
from core.event_bus import event_bus
# 注意：本模块的 services 依赖采用函数内延迟导入，避免 engine 层模块级依赖 services 层。

# 兼容旧引用
_get_threshold_value = get_threshold_value

# === QoS 配置 ===
QOS_CFG = {
    "emergency_threshold_mb": _get_threshold_value("emergency_free_mb", 2048),
    "warning_threshold_mb": _get_threshold_value("warning_free_mb", 4096),
    "check_interval_s": 10,
    "enabled": True,
    "cooldown_s": 60,
}
# === QoS 状态 — 已迁移到 registry（保持引用一致）===
_qos_state = registry.get("qos_state")
if _qos_state is None:
    _qos_state = {
        "level": "ok",
        "last_emergency_ts": 0,
        "last_action": None,
        "suggestions": [],
        "history": deque(maxlen=50),
    }
    registry.set("qos_state", _qos_state)

# QoS 状态变更锁（保护 _qos_state 的复合读写操作）
_qos_lock = threading.Lock()


def _record_qos_transition(old_level: str, new_level: str, free_mb: int, reason: str = "") -> None:
    """QoS 状态跃迁时记录事件到 event_bus（S2.2）。

    Args:
        old_level: 旧状态（ok/warning/emergency）
        new_level: 新状态（ok/warning/emergency）
        free_mb: 当前空闲显存（MB）
        reason: 跃迁原因（可选）
    """
    if old_level == new_level:
        return
    # 事件级别：emergency→critical, warning→warning, ok→info
    if new_level == "emergency":
        event_level = "critical"
    elif new_level == "warning":
        event_level = "warning"
    else:
        event_level = "info"
    try:
        event_bus.record(
            category="vram",
            level=event_level,
            source="qos_engine",
            event="vram_state_{}_to_{}".format(old_level, new_level),
            message="显存状态从 {} 变为 {}（空闲 {}MB）{}".format(
                old_level, new_level, free_mb,
                "，原因：{}".format(reason) if reason else ""
            ),
            metadata={
                "old_state": old_level,
                "new_state": new_level,
                "vram_free_mb": free_mb,
                "reason": reason,
            }
        )
    except Exception:
        pass  # 事件记录失败不影响 QoS 功能


def qos_check():
    """QoS 检查：按显存水位分级，危急时触发自动防死机。"""
    from services.helper import _auto_protect_cfg
    if not QOS_CFG["enabled"]:
        return {"level": "disabled"}
    gpu = gpu_status()
    if not gpu.get("ok"):
        return {"level": "unknown", "error": "nvidia-smi unavailable"}
    free_mb = gpu.get("free_mb", 99999)
    now = time.time()
    old_level = _qos_state.get("level", "ok")
    if free_mb < QOS_CFG["emergency_threshold_mb"]:
        auto_result = _auto_protect_run(free_mb)
        if auto_result:
            result = {"level": "emergency", "free_mb": free_mb, "free_gb": round(free_mb / 1024, 1),
                      "actions": auto_result.get("actions", []),
                      "message": "显存危急（%.1fGB），已按自动防死机策略执行分级释放。" % (free_mb / 1024)}
            _qos_state["last_emergency_ts"] = now
            _record_qos_transition(old_level, "emergency", free_mb, "auto_protect")
            _qos_state["level"] = "emergency"
            _qos_state["last_action"] = result
            _qos_state["history"].append({"ts": now, "level": "emergency", "free_mb": free_mb})
            return result
        _record_qos_transition(old_level, "emergency", free_mb, "threshold_crossed")
        _qos_state["level"] = "emergency"
        return {"level": "emergency", "free_mb": free_mb, "free_gb": round(free_mb / 1024, 1),
                "auto_protect": _auto_protect_cfg().get("enabled"),
                "message": ("显存危急（%.1fGB）！已自动执行分级释放。" % (free_mb / 1024)
                            if _auto_protect_cfg().get("enabled")
                            else "显存危急（%.1fGB）！自动防死机未开启，请立即手动释放。" % (free_mb / 1024))}
    elif free_mb < QOS_CFG["warning_threshold_mb"]:
        suggestions = _qos_build_suggestions(free_mb)
        _record_qos_transition(old_level, "warning", free_mb, "threshold_crossed")
        _qos_state["level"] = "warning"
        _qos_state["suggestions"] = suggestions
        return {"level": "warning", "free_mb": free_mb, "free_gb": round(free_mb / 1024, 1),
                "suggestions": suggestions,
                "message": "显存紧张（%.1fGB 空闲），建议释放以下资源：" % (free_mb / 1024)}
    else:
        _record_qos_transition(old_level, "ok", free_mb, "recovered")
        _qos_state["level"] = "ok"
        _qos_state["suggestions"] = []
        return {"level": "ok", "free_mb": free_mb, "free_gb": round(free_mb / 1024, 1)}


def _qos_build_suggestions(free_mb):
    """构建降级建议列表。"""
    from services.ollama import ollama_ps, ollama_stop
    from services.comfy import comfy_free
    from services.docker import docker_containers
    suggestions = []
    try:
        ollama_loaded = ollama_ps().get("models", [])
        for m in ollama_loaded:
            model_name = m.get("model", "")
            size_gb = float(m.get("size_gb", 0))
            suggestions.append({
                "id": "ollama_stop_%s" % model_name,
                "type": "ollama_stop",
                "model": model_name,
                "vram_gb": round(size_gb, 1),
                "action": "停止 %s（释放 %.1fGB）" % (model_name, size_gb),
                "priority": "medium",
            })
    except Exception as e:
        log_error("qos_suggestion_ollama_failed", error=e)
    try:
        if "comfyui" in docker_containers():
            suggestions.append({
                "id": "comfy_free", "type": "comfy_free",
                "action": "ComfyUI /free（释放生成模型显存，约 2-6GB）",
                "priority": "low",
            })
    except Exception as e:
        log_error("qos_suggestion_comfy_failed", error=e)
    try:
        if "fooocus" in docker_containers():
            suggestions.append({
                "id": "fooocus_stop", "type": "fooocus_stop",
                "action": "停止 Fooocus 容器（释放约 7GB）",
                "priority": "high",
            })
    except Exception as e:
        log_error("qos_suggestion_fooocus_failed", error=e)
    priority_order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))
    return suggestions


def qos_execute_suggestion(suggestion_id):
    """执行用户选择的降级建议。"""
    from services.ollama import ollama_stop
    from services.comfy import comfy_free
    from services.docker import docker_action
    suggestions = _qos_state.get("suggestions", [])
    target = next((s for s in suggestions if s["id"] == suggestion_id), None)
    if not target:
        return {"ok": False, "error": "suggestion not found: %s" % suggestion_id}
    try:
        if target["type"] == "ollama_stop":
            ollama_stop([target["model"]])
            msg = "已停止 %s" % target["model"]
        elif target["type"] == "comfy_free":
            comfy_free()
            msg = "已释放 ComfyUI 显存"
        elif target["type"] == "fooocus_stop":
            docker_action("fooocus", "stop")
            msg = "已停止 Fooocus 容器"
        else:
            return {"ok": False, "error": "unknown type"}
        log_event("qos_user_downgrade", suggestion_id=suggestion_id, message=msg)
        new_state = qos_check()
        return {"ok": True, "message": msg, "new_state": new_state}
    except Exception as e:
        log_error("qos_execute_error", error=str(e))
        return {"ok": False, "error": str(e)}


def qos_status():
    return {
        "ok": True,
        "level": _qos_state["level"],
        "last_action": _qos_state["last_action"],
        "suggestions": _qos_state["suggestions"],
        "config": QOS_CFG,
        "history": list(_qos_state["history"])[-10:],
    }


def _qos_loop():
    log_event("qos_loop_start", enabled=QOS_CFG["enabled"])
    while True:
        try:
            qos_check()
        except Exception as e:
            log_error("qos_loop_error", error=str(e))
        time.sleep(QOS_CFG["check_interval_s"])


def start_qos():
    t = threading.Thread(target=_qos_loop, daemon=True, name="qos-engine")
    t.start()
    return t


# === 自动防死机 ===
# === 自动防死机状态 — 已迁移到 registry（保持引用一致）===
_AUTO_PROTECT_STATE = registry.get("auto_protect_state")
if _AUTO_PROTECT_STATE is None:
    _AUTO_PROTECT_STATE = {
        "last_trigger_ts": 0,
        "last_level": None,
        "last_actions": [],
        "last_free_mb": None,
        "history": deque(maxlen=20),
    }
    registry.set("auto_protect_state", _AUTO_PROTECT_STATE)
_AUTO_PROTECT_COOLDOWN_S = 120
_AUTO_PROTECT_RESET_MB = 4096
_AUTO_PROTECT_MODE_PLAN = {
    "conservative": {"critical": [1, 2], "danger": [], "warning": []},
    "standard":     {"critical": [1, 2, 3], "danger": [1, 2], "warning": []},
    "aggressive":   {"critical": [1, 2, 3], "danger": [1, 2], "warning": [1]},
}


def _auto_protect_run(free_mb):
    """自动防死机主逻辑：由 qos_check 每周期调用。"""
    from services.helper import _auto_protect_cfg
    from services.ollama import ollama_ps, ollama_stop
    from services.comfy import comfy_free
    from services.docker import docker_containers, docker_action, infer_scene
    ap = _auto_protect_cfg()
    if not ap.get("enabled"):
        return None
    now = time.time()
    st = _AUTO_PROTECT_STATE
    _crit = _get_threshold_value("emergency_free_mb", 2048) // 2
    _danger = _get_threshold_value("emergency_free_mb", 2048)
    _warn = _get_threshold_value("warning_free_mb", 4096)
    if free_mb < _crit:
        level = "critical"
    elif free_mb < _danger:
        level = "danger"
    elif free_mb < _warn:
        level = "warning"
    else:
        st["last_level"] = None
        return None
    if level == st["last_level"] and now - st["last_trigger_ts"] < _AUTO_PROTECT_COOLDOWN_S:
        return None
    plan = _AUTO_PROTECT_MODE_PLAN.get(ap.get("mode", "standard"), {})
    enabled_levels = plan.get(level, [])
    if not enabled_levels:
        return None
    actions = []
    names = docker_containers()
    scene = infer_scene(names)
    if 1 in enabled_levels:
        try:
            loaded = ollama_ps().get("models", [])
            keep = loaded[-1].get("model") if (scene == "dialogue" and loaded) else None
            to_stop = [m.get("model") for m in loaded
                       if m.get("model") and m.get("model") != keep]
            if to_stop:
                ollama_stop(to_stop)
                actions.append({"level": "L1", "action": "卸载 Ollama 模型", "target": to_stop})
        except Exception as e:
            log_error("auto_protect_l1_error", error=str(e))
    if 2 in enabled_levels and "comfyui" in names:
        try:
            activity = service_activity().get("services", {}) or {}
            if not (activity.get("comfyui") or {}).get("busy"):
                if comfy_free().get("ok"):
                    actions.append({"level": "L2", "action": "ComfyUI 释放生成模型显存"})
        except Exception as e:
            log_error("auto_protect_l2_error", error=str(e))
    if 3 in enabled_levels and "fooocus" in names and scene != "fooocus":
        try:
            docker_action("fooocus", "stop")
            actions.append({"level": "L3", "action": "停止 Fooocus 容器"})
        except Exception as e:
            log_error("auto_protect_l3_error", error=str(e))
    if not actions:
        return None
    st["last_trigger_ts"] = now
    st["last_level"] = level
    st["last_actions"] = actions
    st["last_free_mb"] = free_mb
    st["history"].append({"ts": now, "level": level, "free_mb": free_mb, "actions": actions})
    log_event("auto_protect_trigger", level=level, free_mb=free_mb,
              mode=ap.get("mode"), actions=actions)
    toast_notify("GMae 自动防死机", "显存 %s（空闲 %.1fGB），已自动执行：%s" % (
        level, free_mb / 1024, "；".join(a["action"] for a in actions)),
        event_type="auto_protect", cooldown_s=120)
    return {"level": level, "free_mb": free_mb, "actions": actions}


def auto_protect_status():
    """GET /api/auto-protect/status：当前配置 + 最近触发记录。"""
    from services.helper import _auto_protect_cfg
    ap = _auto_protect_cfg()
    st = _AUTO_PROTECT_STATE
    return {
        "ok": True,
        "enabled": ap.get("enabled"),
        "mode": ap.get("mode"),
        "modes": {
            "conservative": "保守：仅 <1GB 危急时卸载多余模型 + ComfyUI 释放；不碰容器",
            "standard": "标准：<2GB 开始卸载多余模型 + ComfyUI 释放；<1GB 再加停 Fooocus",
            "aggressive": "激进：<4GB 即卸载多余模型；<2GB 加 ComfyUI 释放；<1GB 加停 Fooocus",
        },
        "last_trigger": ({"ts": st["last_trigger_ts"], "level": st["last_level"],
                          "free_mb": st["last_free_mb"], "actions": st["last_actions"]}
                         if st["last_trigger_ts"] else None),
        "history": list(st["history"])[-8:],
    }


def auto_protect_config(data):
    """POST /api/auto-protect/config：{enabled?, mode?} 保存并审计。"""
    from services.helper import _auto_protect_cfg, _auto_protect_save
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid payload"}
    if "enabled" not in data and "mode" not in data:
        return {"ok": False, "error": "nothing to change"}
    if not _auto_protect_save(data):
        return {"ok": False, "error": "保存配置失败"}
    ap = _auto_protect_cfg()
    log_event("auto_protect_config_change", enabled=ap.get("enabled"), mode=ap.get("mode"))
    toast_notify("自动防死机", "已%s（模式：%s）" % ("开启" if ap.get("enabled") else "关闭", ap.get("mode")),
                 event_type="auto_protect_config", cooldown_s=10)
    return {"ok": True, "enabled": ap.get("enabled"), "mode": ap.get("mode")}
