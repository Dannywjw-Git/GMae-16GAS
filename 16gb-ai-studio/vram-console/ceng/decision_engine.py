"""
GMae v0.3.1 C-Eng — 决策引擎

单阶段决策流程：
1. 构建上下文（状态快照+可释放项+对话历史+System Prompt决策模式引导）
2. L1 快道（0.8b）单次调用：意图理解+任务规划+调度决策
3. 深道判断：复杂任务自动升级云端/9b 重规划
4. 释放本地深道模型（避免自指显存占用）
5. 准入校验：逐步骤过 P-Eng /api/admission
6. 准入拒绝后自动重规划（最多1次，注入拒绝原因）
7. 用户确认（默认每次确认）
8. 执行：逐步重评估（每步后重新获取状态+准入）
9. 决策归档
"""
import json
import time
import uuid
from typing import Optional

from .providers.manager import ProviderManager
from .context_builder import ContextBuilder
from .tools.peng_client import PengClient
from .tools.peng_tools import create_all_tools


class DecisionEngine:
    def __init__(self, peng_client: PengClient, provider_manager: ProviderManager = None):
        self.peng = peng_client
        self.providers = provider_manager or ProviderManager()
        self.tools = create_all_tools(peng_client)
        self.context_builder = ContextBuilder(peng_client, self.tools)
        self.decision_logger = None

    def plan(self, user_input: str, prefer_backend: str = "auto") -> dict:
        """
        单阶段决策：理解意图 + 规划任务序列 + 准入校验 + 拒绝后重规划。

        Returns:
            决策结果 dict（含 plan、confidence、validation、retry 信息等）
        """
        turn_id = uuid.uuid4().hex[:12]
        start = time.time()

        # 1. 获取实时状态 + 可释放项
        status = self.peng.get_status()
        advice = self.peng.get_advice()

        # 2. 构建 messages（含对话历史+状态快照+可释放项）
        messages = self.context_builder.build_messages(user_input, status, advice)

        # 3. LLM 调用（快道优先）
        provider = self._select_provider(prefer_backend)
        if provider is None:
            return self._fail_result(turn_id, "no available LLM provider")

        response = provider.chat(messages=messages, temperature=0.2, max_tokens=1024)
        if not response.ok:
            return self._fail_result(turn_id, f"LLM call failed: {response.error}", provider)

        # 4. 解析决策
        decision = self._parse_decision(response.content)
        if decision is None:
            return self._fail_result(turn_id, "failed to parse LLM decision JSON",
                                     provider, raw_output=response.content[:500])

        # 5. 深道判断 + 升级重规划
        provider, decision, response = self._maybe_upgrade_deep(
            provider, decision, response, messages, prefer_backend
        )

        # 6. 释放本地深道模型（避免自指显存占用）
        self._release_local_deep(provider)

        # 7. 处理 clarify/reject 意图（不需要准入校验）
        intent = decision.get("intent", "")
        if intent in ("clarify", "reject"):
            return self._build_result(turn_id, user_input, decision, provider, response,
                                      start, validation={"all_passed": True, "steps": [],
                                                         "note": f"{intent}意图，无需执行"})

        # 8. 准入校验
        validation = self._validate_plan(decision.get("plan", []))

        # 9. 准入拒绝后自动重规划（最多1次）
        retry_info = None
        if not validation.get("all_passed", True) and len(decision.get("plan", [])) > 0:
            retry_info = self._retry_with_rejection_feedback(
                turn_id, user_input, status, advice, decision, validation,
                provider, prefer_backend
            )
            if retry_info and retry_info.get("success"):
                decision = retry_info["decision"]
                validation = retry_info["validation"]
                provider = retry_info["provider"]
                response = retry_info["response"]

        # 10. 构建结果
        result = self._build_result(turn_id, user_input, decision, provider, response, start, validation)
        if retry_info:
            result["retry"] = retry_info

        # 记录对话历史
        self.context_builder.add_to_history(user_input, result)
        return result

    def execute(self, turn_id: str, plan: list) -> dict:
        """
        执行决策计划（逐步重评估：每步后重新获取状态+准入，避免次序导致的显存问题）。

        Args:
            turn_id: 决策ID
            plan: 步骤列表 [{step, tool, args, reason}]
        """
        execution_log = []
        all_success = True

        for step in plan:
            tool_name = step.get("tool", "")
            args = step.get("args", {})
            step_num = step.get("step", 0)

            tool = self.context_builder.get_tool_by_name(tool_name)
            if tool is None:
                execution_log.append({
                    "step": step_num, "tool": tool_name,
                    "ok": False, "error": f"unknown tool: {tool_name}"
                })
                all_success = False
                break

            # 逐步重评估：写操作执行前重新过准入闸门（状态可能已变化）
            read_only = {"get_system_status", "get_model_budget", "list_models",
                         "get_task_status", "get_advice"}
            if tool_name not in read_only:
                pre_check = self._pre_execution_check(tool_name, args)
                if not pre_check.get("allowed", True):
                    execution_log.append({
                        "step": step_num, "tool": tool_name,
                        "ok": False, "rejected": True,
                        "error": f"执行前重评估被拒: {pre_check.get('reason', '')}",
                        "required_free_gb": pre_check.get("required_free_gb", 0),
                    })
                    all_success = False
                    break

            try:
                result = tool.execute(**args)
                execution_log.append({
                    "step": step_num, "tool": tool_name,
                    "ok": result.get("ok", False),
                    "result": result,
                })
                if not result.get("ok"):
                    all_success = False
                    if result.get("rejected"):
                        break
            except Exception as e:
                execution_log.append({
                    "step": step_num, "tool": tool_name,
                    "ok": False, "error": str(e)
                })
                all_success = False
                break

            # 每步后等待状态稳定（显存释放/加载需要时间）
            if step_num < len(plan):
                time.sleep(2)

        return {
            "turn_id": turn_id,
            "status": "completed" if all_success else "failed",
            "all_success": all_success,
            "execution_log": execution_log,
        }

    # === 内部方法 ===

    def _select_provider(self, prefer_backend: str):
        if prefer_backend == "fast":
            return self.providers.get_fast()
        elif prefer_backend == "deep":
            return self.providers.get_deep()
        return self.providers.get_fast() or self.providers.get_deep()

    def _fail_result(self, turn_id, error, provider=None, raw_output=None):
        r = {
            "turn_id": turn_id, "ok": False, "error": error, "status": "failed",
        }
        if provider:
            r["backend_used"] = provider.name
        if raw_output:
            r["raw_output"] = raw_output
        return r

    def _build_result(self, turn_id, user_input, decision, provider, response, start, validation):
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "turn_id": turn_id,
            "ok": True,
            "status": "planned",
            "user_input": user_input,
            "intent": decision.get("intent"),
            "plan": decision.get("plan", []),
            "estimated_vram_peak": decision.get("estimated_vram_peak", 0),
            "confidence": decision.get("confidence", 0),
            "needs_deep": decision.get("needs_deep", False),
            "backend_used": provider.name,
            "backend_tier": provider.capability_tier,
            "validation": validation,
            "latency_ms": elapsed_ms,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
        }

    def _maybe_upgrade_deep(self, provider, decision, response, messages, prefer_backend):
        """复杂任务升级深道重规划。"""
        needs_deep = decision.get("needs_deep", False)
        confidence = decision.get("confidence", 1.0)
        plan_len = len(decision.get("plan", []))
        intent = decision.get("intent", "")

        # 硬约束：chat意图绝对不走深道（避免浪费显存）
        if intent == "chat":
            needs_deep = False

        # 非SDXL的submit_task（音乐/视频/Flux等复杂创作）自动升级深道
        has_complex_gen = any(
            s.get("tool") == "submit_task" and
            str(s.get("args", {}).get("model", "SDXL")).lower() not in ("sdxl",)
            for s in decision.get("plan", [])
        )

        should_deep = (
            needs_deep or confidence < 0.7 or
            plan_len >= 3 or intent == "multimodal_creation" or
            has_complex_gen
        )

        if should_deep and prefer_backend != "fast":
            deep_provider = self.providers.get_deep()
            if deep_provider and deep_provider.name != provider.name:
                deep_response = deep_provider.chat(messages=messages, temperature=0.2, max_tokens=1024)
                if deep_response.ok:
                    deep_decision = self._parse_decision(deep_response.content)
                    if deep_decision:
                        return deep_provider, deep_decision, deep_response
        return provider, decision, response

    def _release_local_deep(self, provider):
        """释放本地深道模型（避免自指显存占用）。"""
        if provider.backend == "local" and provider.capability_tier == "deep":
            if hasattr(provider, "unload"):
                provider.unload()
                time.sleep(2)

    def _retry_with_rejection_feedback(self, turn_id, user_input, status, advice,
                                       original_decision, validation, provider, prefer_backend):
        """准入拒绝后自动重规划（注入拒绝原因，最多1次）。"""
        rejected_steps = [s for s in validation.get("steps", []) if not s.get("passed")]
        if not rejected_steps:
            return None

        rejection_reasons = "; ".join([
            f"{s.get('tool')}: {s.get('reason', 'unknown')}"
            for s in rejected_steps
        ])

        # 构建带拒绝反馈的 messages
        retry_messages = self.context_builder.build_messages(user_input, status, advice)
        retry_feedback = (
            f"\n\n## 上一次规划被准入闸门拒绝，请调整规划后重试。\n"
            f"拒绝原因：{rejection_reasons}\n"
            f"请考虑：释放显存、换更小的模型、降低分辨率、或减少并发步骤。\n"
            f"重新输出JSON决策。"
        )
        retry_messages[-1]["content"] += retry_feedback

        # 用深道重规划（更精准）
        retry_provider = self.providers.get_deep() or provider
        retry_response = retry_provider.chat(messages=retry_messages, temperature=0.1, max_tokens=1024)
        if not retry_response.ok:
            return {"success": False, "error": retry_response.error}

        retry_decision = self._parse_decision(retry_response.content)
        if retry_decision is None:
            return {"success": False, "error": "retry parse failed"}

        # 释放深道
        self._release_local_deep(retry_provider)

        # 重新校验
        retry_validation = self._validate_plan(retry_decision.get("plan", []))

        return {
            "success": True,
            "decision": retry_decision,
            "validation": retry_validation,
            "provider": retry_provider,
            "response": retry_response,
            "original_rejected": rejection_reasons,
            "attempt": 2,
        }

    def _pre_execution_check(self, tool_name: str, args: dict) -> dict:
        """执行前重评估（逐步重评估的核心）。"""
        action_map = {
            "switch_scene": "switch_scene",
            "submit_task": "submit_task",
            "cancel_task": "stop_model",
            "free_vram": "free_vram",
            "evict_process": "evict_process",
            "load_model": "load_model",
        }
        action = action_map.get(tool_name)
        if not action:
            return {"allowed": True, "reason": "no check needed"}
        return self.peng.admission_check(action, args)

    def _parse_decision(self, content: str) -> Optional[dict]:
        """解析 LLM 输出的 JSON 决策（健壮处理小模型常见的格式偏差）。"""
        if not content:
            return None
        content = content.strip()
        # 1. 直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # 2. 提取 markdown 代码块
        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            if "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
                return json.loads(json_str)
        except (json.JSONDecodeError, IndexError):
            pass
        # 3. 提取第一个 { 到最后一个 }
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start:end + 1])
        except (json.JSONDecodeError, IndexError):
            pass
        # 4. 逐字符缩短重试
        try:
            start = content.find("{")
            if start >= 0:
                candidate = content[start:]
                for _ in range(10):
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        candidate = candidate[:-1]
                        if len(candidate) < 2:
                            break
        except Exception:
            pass
        # 5. 完全没有JSON（小模型直接输出自然语言）→ 当作chat回复
        if content and len(content) < 500:
            return {
                "intent": "chat",
                "plan": [],
                "estimated_vram_peak": 0,
                "confidence": 0.5,
                "needs_deep": False,
                "reply": content.strip(),
            }
        return None

    def _validate_plan(self, plan: list) -> dict:
        """逐步骤过准入闸门校验。"""
        steps_validation = []
        all_passed = True
        read_only = {"get_system_status", "get_model_budget", "list_models",
                     "get_task_status", "get_advice"}
        action_map = {
            "switch_scene": "switch_scene",
            "submit_task": "submit_task",
            "cancel_task": "stop_model",
            "free_vram": "free_vram",
            "evict_process": "evict_process",
            "load_model": "load_model",
        }
        for step in plan:
            tool_name = step.get("tool", "")
            args = step.get("args", {})
            if tool_name in read_only:
                steps_validation.append({
                    "step": step.get("step"), "tool": tool_name,
                    "passed": True, "checks": ["read_only"],
                })
                continue
            action = action_map.get(tool_name)
            if action:
                check = self.peng.admission_check(action, args)
                passed = check.get("allowed", False)
                if not passed:
                    all_passed = False
                steps_validation.append({
                    "step": step.get("step"), "tool": tool_name,
                    "passed": passed, "checks": ["format", "rules", "budget"],
                    "reason": check.get("reason", ""),
                    "required_free_gb": check.get("required_free_gb", 0),
                })
            else:
                steps_validation.append({
                    "step": step.get("step"), "tool": tool_name,
                    "passed": True, "checks": ["unknown_tool_skipped"],
                })
        return {"all_passed": all_passed, "steps": steps_validation}
