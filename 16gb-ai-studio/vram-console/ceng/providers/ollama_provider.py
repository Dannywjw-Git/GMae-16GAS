"""
GMae v0.3.1 C-Eng — Ollama Provider

本地 Ollama 推理后端，支持任意 Ollama 模型。
关键：Qwen3.5/Gemma4 必须带 think:false，否则长生成时空回复。
"""
import json
import time
import urllib.request
from typing import Optional

from .base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "qwen3.5:0.8b",
                 name: str = None,
                 vram_cost_gb: float = 3.5,
                 capability_tier: str = "light"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = name or f"ollama-{model}"
        self.backend = "local"
        self.vram_cost_gb = vram_cost_gb
        self.speed_tier = "fast" if "0.8b" in model or "0.6b" in model else "normal"
        self.capability_tier = capability_tier

    def chat(self, messages: list, tools: list = None,
             temperature: float = 0.2, max_tokens: int = 1024) -> LLMResponse:
        start = time.time()
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,  # 关键：Qwen3.5/Gemma4 默认 think 会空回复
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        if tools:
            payload["tools"] = tools

        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))

            latency_ms = int((time.time() - start) * 1000)
            content = data.get("message", {}).get("content", "")
            tool_calls = data.get("message", {}).get("tool_calls", [])
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
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
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=3) as r:
                data = json.loads(r.read().decode("utf-8"))
                return any(m.get("name") == self.model for m in data.get("models", []))
        except Exception:
            return False

    def unload(self) -> bool:
        """卸载本地模型释放显存（决策完成后调用，避免占用生成任务显存）。"""
        try:
            payload = {"model": self.model, "keep_alive": 0}
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception:
            return False
