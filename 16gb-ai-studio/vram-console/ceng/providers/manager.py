"""
GMae v0.3.1 C-Eng — Provider 管理器

管理多个推理后端，负责探活、选择快道/深道、自动降级。
"""
import json
import os
import threading
import time
from typing import Optional

from .base import LLMProvider, LLMResponse
from .ollama_provider import OllamaProvider
from .openai_compat import OpenAICompatProvider


class ProviderManager:
    def __init__(self, config_path: str = None):
        self.providers: dict[str, LLMProvider] = {}
        self._health: dict[str, bool] = {}
        self._lock = threading.Lock()
        self._config_path = config_path
        self._load_defaults()

    def _load_defaults(self):
        """加载默认本地 Ollama 快道（0.8b）。"""
        # 快道：本地 0.8b
        fast = OllamaProvider(
            model="qwen3.5:0.8b",
            name="local-fast-0.8b",
            vram_cost_gb=3.5,
            capability_tier="light",
        )
        self.providers[fast.name] = fast

        # 深道：本地 9b（备份）
        deep = OllamaProvider(
            model="qwen3.5:9b",
            name="local-deep-9b",
            vram_cost_gb=9.9,
            capability_tier="deep",
        )
        self.providers[deep.name] = deep

    def add_provider(self, provider: LLMProvider):
        with self._lock:
            self.providers[provider.name] = provider

    def remove_provider(self, name: str):
        with self._lock:
            self.providers.pop(name, None)
            self._health.pop(name, None)

    def get_fast(self) -> Optional[LLMProvider]:
        """获取快道（本地 0.8b 优先）。"""
        with self._lock:
            for p in self.providers.values():
                if p.capability_tier == "light" and p.backend == "local":
                    if self._health.get(p.name, True):
                        return p
            # 降级：任意可用的 light 后端
            for p in self.providers.values():
                if p.capability_tier == "light" and self._health.get(p.name, True):
                    return p
        return None

    def get_deep(self) -> Optional[LLMProvider]:
        """获取深道（云端优先，其次本地 9b）。"""
        with self._lock:
            # 云端优先（0显存）
            for p in self.providers.values():
                if p.backend == "cloud" and self._health.get(p.name, True):
                    return p
            # 本地深道
            for p in self.providers.values():
                if p.capability_tier == "deep" and self._health.get(p.name, True):
                    return p
        return None

    def get_all(self) -> list[LLMProvider]:
        with self._lock:
            return list(self.providers.values())

    def health_check_all(self) -> dict[str, bool]:
        """探活所有后端，更新健康状态。"""
        results = {}
        with self._lock:
            providers = list(self.providers.values())
        for p in providers:
            ok = p.health_check()
            self._health[p.name] = ok
            results[p.name] = ok
        return results

    def get_status(self) -> list[dict]:
        """返回所有后端的状态（前端展示用）。"""
        status = []
        with self._lock:
            for p in self.providers.values():
                status.append({
                    **p.to_dict(),
                    "available": self._health.get(p.name, "unknown"),
                })
        return status

    def chat(self, messages: list, tools: list = None,
             prefer: str = "auto",
             temperature: float = 0.2, max_tokens: int = 1024) -> LLMResponse:
        """
        智能选择后端并调用。

        Args:
            prefer: "auto"（自动选择）/ "fast"（快道）/ "deep"（深道）
        """
        provider = None
        if prefer == "fast":
            provider = self.get_fast()
        elif prefer == "deep":
            provider = self.get_deep()
        else:
            provider = self.get_fast() or self.get_deep()

        if provider is None:
            return LLMResponse(content="", error="no available LLM provider")

        return provider.chat(messages, tools, temperature, max_tokens)
