#!/usr/bin/env python3
"""
Ollama Batch Evaluator — LLM 批量评估脚本
用法:
  # 评估指定模型
  python ollama_batch_eval.py --model qwen3.5:9b --output ./results/llm_test

  # 只跑快速模式（3道核心题）
  python ollama_batch_eval.py --model qwen3.5:9b --quick

  # 指定 Ollama 地址
  python ollama_batch_eval.py --model qwen3.5:9b --server http://127.0.0.1:11434
"""

import argparse
import json
import time
import os
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vram_monitor import VRAMMonitor

# ============================================================
# 标准 LLM 测试题
# ============================================================
LLM_TESTS = {
    "LLM-01": {
        "type": "推理",
        "prompt": "一个农夫要带狼、羊、白菜过河，船每次只能带一样。农夫不在时狼吃羊、羊吃白菜。怎么安排才能全部安全过河？请一步步说明。",
        "auto_check": "keywords",  # 检查关键词
        "expected_keywords": ["先带羊", "羊过去", "带羊过去", "羊先过"],
    },
    "LLM-02": {
        "type": "编程",
        "prompt": "用Python写一个快速排序函数，要求支持自定义比较函数，并有完整的类型注解和docstring。只输出代码。",
        "auto_check": "code_run",  # 尝试运行代码
    },
    "LLM-03": {
        "type": "知识",
        "prompt": "解释Transformer模型中自注意力机制的计算过程，包括Q/K/V的含义和缩放点积注意力的公式。",
        "auto_check": "keywords",
        "expected_keywords": ["Query", "Key", "Value", "Q", "K", "V", "softmax", "缩放", "scale"],
    },
    "LLM-04": {
        "type": "指令遵循",
        "prompt": "用不超过50个字，以李白的诗风，写一首关于人工智能的七言绝句。",
        "auto_check": "length",  # 检查长度
        "max_length": 50,
    },
    "LLM-05": {
        "type": "多轮对话",
        "prompt": None,  # 多轮特殊处理
        "turns": [
            "我喜欢科幻电影",
            "推荐3部不太知名但评分很高的科幻电影",
            "第二部的导演还拍过什么？",
        ],
        "auto_check": "multi_turn",
    },
    "LLM-06": {
        "type": "数学",
        "prompt": "一个水池有进水管和出水管。单开进水管6小时注满，单开出水管8小时放完。两管同时开，几小时注满？请写出计算过程。",
        "auto_check": "numeric",
        "expected_answer": 24,  # 1/(1/6-1/8)=24
        "tolerance": 0.5,
    },
    "LLM-07": {
        "type": "创意",
        "prompt": "为一个16GB显存的AI工作室产品写一句slogan，要求不超过10个字，包含'无限'一词。",
        "auto_check": "keywords",
        "expected_keywords": ["无限"],
    },
    "LLM-08": {
        "type": "中文理解",
        "prompt": "请用中文解释'显存调度'的含义，要求让一个完全不懂技术的人也能听懂，用一个生活中的比喻来说明。",
        "auto_check": "keywords",
        "expected_keywords": ["比喻", "比如", "就像", "好比"],
    },
}

# 快速模式：只跑核心3题
QUICK_TESTS = ["LLM-01", "LLM-04", "LLM-06"]


class OllamaEvaluator:
    """Ollama 批量评估器。"""

    def __init__(self, server="http://127.0.0.1:11434", model="qwen3.5:9b", output_dir="./results"):
        self.server = server.rstrip("/")
        self.model = model
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.results = []

    def _chat(self, messages, temperature=0.7):
        """调用 Ollama chat API。"""
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.server}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        start = time.time()
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - start

        eval_count = data.get("eval_count", 0)
        eval_duration = data.get("eval_duration", 1)
        tokens_per_s = eval_count / (eval_duration / 1e9) if eval_duration > 0 else 0

        return {
            "content": data.get("message", {}).get("content", ""),
            "total_time_s": round(elapsed, 2),
            "eval_count": eval_count,
            "tokens_per_s": round(tokens_per_s, 2),
        }

    def _auto_check(self, test_id, test_def, response):
        """自动检查答案正确性。"""
        check_type = test_def.get("auto_check")
        content = response.get("content", "")

        if check_type == "keywords":
            keywords = test_def.get("expected_keywords", [])
            found = [kw for kw in keywords if kw.lower() in content.lower()]
            return {
                "passed": len(found) > 0,
                "detail": f"命中关键词: {found if found else '无'}",
                "score": 1.0 if found else 0.0,
            }
        elif check_type == "length":
            max_len = test_def.get("max_length", 100)
            actual_len = len(content.strip())
            return {
                "passed": actual_len <= max_len,
                "detail": f"长度: {actual_len}/{max_len}",
                "score": 1.0 if actual_len <= max_len else max(0, 1 - (actual_len - max_len) / max_len),
            }
        elif check_type == "numeric":
            import re
            expected = test_def.get("expected_answer")
            tolerance = test_def.get("tolerance", 0.1)
            numbers = re.findall(r'[\d.]+', content)
            if not numbers:
                return {"passed": False, "detail": "未找到数字", "score": 0.0}
            closest = min(float(n) for n in numbers if n.replace('.', '').isdigit())
            diff = abs(closest - expected)
            return {
                "passed": diff <= tolerance,
                "detail": f"最近答案: {closest}, 期望: {expected}, 误差: {diff:.2f}",
                "score": max(0, 1 - diff / expected),
            }
        elif check_type == "code_run":
            # 提取代码块尝试运行
            import re
            code_match = re.search(r'```(?:python)?\s*(.*?)```', content, re.DOTALL)
            if not code_match:
                return {"passed": False, "detail": "未找到代码块", "score": 0.0}
            code = code_match.group(1)
            try:
                exec_globals = {}
                exec(code, exec_globals)
                # 检查是否定义了quicksort函数
                has_func = any('sort' in k.lower() for k in exec_globals.keys() if callable(exec_globals.get(k)))
                return {"passed": has_func, "detail": "代码可运行" if has_func else "代码运行但未找到排序函数", "score": 0.8 if has_func else 0.3}
            except Exception as e:
                return {"passed": False, "detail": f"运行错误: {str(e)[:80]}", "score": 0.0}
        elif check_type == "multi_turn":
            return {"passed": True, "detail": "多轮对话需人工评估连贯性", "score": None}

        return {"passed": None, "detail": "需人工评估", "score": None}

    def run_single(self, test_id, test_def):
        """运行单条测试。"""
        print(f"\n[{test_id}] {test_def['type']}")

        mon = VRAMMonitor(interval=0.5)
        import threading
        mon_thread = threading.Thread(target=mon.start, daemon=True)
        mon_thread.start()

        try:
            if test_def.get("turns"):
                # 多轮对话
                messages = []
                turn_results = []
                for i, turn in enumerate(test_def["turns"]):
                    messages.append({"role": "user", "content": turn})
                    resp = self._chat(messages)
                    messages.append({"role": "assistant", "content": resp["content"]})
                    turn_results.append({"turn": i + 1, "prompt": turn, **resp})
                    print(f"  轮次{i+1}: {resp['total_time_s']}s, {resp['tokens_per_s']} tok/s")
                content = turn_results[-1]["content"]
                total_time = sum(t["total_time_s"] for t in turn_results)
                tokens_per_s = sum(t["tokens_per_s"] for t in turn_results) / len(turn_results)
                response = {"content": content, "total_time_s": total_time, "tokens_per_s": round(tokens_per_s, 2), "turns": turn_results}
            else:
                messages = [{"role": "user", "content": test_def["prompt"]}]
                response = self._chat(messages)
                print(f"  完成: {response['total_time_s']}s, {response['tokens_per_s']} tok/s")

            check = self._auto_check(test_id, test_def, response)

        except Exception as e:
            response = {"content": "", "total_time_s": 0, "tokens_per_s": 0, "error": str(e)}
            check = {"passed": False, "detail": f"调用失败: {str(e)[:80]}", "score": 0.0}
            print(f"  失败: {e}")

        mon.stop()
        mon_thread.join(timeout=2)
        vram = mon.summary()

        result = {
            "test_id": test_id,
            "type": test_def["type"],
            "model": self.model,
            **response,
            "peak_vram_gb": vram.get("peak_gb", 0),
            "auto_check": check,
            "timestamp": datetime.now().isoformat(),
        }
        self.results.append(result)
        return result

    def run_batch(self, test_ids=None):
        """批量运行。"""
        if test_ids is None:
            test_ids = list(LLM_TESTS.keys())

        print(f"{'='*60}")
        print(f"Ollama 批量评估 | 模型: {self.model} | 共 {len(test_ids)} 题")
        print(f"{'='*60}")

        for tid in test_ids:
            if tid not in LLM_TESTS:
                print(f"跳过未知测试: {tid}")
                continue
            self.run_single(tid, LLM_TESTS[tid])

        # 保存结果
        summary_path = os.path.join(self.output_dir, f"llm_eval_{self.model.replace(':', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        # 汇总
        print(f"\n{'='*60}")
        print(f"评估完成 | 结果: {summary_path}")
        print(f"{'='*60}")
        auto_scored = [r for r in self.results if r.get("auto_check", {}).get("score") is not None]
        if auto_scored:
            avg_score = sum(r["auto_check"]["score"] for r in auto_scored) / len(auto_scored)
            passed = sum(1 for r in auto_scored if r["auto_check"]["passed"])
            avg_time = sum(r["total_time_s"] for r in self.results) / len(self.results)
            avg_tps = sum(r["tokens_per_s"] for r in self.results) / len(self.results)
            print(f"  自动评分: {passed}/{len(auto_scored)} 通过, 平均分 {avg_score:.2f}/1.0")
            print(f"  平均耗时: {avg_time:.1f}s")
            print(f"  平均速度: {avg_tps:.1f} tok/s")
        return self.results


def main():
    parser = argparse.ArgumentParser(description="Ollama LLM 批量评估")
    parser.add_argument("--model", required=True, help="Ollama 模型名，如 qwen3.5:9b")
    parser.add_argument("--server", default="http://127.0.0.1:11434", help="Ollama 地址")
    parser.add_argument("--output", "-o", default="./results", help="输出目录")
    parser.add_argument("--quick", action="store_true", help="快速模式，只跑3道核心题")
    parser.add_argument("--tests", help="指定测试ID，逗号分隔")
    args = parser.parse_args()

    if args.quick:
        test_ids = QUICK_TESTS
    elif args.tests:
        test_ids = [t.strip() for t in args.tests.split(",")]
    else:
        test_ids = None

    evaluator = OllamaEvaluator(server=args.server, model=args.model, output_dir=args.output)
    evaluator.run_batch(test_ids)


if __name__ == "__main__":
    main()
