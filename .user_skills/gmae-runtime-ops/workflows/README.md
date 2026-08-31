# ComfyUI 工作流集

> 适用于 16GB 显卡的 ComfyUI 工作流（API 格式），可直接用 `run_comfy.js` 运行。

## 工作流列表

| 文件 | 能力 | 模型 | 预计耗时 | 显存 |
|---|---|---|---|---|
| `sdxl-t2i.json` | 文生图 | SDXL 1.0 | ~60秒/张 | ~6.5GB |
| `flux-t2i.json` | 文生图（高质量） | Flux.1 dev Q5 GGUF | ~2分20秒/张 | ~13GB |
| `h3-t2v.json` | 文生视频（带音频） | MiniMax H3 INT8 | ~4分钟/片 | ~14GB |
| `h3-i2v.json` | 图生视频（带音频） | MiniMax H3 INT8 | ~4分钟/片 | ~14GB |
| `music3-t2audio.json` | 文生音乐 | MiniMax Music 3 | ~82秒/首(30s) | ~14.5GB |

## 使用方法

### 方式一：命令行运行（推荐）

```bash
# 前置：Node.js 16+，ComfyUI 运行在 localhost:8188
node ../scripts/run_comfy.js workflows/sdxl-t2i.json my_image
```

输出自动保存到 `../outputs/` 目录。

### 方式二：ComfyUI 界面导入

1. 打开 ComfyUI Web UI（http://localhost:8188）
2. 点击 **Load** 按钮，选择 JSON 文件
3. 修改提示词和参数
4. 点击 **Queue Prompt**

## 修改提示词

用文本编辑器打开 JSON，找到 `CLIPTextEncode` 节点的 `text` 字段：

```json
"2": {
  "class_type": "CLIPTextEncode",
  "inputs": {
    "text": "你的提示词写在这里",
    "clip": ["1", 1]
  }
}
```

## 关键参数说明

### SDXL 文生图
- `steps`: 25（质量/速度平衡）
- `cfg`: 6.0
- `sampler`: euler / normal
- `width/height`: 1024×1024

### Flux 文生图
- `steps`: 20
- `cfg`: 1.0（蒸馏模型必须用1，不是7）
- `sampler`: euler / simple
- 模型：Q5_K_S GGUF（16GB 卡最优，Q8 会爆）

### H3 视频
- `steps`: 4（配合 Turbo LoRA）
- `sampler`: euler / simple
- `width/height`: 640×640（768p 为开源权重上限）
- `length`: 73帧（~5秒 @24fps）
- **必须挂 Turbo LoRA**，否则速度慢一倍

### Music3 音乐
- `steps`: 50
- `cfg`: 1.0
- `seconds`: 30-60（60秒最稳，90s+ 可能断音）
- `max_duration` 必须与 `seconds` 一致

## 注意事项

1. **显存互斥**：跑 Flux/H3/Music3 时，先运行 `gpu_release.ps1` 释放显存
2. **模型路径**：确保模型文件名与工作流中一致，否则报 "not in [...]"
3. **首次预热**：H3 首次生成 8-9 分钟（JIT 编译），第2条起才是真实速度
4. **输出格式**：H3 输出 MP4（H.264+AAC），Music3 输出 WAV，SDXL/Flux 输出 PNG

## 缺失的工作流（待补充）

- [ ] SDXL 图生图（img2img）
- [ ] Flux 图生图（img2img）
- [ ] SDXL + ControlNet
- [ ] H3 视频延长
- [ ] Music3 歌词同步生成
