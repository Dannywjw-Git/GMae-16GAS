"""
GMae v0.3.1 C-Eng — LLM Provider 抽象层

所有推理后端（本地 Ollama、云端 OpenAI 兼容 API）统一实现此接口。
C-Eng 决策核心只依赖 LLMProvider 抽象，不直接调用具体 API。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMResponse:
    """LLM 调用响应的统一格式。"""
    content: str
    tool_calls: list = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    model: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


class LLMProvider(ABC):
    """
    LLM 推理后端抽象接口。

    属性：
        name: 后端名称（如 "ollama-qwen0.8b"、"deepseek-cloud"）
        backend: "local" / "cloud"
        vram_cost_gb: 本地模型的显存占用，云端为 0
        speed_tier: "fast" / "normal" / "slow"
        capability_tier: "light" / "deep"
    """
    name: str = "base"
    backend: str = "local"
    vram_cost_gb: float = 0.0
    speed_tier: str = "normal"
    capability_tier: str = "light"

    @abstractmethod
    def chat(self, messages: list, tools: list = None,
             temperature: float = 0.2, max_tokens: int = 1024) -> LLMResponse:
        """
        发送聊天请求，返回统一格式的 LLMResponse。

        Args:
            messages: OpenAI 格式的消息列表 [{"role": "system/user/assistant", "content": "..."}]
            tools: 工具定义列表（OpenAI function calling 格式）
            temperature: 采样温度
            max_tokens: 最大生成 token 数
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """探测后端是否可用。"""
        pass

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "backend": self.backend,
            "vram_cost_gb": self.vram_cost_gb,
            "speed_tier": self.speed_tier,
            "capability_tier": self.capability_tier,
        }
