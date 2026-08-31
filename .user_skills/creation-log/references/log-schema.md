# 创作日志字段说明

日志文件：`D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\docs\creation-log.jsonl`（JSONL，每行一条记录）

## 字段定义

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 自动 | 记录ID，格式 `YYYYMMDD-HHMMSS` |
| `timestamp` | string | 自动 | ISO 8601 时间戳 |
| `type` | string | 是 | 创作类型：`image` / `music` / `video` |
| `model` | string | 是 | 主模型名（如 `SDXL`、`H3`、`Music3`、`Flux`） |
| `workflow` | string | 否 | 工作流文件名（如 `h3-t2v.json`） |
| `prompt` | string | 否 | 用户提示词 |
| `params` | object | 否 | 关键参数（分辨率、步数、seed、CFG 等） |
| `duration_seconds` | number | 否 | 生成时长（秒） |
| `output_file` | string | 否 | 输出文件绝对路径 |
| `user_rating` | number | 否 | 用户评分 1-5 |
| `user_comment` | string | 否 | 用户评语 |
| `notes` | string | 否 | 其他备注 |
| `environment` | object | 自动 | 环境快照（见下） |

## environment 子字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `comfyui.comfyui_version` | string | ComfyUI 版本 |
| `comfyui.pytorch_version` | string | PyTorch 版本 |
| `gpu.gpu_model` | string | GPU 型号 |
| `gpu.vram_used_mb` | number | 生成时显存使用（MB） |
| `gpu.vram_total_mb` | number | 显存总量（MB） |
| `gpu.driver_version` | string | 显卡驱动版本 |
| `sage_attention` | boolean | SageAttention 是否启用 |
| `args` | string | ComfyUI 启动参数 |

## 示例记录

```json
{
  "id": "20260826-123045",
  "timestamp": "2026-08-26T12:30:45.123456",
  "type": "image",
  "model": "SDXL",
  "workflow": "sdxl-t2i.json",
  "prompt": "a cute cat sitting on a windowsill, sunlight, photorealistic",
  "params": {"width": 1024, "height": 1024, "steps": 20, "seed": 42},
  "duration_seconds": 60,
  "output_file": "D:\\...\\outputs\\sage_test_sdxl_t2i_00001_.png",
  "user_rating": 4,
  "user_comment": "画面不错，细节可以",
  "environment": {
    "comfyui": {"comfyui_version": "0.33.0", "pytorch_version": "2.13.0+cu130"},
    "gpu": {"gpu_model": "NVIDIA GeForce RTX 4060 Ti", "vram_used_mb": 8200, "vram_total_mb": 16384},
    "sage_attention": true
  }
}
```

## 使用脚本

```bash
# 采集环境快照
python scripts/log_creation.py --env

# 追加记录（JSON 字符串）
python scripts/log_creation.py --append '{"type":"image","model":"SDXL","duration_seconds":60}'

# 查看最近 10 条
python scripts/log_creation.py --recent 10

# 按类型筛选
python scripts/log_creation.py --type video

# 统计
python scripts/log_creation.py --stats

# SageAttention 对比
python scripts/log_creation.py --compare sage
```
