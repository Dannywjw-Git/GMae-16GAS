"""
GMae v0.3.1 C-Eng — P-Eng Tool 集合

10 个 Tool 封装 P-Eng API，供 LLM 决策调用。
每个 Tool 的 description 包含显存代价提示。
"""
from .base import Tool
from .peng_client import PengClient


class GetSystemStatusTool(Tool):
    name = "get_system_status"
    description = "获取系统当前状态：显存使用、当前场景、已加载模型、队列深度、进程列表。只读操作，无显存代价。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> dict:
        return self.client.get_status()


class GetModelBudgetTool(Tool):
    name = "get_model_budget"
    description = "查询指定模型的显存预算与可行性：能否加载、需要释放多少、差多少。只读操作。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "模型ID，如 SDXL、Flux-Q5、qwen3.5:9b"}
            },
            "required": ["model"],
        }

    def execute(self, model: str = "", **kwargs) -> dict:
        budget = self.client.get_budget()
        models = budget.get("models", [])
        target = next((m for m in models if m.get("id") == model or m.get("name") == model), None)
        return {"ok": True, "model": target, "full_budget": budget}


class ListModelsTool(Tool):
    name = "list_models"
    description = "列出所有已登记的模型及其显存、能力、是否已加载。只读操作。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> dict:
        return self.client.get_registry()


class SwitchSceneTool(Tool):
    name = "switch_scene"
    description = "切换工作场景。会自动释放显存并启动/停止对应容器。写操作，过准入闸门。场景：dialogue(对话)/comfy(文生图)/fooocus(高质量出图)/music(音乐)/game(游戏)"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": ["dialogue", "comfy", "fooocus", "music", "game"]}
            },
            "required": ["target"],
        }

    def execute(self, target: str = "", **kwargs) -> dict:
        # 先过准入闸门
        check = self.client.admission_check("switch_scene", {"target": target})
        if not check.get("allowed"):
            return {"ok": False, "rejected": True, "reason": check.get("reason", ""),
                    "required_free_gb": check.get("required_free_gb", 0)}
        return self.client.switch_scene(target)


class SubmitTaskTool(Tool):
    name = "submit_task"
    description = "提交生成任务到队列（文生图/文生视频/文生音乐）。写操作，过准入闸门。模型需在registry中登记，params包含prompt/seed/width/height等。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "模型ID，如 SDXL、Flux-Q5、Wan2.2-TI2V、Music3"},
                "params": {"type": "object", "description": "生成参数，如 {prompt:..., seed:42, width:512, height:512}"}
            },
            "required": ["model", "params"],
        }

    def execute(self, model: str = "", params: dict = None, **kwargs) -> dict:
        check = self.client.admission_check("submit_task", {"model": model, "params": params or {}})
        if not check.get("allowed"):
            return {"ok": False, "rejected": True, "reason": check.get("reason", ""),
                    "required_free_gb": check.get("required_free_gb", 0)}
        return self.client.submit_task(model, params or {})


class CancelTaskTool(Tool):
    name = "cancel_task"
    description = "取消队列中的任务。写操作。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        }

    def execute(self, task_id: str = "", **kwargs) -> dict:
        return self.client.cancel_task(task_id)


class GetTaskStatusTool(Tool):
    name = "get_task_status"
    description = "查询任务队列状态和进度。只读操作。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> dict:
        return self.client.get_queue()


class FreeVramTool(Tool):
    name = "free_vram"
    description = "主动释放显存（ComfyUI /free + 卸载 Ollama 模型）。写操作，过准入闸门。释放后显存应回到安全线以下。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> dict:
        check = self.client.admission_check("free_vram", {})
        if not check.get("allowed"):
            return {"ok": False, "rejected": True, "reason": check.get("reason", "")}
        return self.client.free_vram()


class EvictProcessTool(Tool):
    name = "evict_process"
    description = "强制驱逐指定GPU进程（高风险，需用户确认）。写操作，过准入闸门。仅用于白占进程或异常进程。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"pid": {"type": "string", "description": "进程PID"}},
            "required": ["pid"],
        }

    def execute(self, pid: str = "", **kwargs) -> dict:
        check = self.client.admission_check("evict_process", {"pid": pid})
        if not check.get("allowed"):
            return {"ok": False, "rejected": True, "reason": check.get("reason", "")}
        return self.client.evict_process(pid)


class GetAdviceTool(Tool):
    name = "get_advice"
    description = "获取 P-Eng 智能建议：当前可释放项、未归因显存诊断、释放收益排序。只读操作，作为决策参考输入。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> dict:
        return self.client.get_advice()


class LoadModelTool(Tool):
    name = "load_model"
    description = "预热/加载指定 Ollama 对话模型（如 qwen3.5:9b）。用于用户要求切换对话模型时。写操作，过准入闸门。"

    def __init__(self, client: PengClient):
        self.client = client

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Ollama模型名，如 qwen3.5:9b"},
            },
            "required": ["model"],
        }

    def execute(self, model: str = "", **kwargs) -> dict:
        if not model:
            return {"ok": False, "error": "model name required"}
        check = self.client.admission_check("load_model", {"model": model})
        if not check.get("allowed"):
            return {"ok": False, "rejected": True, "reason": check.get("reason", "")}
        import urllib.request, json as _json
        try:
            payload = {"model": model, "prompt": "hi", "stream": False, "keep_alive": "5m"}
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate",
                data=_json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                _json.loads(r.read().decode())
            return {"ok": True, "model": model, "status": "loaded"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def create_all_tools(client: PengClient) -> list[Tool]:
    """创建所有 P-Eng Tool 实例。"""
    return [
        GetSystemStatusTool(client),
        GetModelBudgetTool(client),
        ListModelsTool(client),
        SwitchSceneTool(client),
        SubmitTaskTool(client),
        CancelTaskTool(client),
        GetTaskStatusTool(client),
        FreeVramTool(client),
        EvictProcessTool(client),
        GetAdviceTool(client),
        LoadModelTool(client),
    ]


def get_tool_schemas(tools: list[Tool]) -> list[dict]:
    """获取所有 Tool 的 JSON Schema（注入 LLM System Prompt）。"""
    return [t.to_json_schema() for t in tools]
