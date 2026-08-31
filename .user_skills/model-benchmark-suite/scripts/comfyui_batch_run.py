#!/usr/bin/env python3
"""
ComfyUI Batch Runner — 批量生成评估素材
用法:
  # 用SDXL跑全部8条标准Prompt
  python comfyui_batch_run.py --model sdxl --output ./results/sdxl_test

  # 用Flux跑指定Prompt
  python comfyui_batch_run.py --model flux --prompts IMG-01,IMG-02,IMG-05 --output ./results/flux_test

  # 自定义参数
  python comfyui_batch_run.py --model sdxl --steps 30 --cfg 7 --width 1024 --height 1024 --seed 42
"""

import argparse
import json
import time
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime

# 将脚本目录加入path，以便导入vram_monitor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vram_monitor import VRAMMonitor

# ============================================================
# 标准测试 Prompt 集（图像生成）
# ============================================================
STANDARD_PROMPTS = {
    "IMG-01": {"type": "写实人像", "prompt": "A 25-year-old woman with curly brown hair, wearing a vintage leather jacket, standing in a rainy Tokyo street at night, neon lights reflecting on wet pavement, cinematic lighting, 8k"},
    "IMG-02": {"type": "英文文字渲染", "prompt": "A minimalist poster with bold text 'GMae 2026' in the center, black background, gold geometric shapes, modern design"},
    "IMG-02C": {"type": "中文文字渲染", "prompt": "一张极简海报，中央有醒目的中文文字'显存指挥家'，黑色背景，金色几何图形，现代设计风格"},
    "IMG-03": {"type": "多物体计数", "prompt": "Five red apples and three green bananas arranged on a wooden table, natural window light, photorealistic"},
    "IMG-04": {"type": "颜色/位置", "prompt": "A blue cat sitting on top of a red car, yellow sun in background, green grass, simple illustration style"},
    "IMG-05": {"type": "科幻场景", "prompt": "A futuristic city with flying cars, massive glass skyscrapers, sunset orange sky, cyberpunk style, highly detailed"},
    "IMG-06": {"type": "艺术风格", "prompt": "Starry Night style painting of a modern city skyline, thick brushstrokes, swirling clouds, vibrant colors"},
    "IMG-07": {"type": "产品图", "prompt": "A matte black wireless headphones on a white pedestal, soft studio lighting, product photography, sharp focus"},
    "IMG-08": {"type": "复杂场景", "prompt": "A medieval marketplace with merchants selling fruits, a knight in armor walking by, a castle in the distance, busy crowd, warm afternoon light, oil painting style"},
}

NEGATIVE_PROMPT = "blurry, low quality, distorted, deformed, ugly, watermark, text, signature"


class ComfyUIRunner:
    """ComfyUI 批量运行器。"""

    def __init__(self, server="http://127.0.0.1:8188", output_dir="./results"):
        self.server = server.rstrip("/")
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.results = []

    def _api_get(self, path):
        with urllib.request.urlopen(f"{self.server}{path}", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _api_post(self, path, data):
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            f"{self.server}{path}",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _build_workflow(self, model, prompt, width, height, steps, cfg, seed):
        """构建工作流 JSON。"""
        if model == "sdxl":
            return self._sdxl_workflow(prompt, width, height, steps, cfg, seed)
        elif model == "flux":
            return self._flux_workflow(prompt, width, height, steps, cfg, seed)
        else:
            raise ValueError(f"不支持的模型: {model}")

    def _sdxl_workflow(self, prompt, width, height, steps, cfg, seed):
        """SDXL 标准工作流。"""
        return {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE_PROMPT, "clip": ["1", 1]}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "5": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler",
                "scheduler": "normal", "denoise": 1.0,
                "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]
            }},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "bench_sdxl", "images": ["6", 0]}},
        }

    def _flux_workflow(self, prompt, width, height, steps, cfg, seed):
        """Flux GGUF 工作流。"""
        return {
            "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux1-dev-Q5_K_S.gguf"}},
            "2": {"class_type": "DualCLIPLoader", "inputs": {
                "clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn.safetensors", "type": "flux"
            }},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
            "6": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "7": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler",
                "scheduler": "simple", "denoise": 1.0,
                "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0]
            }},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "bench_flux", "images": ["8", 0]}},
        }

    def _wait_for_prompt(self, prompt_id, timeout=600):
        """等待 prompt 完成，返回输出文件名列表。"""
        start = time.time()
        while time.time() - start < timeout:
            try:
                history = self._api_get(f"/history/{prompt_id}")
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    images = []
                    for node_id, out in outputs.items():
                        if "images" in out:
                            for img in out["images"]:
                                images.append(img["filename"])
                    return images
            except Exception:
                pass
            time.sleep(2)
        return None

    def _download_image(self, filename, subfolder="", folder_type="output"):
        """从 ComfyUI 下载生成的图片。"""
        params = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
        url = f"{self.server}/view?{params}"
        local_path = os.path.join(self.output_dir, filename)
        try:
            urllib.request.urlretrieve(url, local_path)
            return local_path
        except Exception as e:
            print(f"  下载失败: {e}")
            return None

    def run_single(self, prompt_id, prompt_text, model, width, height, steps, cfg, seed):
        """运行单条 Prompt。"""
        print(f"\n[{prompt_id}] 开始生成...")
        print(f"  模型: {model} | 分辨率: {width}x{height} | 步数: {steps} | CFG: {cfg} | 种子: {seed}")

        workflow = self._build_workflow(model, prompt_text, width, height, steps, cfg, seed)

        # 启动显存监控
        mon = VRAMMonitor(interval=0.5)
        import threading
        mon_thread = threading.Thread(target=mon.start, daemon=True)
        mon_thread.start()

        gen_start = time.time()
        try:
            resp = self._api_post("/prompt", {"prompt": workflow})
            pid = resp.get("prompt_id")
            if not pid:
                raise Exception(f"提交失败: {resp}")

            images = self._wait_for_prompt(pid)
            gen_time = round(time.time() - gen_start, 1)

            mon.stop()
            mon_thread.join(timeout=2)
            vram = mon.summary()

            if images:
                local_files = []
                for img_file in images:
                    local = self._download_image(img_file)
                    if local:
                        local_files.append(local)
                status = "success"
                print(f"  完成! 耗时: {gen_time}s | 峰值显存: {vram['peak_gb']}GB | 输出: {local_files}")
            else:
                status = "timeout"
                local_files = []
                print(f"  超时! 耗时: {gen_time}s")

        except Exception as e:
            gen_time = round(time.time() - gen_start, 1)
            mon.stop()
            mon_thread.join(timeout=2)
            vram = mon.summary()
            status = f"error: {str(e)[:100]}"
            local_files = []
            print(f"  失败! {status}")

        result = {
            "prompt_id": prompt_id,
            "prompt": prompt_text,
            "model": model,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg": cfg,
            "seed": seed,
            "gen_time_s": gen_time,
            "peak_vram_gb": vram.get("peak_gb", 0),
            "avg_vram_gb": vram.get("avg_gb", 0),
            "status": status,
            "output_files": local_files,
            "timestamp": datetime.now().isoformat(),
        }
        self.results.append(result)
        return result

    def run_batch(self, model, prompt_ids=None, width=1024, height=1024, steps=25, cfg=7.0, seed=42):
        """批量运行。"""
        if prompt_ids:
            ids = [p.strip() for p in prompt_ids.split(",")]
        else:
            ids = list(STANDARD_PROMPTS.keys())

        # Flux 默认参数调整
        if model == "flux":
            cfg = cfg if cfg != 7.0 else 3.5
            steps = steps if steps != 25 else 25

        print(f"{'='*60}")
        print(f"ComfyUI 批量评估 | 模型: {model} | 共 {len(ids)} 条 Prompt")
        print(f"{'='*60}")

        for pid in ids:
            if pid not in STANDARD_PROMPTS:
                print(f"跳过未知 Prompt ID: {pid}")
                continue
            self.run_single(
                prompt_id=pid,
                prompt_text=STANDARD_PROMPTS[pid]["prompt"],
                model=model,
                width=width, height=height, steps=steps, cfg=cfg, seed=seed
            )

        # 保存汇总
        summary_path = os.path.join(self.output_dir, f"batch_result_{model}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        # 打印汇总
        print(f"\n{'='*60}")
        print(f"批量评估完成 | 结果已保存: {summary_path}")
        print(f"{'='*60}")
        success = [r for r in self.results if r["status"] == "success"]
        if success:
            avg_time = sum(r["gen_time_s"] for r in success) / len(success)
            max_vram = max(r["peak_vram_gb"] for r in success)
            print(f"  成功: {len(success)}/{len(self.results)}")
            print(f"  平均耗时: {avg_time:.1f}s")
            print(f"  峰值显存: {max_vram:.2f}GB")
        return self.results


def main():
    parser = argparse.ArgumentParser(description="ComfyUI 批量生成评估")
    parser.add_argument("--model", required=True, choices=["sdxl", "flux"], help="模型类型")
    parser.add_argument("--server", default="http://127.0.0.1:8188", help="ComfyUI 地址")
    parser.add_argument("--output", "-o", default="./results", help="输出目录")
    parser.add_argument("--prompts", help="指定Prompt ID，逗号分隔（如 IMG-01,IMG-05），默认全部")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    runner = ComfyUIRunner(server=args.server, output_dir=args.output)
    runner.run_batch(
        model=args.model,
        prompt_ids=args.prompts,
        width=args.width, height=args.height,
        steps=args.steps, cfg=args.cfg, seed=args.seed
    )


if __name__ == "__main__":
    main()
