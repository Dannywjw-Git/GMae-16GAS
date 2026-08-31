"""
GMae v0.3.1 M-Eng — 评测调度引擎

类似 Immich 后台人脸/OCR 识别：在系统空闲时自动评测新安装的模型。
- 扫描新模型（Ollama 已安装但未登记）
- 检测系统空闲（显存占用低 + 无队列任务 + 无活跃生成）
- 空闲时执行 P0 评测
- 结果写入 registry.json
- 用户任务触发时立即暂停评测
"""
import json
import os
import sys
import time
import threading
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from meng.model_scanner import ModelScanner
from meng.p0_benchmark import P0Benchmark
from ceng.tools.peng_client import PengClient


class BenchmarkEngine:
    def __init__(self, registry_path: str = None, peng_url: str = "http://127.0.0.1:8787"):
        if registry_path is None:
            registry_path = os.path.join(BASE_DIR, "resources", "registry.json")
        self.registry_path = registry_path
        self.scanner = ModelScanner(registry_path=registry_path)
        self.benchmark = P0Benchmark()
        self.peng = PengClient(base_url=peng_url)
        self._running = False
        self._thread = None
        self._pause_event = threading.Event()
        self._pause_event.set()  # 默认不暂停
        self._results_log = os.path.join(BASE_DIR, "logs", "meng-benchmark.jsonl")
        os.makedirs(os.path.dirname(self._results_log), exist_ok=True)

    def is_system_idle(self) -> tuple[bool, str]:
        """
        检测系统是否空闲（适合执行评测）。

        Returns:
            (is_idle, reason)
        """
        try:
            status = self.peng.get_status()
            if not status or status.get("ok") is False:
                return False, "P-Eng 不可用"

            gpu = status.get("gpu", {})
            free_mb = gpu.get("free_mb", 0)
            total_mb = gpu.get("total_mb", 16384)
            free_pct = free_mb / total_mb if total_mb > 0 else 0

            # 条件1：显存空闲 > 50%
            if free_pct < 0.5:
                return False, f"显存不足（空闲 {free_pct*100:.0f}%）"

            # 条件2：无队列任务
            queue = status.get("comfy_queue", {})
            running = len(queue.get("running", []))
            pending = len(queue.get("pending", []))
            if running > 0 or pending > 0:
                return False, f"队列繁忙（运行 {running}，排队 {pending}）"

            # 条件3：无 Ollama 模型加载（或只有轻量模型）
            ollama = status.get("ollama", {})
            loaded_models = ollama.get("models", [])
            if len(loaded_models) > 0:
                # 有模型加载，检查是否是评测需要的模型
                return False, f"Ollama 有 {len(loaded_models)} 个模型已加载"

            return True, "系统空闲"
        except Exception as e:
            return False, f"检测失败: {e}"

    def write_to_registry(self, model_id: str, bench_result: dict):
        """将评测结果写入 registry.json。"""
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                reg = json.load(f)

            vram_gb = bench_result.get("vram", {}).get("model_vram_gb", 0)
            speed = bench_result.get("speed", {})

            entry = {
                "id": model_id,
                "name": model_id,
                "vram_gb": vram_gb,
                "vram_verified": True,
                "ctx": 4096,
                "exclusive": False,
                "category": "llm",
                "speed_prefill_tok_s": speed.get("prefill_tok_s", 0),
                "speed_gen_tok_s": speed.get("gen_tok_s", 0),
                "smoke_passed": bench_result.get("smoke", {}).get("passed", False),
                "benchmarked_at": bench_result.get("timestamp", ""),
                "benchmark_level": "P0",
                "notes": "M-Eng 自动 P0 评测",
            }

            # 添加到 ollama.models
            if "ollama" not in reg:
                reg["ollama"] = {"models": []}
            reg["ollama"]["models"].append(entry)
            reg["last_updated"] = time.strftime("%Y-%m-%d")

            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(reg, f, ensure_ascii=False, indent=2)

            return True
        except Exception as e:
            print(f"[M-Eng] 写入 registry 失败: {e}")
            return False

    def log_result(self, result: dict):
        """记录评测结果到 JSONL 日志。"""
        try:
            with open(self._results_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def run_once(self) -> dict:
        """
        执行一次评测循环：扫描新模型 → 检测空闲 → 评测第一个新模型。

        Returns:
            执行结果摘要
        """
        # 1. 扫描新模型
        new_models = self.scanner.find_new_models()
        if not new_models:
            return {"action": "scan", "new_models": 0, "status": "idle"}

        # 2. 检测空闲
        is_idle, reason = self.is_system_idle()
        if not is_idle:
            return {"action": "scan", "new_models": len(new_models),
                    "status": "skipped", "reason": reason}

        # 3. 评测第一个新模型
        model = new_models[0]
        model_id = model["id"]
        print(f"[M-Eng] 开始 P0 评测: {model_id}")

        result = self.benchmark.benchmark(model_id)
        result["discovered_size_gb"] = model.get("size_gb", 0)
        self.log_result(result)

        if result["status"] == "completed":
            self.write_to_registry(model_id, result)
            print(f"[M-Eng] 评测完成: {model_id}, "
                  f"显存 {result['vram']['model_vram_gb']}GB, "
                  f"速度 {result['speed']['gen_tok_s']} tok/s")
        else:
            print(f"[M-Eng] 评测失败: {model_id}, {result.get('error')}")

        return {
            "action": "benchmark",
            "model": model_id,
            "status": result["status"],
            "vram_gb": result.get("vram", {}).get("model_vram_gb", 0),
            "gen_tok_s": result.get("speed", {}).get("gen_tok_s", 0),
        }

    def start(self, interval_seconds: int = 300):
        """启动后台评测循环（默认每5分钟扫描一次）。"""
        if self._running:
            return
        self._running = True

        def loop():
            while self._running:
                self._pause_event.wait()  # 暂停时阻塞
                try:
                    self.run_once()
                except Exception as e:
                    print(f"[M-Eng] 循环异常: {e}")
                # 分段 sleep，支持快速暂停
                for _ in range(interval_seconds):
                    if not self._running:
                        break
                    self._pause_event.wait()
                    time.sleep(1)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        print(f"[M-Eng] 评测引擎已启动（间隔 {interval_seconds}s）")

    def stop(self):
        """停止评测循环。"""
        self._running = False
        self._pause_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def pause(self):
        """暂停评测（用户任务开始时调用）。"""
        self._pause_event.clear()
        print("[M-Eng] 评测已暂停（用户任务进行中）")

    def resume(self):
        """恢复评测。"""
        self._pause_event.set()
        print("[M-Eng] 评测已恢复")

    def get_status(self) -> dict:
        """获取引擎状态。"""
        new_models = self.scanner.find_new_models()
        is_idle, reason = self.is_system_idle()
        return {
            "running": self._running,
            "paused": not self._pause_event.is_set(),
            "pending_models": len(new_models),
            "system_idle": is_idle,
            "idle_reason": reason,
            "pending_list": new_models,
        }


# === 独立运行测试 ===
if __name__ == "__main__":
    engine = BenchmarkEngine()
    print("=== M-Eng 状态 ===")
    print(json.dumps(engine.get_status(), ensure_ascii=False, indent=2))
    print("\n=== 执行一次扫描 ===")
    result = engine.run_once()
    print(json.dumps(result, ensure_ascii=False, indent=2))
