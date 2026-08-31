---
name: gmae-runtime-ops
description: GMae 运行时操作工具箱。显存释放/清理、游戏态切换、ComfyUI 工作流批量运行器，以及 16GB 显卡已验证的 ComfyUI 工作流集（SDXL/Flux/H3/Music3）。生成前必须先用本 Skill 释放显存到 <4GB，再用 run_comfy.js 运行工作流。适用于所有 AI 生成任务的前置准备和执行。
---

# GMae 运行时操作工具箱

> 显存释放 + ComfyUI 工作流运行 + 已验证工作流集，一站式覆盖 16GB 显卡的 AI 生成操作。

## 何时使用

- ✅ 生成任务前释放显存（SDXL/Flux/H3/Music3 等）
- ✅ 切换到游戏态，停止 AI 容器腾出资源
- ✅ 用命令行批量运行 ComfyUI 工作流（替代手动点界面）
- ✅ 查询已验证的工作流参数和模型配置
- ❌ 模型评测（用 model-benchmark-suite）
- ❌ 下载模型（用 aria2-multithread-download）

---

## 一、显存管理脚本

### 1.1 gpu_release.ps1 — 生成前释放显存（推荐）

不杀进程，只卸载 Ollama LLM 模型，确认显存降至阈值后放行。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\gpu_release.ps1
# 自定义阈值（默认 4096MB）
powershell -ExecutionPolicy Bypass -File scripts\gpu_release.ps1 -ThresholdMB 6000
```

- 从 `16gb-ai-studio\vram-console\resources\registry.json` 读取 LLM 模型列表
- 读取失败时用硬编码兜底列表
- 不杀 CPU 服务（rerank/embedding 等）

### 1.2 vram_cleanup.ps1 — 深度显存清理

比 gpu_release 更彻底，可选重启 ComfyUI 释放模型缓存。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\vram_cleanup.ps1
# 强制重启 ComfyUI 释放模型缓存
powershell -ExecutionPolicy Bypass -File scripts\vram_cleanup.ps1 -RestartComfyUI
# 自定义阈值
powershell -ExecutionPolicy Bypass -File scripts\vram_cleanup.ps1 -ThresholdMB 6000 -RestartComfyUI
```

### 1.3 game-on.ps1 — 切换到游戏态

停止 AI 生成容器 + 卸载 Ollama 模型，为游戏腾出 GPU 资源。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\game-on.ps1
# 自定义阈值（默认 2048MB）
powershell -ExecutionPolicy Bypass -File scripts\game-on.ps1 -ThresholdMB 3072
```

- 停止 comfyui / fooocus 容器
- 卸载全部 Ollama LLM 模型
- 确认显存降至游戏可用水平

### 1.4 gpu_release.sh — Linux/macOS 版本

```bash
chmod +x scripts/gpu_release.sh
./scripts/gpu_release.sh 6000  # 阈值可选，默认 4096
```

---

## 二、ComfyUI 工作流运行器

### run_comfy.js — 通用工作流运行器

提交工作流 → 轮询状态 → 拉取全部输出（图片/视频/音频），自动计时。

```bash
# 基本用法
node scripts\run_comfy.js <workflow.json> <output_prefix> [timeout_minutes]

# 示例：跑 SDXL 文生图
node scripts\run_comfy.js workflows\sdxl-t2i.json my_image

# 示例：跑 H3 文生视频，自定义超时 60 分钟
node scripts\run_comfy.js workflows\h3-t2v.json my_video 60
```

**环境变量：**

| 变量 | 默认 | 说明 |
|------|------|------|
| `COMFY_HOST` | `localhost` | ComfyUI 地址 |
| `COMFY_PORT` | `8188` | ComfyUI 端口 |
| `OUTPUT_DIR` | `../outputs` | 输出目录 |
| `RUN_TIMEOUT` | `30` | 超时时间（分钟） |

**前置：** Node.js 16+，ComfyUI 运行中。

---

## 三、已验证工作流集

> 所有工作流均在 RTX 4060 Ti 16GB 上实测通过，可直接用 run_comfy.js 运行。

| 文件 | 能力 | 模型 | 预计耗时 | 峰值显存 |
|------|------|------|---------|---------|
| `sdxl-t2i.json` | 文生图 | SDXL 1.0 | ~60秒/张 | ~6.5GB |
| `flux-t2i.json` | 文生图（高质量） | Flux.1 dev Q5 GGUF | ~2分20秒/张 | ~13GB |
| `h3-t2v.json` | 文生视频（带音频） | MiniMax H3 INT8 | ~4分钟/片 | ~14GB |
| `h3-i2v.json` | 图生视频（带音频） | MiniMax H3 INT8 | ~4分钟/片 | ~14GB |
| `music3-t2audio.json` | 文生音乐 | MiniMax Music 3 | ~82秒/首(30s) | ~14.5GB |

### 关键参数速查

**SDXL 文生图：** steps=25, cfg=6.0, sampler=euler, 1024×1024

**Flux 文生图：** steps=20, cfg=1.0（蒸馏模型必须用1）, sampler=euler/simple, 模型用 Q5_K_S GGUF（Q8 会爆显存）

**H3 视频：** steps=4（配合 Turbo LoRA）, sampler=euler/simple, 640×640, 73帧(~5秒@24fps), 必须挂 Turbo LoRA

**Music3 音乐：** steps=50, cfg=1.0, seconds=30-60（60秒最稳）, max_duration 必须与 seconds 一致

### 修改提示词

用文本编辑器打开 JSON，找到 `CLIPTextEncode` 节点的 `text` 字段修改。

---

## 四、标准生成流程

```
1. 释放显存 → scripts\gpu_release.ps1
2. 确认显存 <4GB → 脚本输出 "GPU ready"
3. 运行工作流 → node scripts\run_comfy.js workflows\xxx.json prefix
4. 查看输出 → outputs\ 目录
5. 记录日志 → creation-log Skill（可选）
```

**显存互斥规则：** 跑 Flux/H3/Music3 时，必须先释放显存，且不能与其他 GPU 服务并发。

**首次预热：** H3 首次生成 8-9 分钟（JIT 编译），第 2 条起才是真实速度。

---

## 五、其他工具

### md_to_pdf.py — Markdown 转 PDF

```bash
python scripts\md_to_pdf.py <input.md> <output.pdf>
```

---

## 文件结构

```
gmae-runtime-ops/
├── SKILL.md                          # 本文件
├── scripts/
│   ├── gpu_release.ps1               # 生成前释放显存（Windows）
│   ├── gpu_release.sh                # 生成前释放显存（Linux/macOS）
│   ├── vram_cleanup.ps1              # 深度显存清理（可选重启ComfyUI）
│   ├── game-on.ps1                   # 切换到游戏态
│   ├── run_comfy.js                  # ComfyUI 工作流运行器
│   └── md_to_pdf.py                  # Markdown 转 PDF
└── workflows/
    ├── sdxl-t2i.json                 # SDXL 文生图
    ├── flux-t2i.json                 # Flux 文生图（Q5 GGUF）
    ├── h3-t2v.json                   # H3 文生视频（带音频）
    ├── h3-i2v.json                   # H3 图生视频（带音频）
    ├── music3-t2audio.json           # Music3 文生音乐
    ├── music3_t2audio_test.json      # Music3 测试工作流
    └── README.md                      # 工作流详细说明
```

---

## 注意事项

1. **显存安全第一**：16GB 卡生成前必须释放到 <4GB，禁止显存打满（会死机）
2. **脚本自动定位工作区**：PS1 脚本自动向上查找包含 AGENTS.md 的目录作为工作区根，无需手动配置路径
3. **ComfyUI 容器管理**：禁止 `docker compose up -d comfyui`（会清空改动），改容器用 `docker exec`/`docker cp`，完成后 `docker commit`
4. **输出格式**：H3 输出 MP4（H.264+AAC），Music3 输出 WAV，SDXL/Flux 输出 PNG
5. **模型路径**：确保模型文件名与工作流中一致，否则报 "not in [...]" 错误

---

*创建：2026-08-31 | 来源：整合自工作区 scripts/ 和 workflows/ | 版本：v1.0*
