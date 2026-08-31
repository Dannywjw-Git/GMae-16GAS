"""
GMae v0.3.1 M-Eng — P0 基础评测

新模型的基础能力评测：
1. 显存占用（加载后实测）
2. 推理速度（prefill tok/s + generation tok/s）
3. 基础能力冒烟（能否正常生成中文/英文/代码）
4. context 上限探测（可选）

评测在系统空闲时执行，避免影响用户任务。
"""
import json
import time
import urllib.request
from typing import Optional


class P0Benchmark:
    def __init__(self, ollama_url: str = "http://127.0.0.1:11434"):
        self.ollama_url = ollama_url.rstrip("/")

    def _chat(self, model: str, messages: list, num_predict: int = 128,
              ctx: int = 4096) -> dict:
        """调用 Ollama chat，返回性能数据。"""
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"num_predict": num_predict, "num_ctx": ctx}
        }
        start = time.time()
        req = urllib.request.Request(
            f"{self.ollama_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode("utf-8"))
        elapsed = time.time() - start
        return {
            "content": data.get("message", {}).get("content", ""),
            "prompt_eval_count": data.get("prompt_eval_count", 0),
            "eval_count": data.get("eval_count", 0),
            "total_duration_ms": int(data.get("total_duration", 0) / 1e6),
            "load_duration_ms": int(data.get("load_duration", 0) / 1e6),
            "prompt_eval_duration_ms": int(data.get("prompt_eval_duration", 0) / 1e6),
            "eval_duration_ms": int(data.get("eval_duration", 0) / 1e6),
            "wall_time_s": round(elapsed, 2),
        }

    def _get_gpu_vram(self) -> tuple[float, float]:
        """获取当前 GPU 显存使用（MB）。"""
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            parts = result.stdout.strip().split(",")
            return float(parts[0]), float(parts[1])
        except Exception:
            return 0, 0

    def benchmark(self, model: str, ctx: int = 4096) -> dict:
        """
        执行 P0 评测。

        Returns:
            评测结果 dict（显存、速度、能力冒烟）
        """
        result = {
            "model": model,
            "ctx": ctx,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "running",
        }

        try:
            # 1. 记录加载前显存
            vram_before, vram_total = self._get_gpu_vram()

            # 2. 预热加载（第一次调用包含加载时间）
            warmup = self._chat(model, [{"role": "user", "content": "hi"}],
                                num_predict=10, ctx=ctx)
            time.sleep(2)  # 等待显存稳定

            # 3. 记录加载后显存
            vram_after, _ = self._get_gpu_vram()
            model_vram_mb = vram_after - vram_before

            # 4. 速度测试（中文生成）
            speed_test = self._chat(model, [
                {"role": "system", "content": "你是一个助手。"},
                {"role": "user", "content": "用三句话介绍一下你自己。"}
            ], num_predict=128, ctx=ctx)

            # 计算 tok/s
            prefill_tok_s = 0
            gen_tok_s = 0
            if speed_test["prompt_eval_duration_ms"] > 0:
                prefill_tok_s = round(speed_test["prompt_eval_count"] /
                                      (speed_test["prompt_eval_duration_ms"] / 1000), 1)
            if speed_test["eval_duration_ms"] > 0:
                gen_tok_s = round(speed_test["eval_count"] /
                                  (speed_test["eval_duration_ms"] / 1000), 1)

            # 5. 能力冒烟测试
            smoke = self._chat(model, [
                {"role": "user", "content": "1+1等于几？只回答数字。"}
            ], num_predict=32, ctx=ctx)
            smoke_ok = "2" in smoke["content"]

            # 6. 卸载模型
            self._unload_model(model)

            result.update({
                "status": "completed",
                "vram": {
                    "before_mb": vram_before,
                    "after_mb": vram_after,
                    "model_vram_mb": model_vram_mb,
                    "model_vram_gb": round(model_vram_mb / 1024, 2),
                    "total_gb": round(vram_total / 1024, 1),
                },
                "speed": {
                    "prefill_tok_s": prefill_tok_s,
                    "gen_tok_s": gen_tok_s,
                    "prompt_eval_count": speed_test["prompt_eval_count"],
                    "eval_count": speed_test["eval_count"],
                },
                "smoke": {
                    "passed": smoke_ok,
                    "response": smoke["content"][:100],
                },
                "sample_output": speed_test["content"][:200],
            })
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            try:
                self._unload_model(model)
            except Exception:
                pass

        return result

    def _unload_model(self, model: str):
        """卸载模型（发送 keep_alive=0 的请求）。"""
        try:
            payload = {"model": model, "keep_alive": 0}
            req = urllib.request.Request(
                f"{self.ollama_url}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
