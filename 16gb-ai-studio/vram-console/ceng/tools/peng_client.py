"""
GMae v0.3.1 C-Eng — P-Eng API Client

C-Eng 通过 HTTP 调用 P-Eng（端口 8787），不直接操作硬件。
所有写操作必须过 P-Eng 准入闸门。
"""
import json
import urllib.request
from typing import Optional


class PengClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8787", api_token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or self._auto_discover_token()

    def _auto_discover_token(self) -> str:
        """自动发现 P-Eng API token：环境变量优先，其次 .api_token 文件。"""
        import os
        env = os.environ.get("VRAM_CONSOLE_TOKEN", "")
        if env:
            return env
        try:
            # __file__ = vram-console/ceng/tools/peng_client.py
            # dirname x3 = vram-console/
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            token_path = os.path.join(base_dir, ".api_token")
            with open(token_path, "r", encoding="ascii") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_token:
            h["X-API-Key"] = self.api_token
        return h

    def _get(self, path: str, timeout: int = 10) -> dict:
        try:
            req = urllib.request.Request(f"{self.base_url}{path}", headers=self._headers())
            with urllib.request.urlopen(req, timeout=timeout) as r:
                result = json.loads(r.read().decode("utf-8"))
                # 统一确保 ok 字段存在（P-Eng 部分接口顶层无 ok，如 /api/status）
                if "ok" not in result:
                    result["ok"] = True
                return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _post(self, path: str, data: dict, timeout: int = 30) -> dict:
        try:
            req = urllib.request.Request(
                f"{self.base_url}{path}",
                data=json.dumps(data).encode("utf-8"),
                headers=self._headers(),
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                result = json.loads(r.read().decode("utf-8"))
                if "ok" not in result:
                    result["ok"] = True
                return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # === 只读 API ===
    def get_status(self) -> dict:
        return self._get("/api/status")

    def get_budget(self, context: str = None) -> dict:
        path = "/api/budget"
        if context:
            path += f"?context={context}"
        return self._get(path)

    def get_registry(self) -> dict:
        return self._get("/api/registry")

    def get_queue(self) -> dict:
        return self._get("/api/queue")

    def get_advice(self) -> dict:
        return self._get("/api/advice")

    def get_hardware(self) -> dict:
        return self._get("/api/hardware")

    # === 写操作 API（过准入闸门） ===
    def admission_check(self, action: str, args: dict) -> dict:
        """准入闸门校验（C-Eng 决策执行前必须调用）。"""
        return self._post("/api/admission", {"action": action, "args": args})

    def switch_scene(self, scene: str) -> dict:
        return self._post("/api/scene", {"scene": scene})

    def submit_task(self, model: str, params: dict) -> dict:
        return self._post("/api/queue", {"model": model, "params": params})

    def cancel_task(self, task_id: str) -> dict:
        return self._post("/api/queue/cancel", {"id": task_id})

    def free_vram(self) -> dict:
        return self._post("/api/free", {})

    def evict_process(self, pid: str) -> dict:
        return self._post("/api/guard", {"action": "kick", "pid": pid})

    def load_model(self, name: str) -> dict:
        return self._post("/api/model", {"name": name, "action": "load"})

    def stop_model(self, name: str) -> dict:
        return self._post("/api/model", {"name": name, "action": "stop"})

    # === 健康检查 ===
    def health_check(self) -> bool:
        r = self._get("/api/health", timeout=3)
        return r.get("ok", False)
