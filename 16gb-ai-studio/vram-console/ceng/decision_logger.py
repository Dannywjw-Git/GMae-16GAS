"""
GMae v0.3.1 C-Eng — 决策日志

记录完整决策链：turn_id、用户输入、状态快照、LLM输出、校验结果、执行日志。
按天轮转，保留7天。完整 prompt 存7天，7天后自动清理只留元数据。
"""
import json
import os
import time
from datetime import datetime
from collections import deque


class DecisionLogger:
    def __init__(self, log_dir: str = None, retention_days: int = 7):
        if log_dir is None:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
        self.log_dir = os.path.abspath(log_dir)
        os.makedirs(self.log_dir, exist_ok=True)
        self.retention_days = retention_days
        self._cache: deque = deque(maxlen=100)  # 内存缓存最近100条

    def _log_file(self) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"ceng-decision-{date_str}.log")

    def log_decision(self, decision: dict):
        """记录决策结果。"""
        entry = {
            "ts": datetime.now().isoformat(),
            "turn_id": decision.get("turn_id"),
            "event": "decision",
            "user_input": decision.get("user_input"),
            "intent": decision.get("intent"),
            "plan": decision.get("plan"),
            "estimated_vram_peak": decision.get("estimated_vram_peak"),
            "confidence": decision.get("confidence"),
            "backend_used": decision.get("backend_used"),
            "backend_tier": decision.get("backend_tier"),
            "validation": decision.get("validation"),
            "latency_ms": decision.get("latency_ms"),
            "prompt_tokens": decision.get("prompt_tokens"),
            "completion_tokens": decision.get("completion_tokens"),
            "status": decision.get("status"),
            "error": decision.get("error"),
        }
        self._write(entry)
        self._cache.append(entry)

    def log_execution(self, turn_id: str, execution: dict):
        """记录执行结果。"""
        entry = {
            "ts": datetime.now().isoformat(),
            "turn_id": turn_id,
            "event": "execution",
            "status": execution.get("status"),
            "all_success": execution.get("all_success"),
            "execution_log": execution.get("execution_log"),
        }
        self._write(entry)
        self._cache.append(entry)

    def _write(self, entry: dict):
        try:
            with open(self._log_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_recent(self, limit: int = 20) -> list:
        """获取最近的决策记录。"""
        return list(self._cache)[-limit:]

    def get_by_turn_id(self, turn_id: str) -> dict:
        """按 turn_id 查询完整决策链（决策 + 执行）。"""
        decision = None
        execution = None
        for entry in reversed(self._cache):
            if entry.get("turn_id") == turn_id:
                if entry.get("event") == "decision" and decision is None:
                    decision = entry
                elif entry.get("event") == "execution" and execution is None:
                    execution = entry
                if decision and execution:
                    break
        return {"decision": decision, "execution": execution}

    def cleanup_old_logs(self):
        """清理超过保留期的日志文件。"""
        try:
            now = time.time()
            for fname in os.listdir(self.log_dir):
                if fname.startswith("ceng-decision-") and fname.endswith(".log"):
                    fpath = os.path.join(self.log_dir, fname)
                    age_days = (now - os.path.getmtime(fpath)) / 86400
                    if age_days > self.retention_days:
                        os.remove(fpath)
        except Exception:
            pass
