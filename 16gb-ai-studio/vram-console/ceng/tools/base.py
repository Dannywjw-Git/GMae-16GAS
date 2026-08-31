"""
GMae v0.3.1 C-Eng — Tool 基类

所有 Tool 继承此类，提供统一的 JSON Schema 生成和执行接口。
"""
from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """
    Tool 抽象基类。

    属性：
        name: 工具名（LLM 调用时用）
        description: 工具描述（含显存代价提示，注入 System Prompt）
    """
    name: str = "base_tool"
    description: str = ""

    @abstractmethod
    def execute(self, **kwargs) -> dict:
        """执行工具，返回结果 dict。"""
        pass

    def to_json_schema(self) -> dict:
        """生成 OpenAI function calling 格式的 JSON Schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema(),
            }
        }

    @abstractmethod
    def parameters_schema(self) -> dict:
        """返回参数的 JSON Schema（properties + required）。"""
        pass
