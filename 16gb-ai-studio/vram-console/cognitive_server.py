#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae v0.3.1 C-Eng — 认知引擎 HTTP 服务（端口 8789）

C-Eng 是 LLM 驱动的调度大脑，用户用自然语言表达创作意图，
C-Eng 理解意图、规划多模态任务序列、动态管理显存资源，P-Eng 负责安全执行。

API:
  POST /api/chat      自然语言编排请求（核心）
  POST /api/execute   执行已规划的决策
  GET  /api/decision/{turn_id}  查询决策详情
  GET  /api/providers 已配置推理后端列表
  GET  /api/health    健康检查

启动: python cognitive_server.py
"""
import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 确保可以导入 ceng 包和 server.py（P-Eng）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from ceng.decision_engine import DecisionEngine
from ceng.decision_logger import DecisionLogger
from ceng.providers.manager import ProviderManager
from ceng.providers.ollama_provider import OllamaProvider
from ceng.providers.openai_compat import OpenAICompatProvider
from ceng.tools.peng_client import PengClient
from ceng.privacy_filter import PrivacyFilter

# === 配置 ===
CENG_PORT = int(os.environ.get("CENG_PORT", "8789"))
CENG_HOST = os.environ.get("CENG_HOST", "127.0.0.1")
PENG_URL = os.environ.get("PENG_URL", "http://127.0.0.1:8787")
PENG_TOKEN = os.environ.get("PENG_TOKEN", "")

# === 全局实例 ===
peng_client = PengClient(base_url=PENG_URL, api_token=PENG_TOKEN)
provider_manager = ProviderManager()
decision_engine = DecisionEngine(peng_client, provider_manager)
decision_logger = DecisionLogger()
privacy_filter = PrivacyFilter(send_prompts_to_cloud=False)

# 决策结果缓存（turn_id -> decision）
_decision_cache: dict = {}


def add_cloud_provider(name: str, base_url: str, api_key: str, model: str):
    """添加云端推理后端。"""
    provider = OpenAICompatProvider(name=name, base_url=base_url, api_key=api_key, model=model)
    provider_manager.add_provider(provider)
    return {"ok": True, "name": name, "available": provider.health_check()}


class CEngHandler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        if self.path == "/api/health":
            peng_ok = peng_client.health_check()
            providers_ok = provider_manager.health_check_all()
            self._json({
                "ok": True,
                "peng_connected": peng_ok,
                "providers": providers_ok,
                "port": CENG_PORT,
                "ts": int(time.time()),
            })
        elif self.path == "/api/providers":
            self._json({"ok": True, "providers": provider_manager.get_status()})
        elif self.path.startswith("/api/decision/"):
            turn_id = self.path.split("/api/decision/")[1]
            result = decision_logger.get_by_turn_id(turn_id)
            if result.get("decision") or result.get("execution"):
                self._json({"ok": True, **result})
            else:
                # 从缓存查找
                cached = _decision_cache.get(turn_id)
                if cached:
                    self._json({"ok": True, "decision": cached})
                else:
                    self._json({"ok": False, "error": "turn_id not found"}, 404)
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        data = self._read_body()

        if self.path == "/api/chat":
            # 核心：自然语言编排
            user_input = data.get("message", "")
            execute = data.get("execute", False)
            prefer = data.get("preferred_backend", "auto")

            if not user_input:
                self._json({"ok": False, "error": "message is required"}, 400)
                return

            # 规划
            decision = decision_engine.plan(user_input, prefer_backend=prefer)
            decision_logger.log_decision(decision)
            _decision_cache[decision["turn_id"]] = decision

            # 自动执行
            if execute and decision.get("ok") and decision.get("validation", {}).get("all_passed"):
                execution = decision_engine.execute(decision["turn_id"], decision.get("plan", []))
                decision_logger.log_execution(decision["turn_id"], execution)
                decision["execution"] = execution
                decision["status"] = execution.get("status", "completed")

            self._json(decision)

        elif self.path == "/api/execute":
            # 执行已规划的决策
            turn_id = data.get("turn_id", "")
            plan = data.get("plan")

            if not turn_id or not plan:
                self._json({"ok": False, "error": "turn_id and plan are required"}, 400)
                return

            execution = decision_engine.execute(turn_id, plan)
            decision_logger.log_execution(turn_id, execution)
            self._json(execution)

        elif self.path == "/api/providers":
            # 添加云端后端
            name = data.get("name", "")
            base_url = data.get("base_url", "")
            api_key = data.get("api_key", "")
            model = data.get("model", "")
            if not all([name, base_url, api_key, model]):
                self._json({"ok": False, "error": "name, base_url, api_key, model are required"}, 400)
                return
            result = add_cloud_provider(name, base_url, api_key, model)
            self._json(result)

        elif self.path == "/api/providers/health":
            # 手动触发健康检查
            results = provider_manager.health_check_all()
            self._json({"ok": True, "results": results})

        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass  # 静默 HTTP 日志


def main():
    print("=" * 60)
    print("GMae v0.3.1 C-Eng — 认知引擎服务")
    print("=" * 60)
    print(f"  监听: {CENG_HOST}:{CENG_PORT}")
    print(f"  P-Eng: {PENG_URL}")

    # 检查 P-Eng 连接
    peng_ok = peng_client.health_check()
    print(f"  P-Eng 连接: {'✅ 已连接' if peng_ok else '❌ 未连接（C-Eng 仍可启动，决策时会重试）'}")

    # 检查 LLM 后端
    fast = provider_manager.get_fast()
    deep = provider_manager.get_deep()
    print(f"  快道: {fast.name if fast else '无可用快道'}")
    print(f"  深道: {deep.name if deep else '无可用深道（云端未配置）'}")

    server = ThreadingHTTPServer((CENG_HOST, CENG_PORT), CEngHandler)
    print(f"\n✅ C-Eng 已启动，端口 {CENG_PORT}")
    print(f"   POST /api/chat  {{message: \"出一张猫的图\"}}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nC-Eng 已停止")
        server.server_close()


if __name__ == "__main__":
    main()
