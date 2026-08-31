"""
GMae v0.3.1 C-Eng — OpenAI 兼容 Provider

支持所有 OpenAI 兼容的云端 API：DeepSeek、通义千问、Kimi、智谱、OpenAI 等。
vram_cost_gb = 0（云端推理不占本地显存）。
"""
import json
import time
import urllib.request
from typing import Optional

from .base import LLMProvider, LLMResponse


class OpenAICompatProvider(LLMProvider):
    def __init__(self, name: str, base_url: str, api_key: str, model: str,
                 capability_tier: str = "deep"):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key  # 从加密存储读取，不明文落盘
        self.model = model
        self.backend = "cloud"
        self.vram_cost_gb = 0.0
        self.speed_tier = "normal"
        self.capability_tier = capability_tier

    def chat(self, messages: list, tools: list = None,
             temperature: float = 0.2, max_tokens: int = 1024) -> LLMResponse:
        start = time.time()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                }
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))

            latency_ms = int((time.time() - start) * 1000)
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls", [])
            usage = data.get("usage", {})

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
                model=self.model,
            )
        except Exception as e:
            return LLMResponse(
                content="",
                latency_ms=int((time.time() - start) * 1000),
                model=self.model,
                error=str(e),
            )

    def health_check(self) -> bool:
        """最小请求验证连通性和 Key 有效性。"""
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                }
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except Exception:
            return False
