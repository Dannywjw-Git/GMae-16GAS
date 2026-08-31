"""
GMae v0.3.1 M-Eng — 模型扫描器

扫描 Ollama / ComfyUI 已安装但未在 registry 中登记的新模型。
"""
import json
import os
import urllib.request
from typing import Optional


class ModelScanner:
    def __init__(self, ollama_url: str = "http://127.0.0.1:11434",
                 registry_path: str = None):
        self.ollama_url = ollama_url.rstrip("/")
        if registry_path is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            registry_path = os.path.join(base, "resources", "registry.json")
        self.registry_path = registry_path

    def scan_ollama(self) -> list[dict]:
        """扫描 Ollama 已安装模型列表。"""
        try:
            with urllib.request.urlopen(f"{self.ollama_url}/api/tags", timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data.get("models", [])
        except Exception:
            return []

    def get_registered_ids(self) -> set[str]:
        """获取 registry 中已登记的模型 ID。"""
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                reg = json.load(f)
            ids = set()
            for m in reg.get("ollama", {}).get("models", []):
                ids.add(m.get("id", ""))
            for m in reg.get("comfyui", {}).get("models", []):
                ids.add(m.get("id", ""))
            return ids
        except Exception:
            return set()

    def find_new_models(self) -> list[dict]:
        """发现未登记的新模型。"""
        installed = self.scan_ollama()
        registered = self.get_registered_ids()
        new_models = []
        for m in installed:
            name = m.get("name", "")
            # 跳过非模型（如嵌入模型、reranker）
            if any(skip in name.lower() for skip in ["bge", "reranker", "embed"]):
                continue
            if name not in registered:
                new_models.append({
                    "id": name,
                    "size_gb": round(m.get("size", 0) / (1024**3), 2),
                    "modified_at": m.get("modified_at", ""),
                    "source": "ollama",
                })
        return new_models

    def get_model_detail(self, model_name: str) -> Optional[dict]:
        """获取单个模型的详细信息（Ollama show）。"""
        try:
            payload = {"name": model_name}
            req = urllib.request.Request(
                f"{self.ollama_url}/api/show",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None
