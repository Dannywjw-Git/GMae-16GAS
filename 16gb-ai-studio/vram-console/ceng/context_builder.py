"""
GMae v0.3.1 C-Eng — 上下文构建器

从 P-Eng 获取实时状态，构建 LLM 决策所需的精简上下文。
包括：System Prompt（含决策模式引导）、状态快照（队列+模型+可释放项）、
对话历史（最近3轮）、few-shot 示例（6个覆盖典型局面）。
"""
import json
import os
from typing import Optional

from .tools.peng_client import PengClient
from .tools.peng_tools import create_all_tools, get_tool_schemas


SYSTEM_PROMPT_TEMPLATE = """你是 GMae（GPU Maestro）显存指挥家的调度大脑，负责在消费级 GPU 上编排多模态 AI 任务。

## 硬件约束
- GPU: {gpu_name}，总显存 {vram_total_gb}GB，底噪 {base_noise_gb}GB
- 当前显存：已用 {vram_used_gb}GB，可用 {vram_free_gb}GB
- 危险线 {danger_gb}GB，超过则必须先释放

## 铁律（不可违反）
R1: 禁止两个 ≥5G 模型同时常驻
R2: Flux/27B/Wan2.2 等独占模型不与其他 AI 负载共存
R3: 禁止 num_ctx 超 8192（可能导致死机）
R4: 禁止双 ollama serve 进程
R6: 禁止 Fooocus/ComfyUI 模型常驻于对话态
R7: 禁止未登记模型占用显存

## 决策模式（按当前局面选择标准流程，不要跳步）

### 局面A：显存充足（空闲>8GB）+ 目标模型已加载
→ 直接 submit_task，不需要释放或切换场景

### 局面B：显存不足（空闲<8GB）但可释放
→ 步骤1: free_vram（释放显存）
→ 步骤2: 等待释放完成后再评估
→ 步骤3: 如果模型未加载，switch_scene 到对应场景
→ 步骤4: submit_task
→ 注意：释放后显存可能仍不足，保守估计峰值

### 局面C：目标模型未加载
→ 步骤1: switch_scene 到对应场景（comfy=文生图, music=音乐, dialogue=对话）
→ 步骤2: submit_task
→ 如果显存不足，先按局面B处理

### 局面D：队列有任务在运行
→ 不要提交新任务，提示用户队列忙
→ 或者建议用户等待当前任务完成，或取消现有任务

### 局面E：多步骤/多模态任务
→ 每一步都会改变显存状态，后续步骤要保守估计
→ 第一步完成后，后续模型的加载需要重新评估显存
→ 如果第一步用了大模型（如Flux 13GB），后续步骤可能没有显存

### 局面F：请求模糊/不确定/缺少关键信息
→ intent 设为 "clarify"
→ plan 为空数组
→ 在 reason 中说明需要澄清什么
→ 不要猜测用户意图，不要执行任何操作

### 局面G：请求的模型/操作不可行（如未登记模型、显存永远不够）
→ intent 设为 "reject"
→ plan 为空数组
→ 在 reason 中说明为什么不可行，建议替代方案（如用更小的模型、降低分辨率）

### 局面H：简单对话/寒暄（你好、谢谢、再见、你是谁等）
→ intent 设为 "chat"
→ plan 为空数组（不调用任何工具）
→ 在 reply 字段中直接写回复文字（自然、友好、简短）
→ needs_deep 必须为 false（简单对话绝对不走深道，避免浪费显存）
→ 不要执行 get_system_status 或任何工具调用

## 可用工具（在 plan 中通过 tool 字段引用）
{tools_list}

## 输出格式
必须输出 JSON，不输出自然语言：
{{
  "intent": "single_task|multimodal_creation|query|system_management|clarify|reject|chat",
  "plan": [
    {{"step": 1, "tool": "工具名", "args": {{...}}, "reason": "为什么这么做"}}
  ],
  "estimated_vram_peak": 数字,
  "confidence": 0.0-1.0,
  "needs_deep": true/false,
  "reply": "可选，仅当 intent=chat 时填写直接回复的文字"
}}

## 示例

### 示例1：查询（局面A变体，只读）
用户：当前显存状态
输出：{{"intent":"query","plan":[{{"step":1,"tool":"get_system_status","args":{{}},"reason":"查询系统状态"}}],"estimated_vram_peak":0,"confidence":1.0,"needs_deep":false}}

### 示例2：显存充足时文生图（局面A）
用户：出一张猫的图
状态：空闲12GB，SDXL已加载
输出：{{"intent":"single_task","plan":[{{"step":1,"tool":"submit_task","args":{{"model":"SDXL","params":{{"prompt":"a cute cat","seed":42,"width":512,"height":512}}}},"reason":"显存充足且SDXL已加载，直接提交"}}],"estimated_vram_peak":7.5,"confidence":0.95,"needs_deep":false}}

### 示例3：显存不足时文生图（局面B）
用户：出一张猫的图
状态：空闲2GB，SDXL未加载，9b模型占着
输出：{{"intent":"single_task","plan":[{{"step":1,"tool":"free_vram","args":{{}},"reason":"显存不足，先释放9b等模型占用的显存"}},{{"step":2,"tool":"switch_scene","args":{{"target":"comfy"}},"reason":"切换到文生图场景加载SDXL"}},{{"step":3,"tool":"submit_task","args":{{"model":"SDXL","params":{{"prompt":"a cute cat","seed":42,"width":512,"height":512}}}},"reason":"释放后显存充足，提交SDXL生成"}}],"estimated_vram_peak":7.5,"confidence":0.85,"needs_deep":false}}

### 示例4：多模态创作（局面E）
用户：先出一张日落图，再配一段音乐
输出：{{"intent":"multimodal_creation","plan":[{{"step":1,"tool":"free_vram","args":{{}},"reason":"多模态任务先释放显存确保空间"}},{{"step":2,"tool":"switch_scene","args":{{"target":"comfy"}},"reason":"先切到文生图场景"}},{{"step":3,"tool":"submit_task","args":{{"model":"SDXL","params":{{"prompt":"sunset landscape","seed":42,"width":512,"height":512}}}},"reason":"第一步生成日落图"}},{{"step":4,"tool":"switch_scene","args":{{"target":"music"}},"reason":"图完成后切到音乐场景（每步后显存会变化，保守执行）"}}],"estimated_vram_peak":10.0,"confidence":0.7,"needs_deep":true}}

### 示例5：系统管理（局面B变体）
用户：显存不够了，帮我释放一下
输出：{{"intent":"system_management","plan":[{{"step":1,"tool":"free_vram","args":{{}},"reason":"主动释放ComfyUI和Ollama占用的显存"}},{{"step":2,"tool":"get_advice","args":{{}},"reason":"释放后检查是否还有可释放项"}}],"estimated_vram_peak":0,"confidence":0.95,"needs_deep":false}}

### 示例6：模糊请求（局面F）
用户：帮我弄一下
输出：{{"intent":"clarify","plan":[],"estimated_vram_peak":0,"confidence":0.3,"needs_deep":false}}

### 示例7：不可行请求（局面G）
用户：用HunyuanVideo 13B出视频（该模型需52GB显存）
输出：{{"intent":"reject","plan":[],"estimated_vram_peak":52,"confidence":0.9,"needs_deep":false}}

### 示例8：文生音乐（创作类，必须用submit_task）
用户：生成一首女生演唱的爱情歌曲
状态：空闲12GB
输出：{{"intent":"single_task","plan":[{{"step":1,"tool":"free_vram","args":{{}},"reason":"Music3需13GB独占显存，先释放确保空间"}},{{"step":2,"tool":"switch_scene","args":{{"target":"music"}},"reason":"切换到音乐场景"}},{{"step":3,"tool":"submit_task","args":{{"model":"Music3","params":{{"prompt":"female vocal love song, romantic, pop style","seed":42}}}},"reason":"提交Music3生成任务"}}],"estimated_vram_peak":13.0,"confidence":0.85,"needs_deep":true}}

### 示例9：简单对话（局面H，不调用工具）
用户：你好
输出：{{"intent":"chat","plan":[],"estimated_vram_peak":0,"confidence":1.0,"needs_deep":false,"reply":"你好！我是GMae显存指挥家，可以帮你生成图片、视频、音乐，也可以查询显存状态。有什么想创作的吗？"}}

### 示例10：感谢/告别（局面H，不调用工具）
用户：谢谢
输出：{{"intent":"chat","plan":[],"estimated_vram_peak":0,"confidence":1.0,"needs_deep":false,"reply":"不客气！随时可以找我创作。"}}

## 重要提醒
- 创作类请求（出图/生成视频/生成音乐/做一首歌）必须用 submit_task，不要只做查询
- 音乐生成用 Music3（13GB独占）或 ACE-Step（6GB），视频用 Wan2.2-TI2V（10.9GB）
- 非图片类创作（音乐/视频）建议 needs_deep=true，需要深道理解复杂语义
- 模型显存不足时，先 free_vram 再 switch_scene 再 submit_task
"""


class ContextBuilder:
    def __init__(self, peng_client: PengClient, tools: list = None):
        self.peng = peng_client
        self.tools = tools or create_all_tools(peng_client)
        self.tool_schemas = get_tool_schemas(self.tools)
        self._conversation_history: list = []  # 最近3轮对话 {user_input, intent, plan_summary}

    def build_system_prompt(self, status: dict) -> str:
        """构建 System Prompt（含硬件状态、铁律、决策模式、可用工具、示例）。"""
        gpu = status.get("gpu", {})
        hardware = status.get("vram_ledger", {})
        tools_desc = []
        for t in self.tools:
            params = t.parameters_schema().get("properties", {})
            param_str = ", ".join(params.keys()) if params else "无"
            tools_desc.append(f"- {t.name}({param_str}): {t.description}")
        tools_list = "\n".join(tools_desc)
        return SYSTEM_PROMPT_TEMPLATE.format(
            gpu_name=gpu.get("name", "Unknown GPU"),
            vram_total_gb=round(gpu.get("total_mb", 16384) / 1024, 1),
            vram_used_gb=round(gpu.get("used_mb", 0) / 1024, 1),
            vram_free_gb=round(gpu.get("free_mb", 16384) / 1024, 1),
            base_noise_gb=round(hardware.get("noise_mb", 1200) / 1024, 2),
            danger_gb=round((gpu.get("total_mb", 16384) * 0.92) / 1024, 1),
            tools_list=tools_list,
        )

    def build_state_snapshot(self, status: dict, advice: dict = None) -> dict:
        """构建详细状态快照（注入 LLM 上下文）。"""
        gpu = status.get("gpu", {})
        queue = status.get("comfy_queue", {})
        running = queue.get("running", [])
        pending = queue.get("pending", [])

        snapshot = {
            "vram": {
                "total_gb": round(gpu.get("total_mb", 0) / 1024, 1),
                "used_gb": round(gpu.get("used_mb", 0) / 1024, 1),
                "free_gb": round(gpu.get("free_mb", 0) / 1024, 1),
            },
            "scene": status.get("scene", "unknown"),
            "danger_level": status.get("vram_ledger", {}).get("danger_level", "safe"),
            "loaded_models": self._extract_loaded_models(status),
            "queue": {
                "running_count": len(running),
                "pending_count": len(pending),
                "running": [{"id": t.get("id", "")[:8], "model": t.get("model", "")} for t in running[:3]],
                "busy": len(running) > 0,
            },
        }

        # 可释放项（如果提供了advice）
        if advice:
            releasable = advice.get("releasable", [])
            snapshot["releasable_items"] = [
                {"name": r.get("name", ""), "vram_gb": r.get("vram_gb", 0)}
                for r in releasable[:5]
            ]
            snapshot["total_releasable_gb"] = advice.get("total_releasable_gb", 0)

        return snapshot

    def _extract_loaded_models(self, status: dict) -> list:
        """提取已加载模型列表（含大小和来源）。"""
        models = []
        ollama = status.get("ollama", {})
        for m in ollama.get("models", []):
            models.append({
                "name": m.get("name", ""),
                "size_gb": round(m.get("size_gb", 0), 1),
                "source": "ollama"
            })
        comfy = status.get("comfyui_models", {})
        for m in comfy.get("models", []):
            models.append({
                "name": m.get("name", ""),
                "size_gb": round(m.get("vram_gb", 0), 1),
                "source": "comfyui"
            })
        return models[:8]

    def build_conversation_context(self) -> str:
        """构建对话历史上下文（最近3轮，精简摘要）。"""
        if not self._conversation_history:
            return ""
        lines = ["## 最近对话历史（用于理解指代，如'再来一张'）"]
        for i, h in enumerate(self._conversation_history[-3:], 1):
            plan_summary = ""
            if h.get("plan"):
                tools = [s.get("tool", "") for s in h["plan"][:3]]
                plan_summary = f"，执行: {'→'.join(tools)}"
            lines.append(f"{i}. 用户: {h.get('user_input', '')[:60]}{plan_summary}")
        return "\n".join(lines) + "\n"

    def build_messages(self, user_input: str, status: dict = None,
                       advice: dict = None) -> list:
        """构建完整的 messages 列表（system + user，含状态快照和对话历史）。"""
        if status is None:
            status = self.peng.get_status()
        system_prompt = self.build_system_prompt(status)
        state_snapshot = self.build_state_snapshot(status, advice)
        conv_context = self.build_conversation_context()

        user_msg = (
            f"{conv_context}"
            f"当前系统状态：\n{json.dumps(state_snapshot, ensure_ascii=False, indent=2)}\n\n"
            f"用户请求：{user_input}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

    def add_to_history(self, user_input: str, decision: dict):
        """记录对话历史（最近3轮）。"""
        self._conversation_history.append({
            "user_input": user_input,
            "intent": decision.get("intent", ""),
            "plan": decision.get("plan", []),
        })
        if len(self._conversation_history) > 3:
            self._conversation_history.pop(0)

    def get_tool_by_name(self, name: str):
        """按名称获取 Tool 实例。"""
        for t in self.tools:
            if t.name == name:
                return t
        return None
