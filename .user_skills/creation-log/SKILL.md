---
name: creation-log
description: AI 创作日志记录。每次完成生图/音乐/视频生成后，记录环境信息（模型/参数/SageAttention/显存/版本）、生成时长和用户评判，追加到 JSONL 日志文件。触发场景：用户说"记录这次创作""记一下生成""创作日志""这次效果怎么样记一下"，或每次 ComfyUI/run_comfy.js 生成完成后主动询问是否记录。也用于查询历史创作记录、统计生成时长、对比 SageAttention 开启前后的性能差异。
---

---
name: creation-log
description: AI 创作日志记录。每次完成生图/音乐/视频生成后，记录环境信息（模型/参数/SageAttention/显存/版本）、生成时长和用户评判，追加到 JSONL 日志文件。用于性能对比、效果追踪、SageAttention 开启前后性能差异分析。
---

# 创作日志

记录每次 AI 生成（图/音乐/视频）的完整上下文，用于性能对比、效果追踪和经验积累。

## 日志文件位置

`D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\docs\creation-log.jsonl`

- 格式：JSONL（每行一条 JSON 记录）
- 不存在时自动创建
- 详细字段说明见 `references/log-schema.md`

## 记录流程

### 1. 生成完成后立即收集信息

生成任务结束时（run_comfy.js 输出 "RUN COMPLETED" 或用户告知生成完成），收集：

| 字段 | 来源 |
|------|------|
| `type` | image / music / video（根据工作流判断） |
| `model` | 工作流中使用的主模型名（如 SDXL、H3、Music3、Flux） |
| `workflow` | 工作流文件名（如 h3-t2v.json） |
| `prompt` | 用户输入的提示词 |
| `params` | 关键参数：分辨率、步数、seed、CFG 等（从工作流或用户处获取） |
| `duration_seconds` | run_comfy.js 输出的时长，或手动计时 |
| `output_file` | 生成文件的绝对路径 |

### 2. 自动采集环境信息

运行 `scripts/log_creation.py --env` 获取当前环境快照：
- ComfyUI 版本、PyTorch 版本
- SageAttention 是否启用（从启动日志或 comfyui_args.conf 判断）
- GPU 型号、显存使用量（nvidia-smi）
- 时间戳

### 3. 询问用户评判

生成完成后主动问用户：
- "这次效果打几分？（1-5）"
- "有什么评语或备注？"

如果用户不回答，`user_rating` 和 `user_comment` 留空，不阻塞记录。

### 4. 写入日志

运行 `scripts/log_creation.py --append` 传入收集到的信息，脚本自动追加到 JSONL 文件。

或手动构造 JSON 追加到文件末尾（确保每行一条完整 JSON）。

## 查询与统计

- 查看最近 N 条：`scripts/log_creation.py --recent 10`
- 按类型筛选：`scripts/log_creation.py --type video`
- 统计平均时长：`scripts/log_creation.py --stats`
- 对比 SageAttention 开启前后：`scripts/log_creation.py --compare sage`

## 注意事项

- 记录是追加操作，不会覆盖已有记录
- 提示词可能含敏感内容，日志文件不对外公开
- 生成时长以 run_comfy.js 输出为准；手动生成时用计时器记录
- 环境信息是生成时刻的快照，后续环境变化不影响已记录的数据
