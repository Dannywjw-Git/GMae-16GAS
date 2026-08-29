# 工具脚本

## gpu_release.ps1 / gpu_release.sh

生成任务前释放显存。卸载全部 Ollama 模型，确认显存降至阈值后放行。

**Windows：**
```powershell
powershell -ExecutionPolicy Bypass -File gpu_release.ps1
# 自定义阈值
.\gpu_release.ps1 -ThresholdMB 6000
```

**Linux/macOS：**
```bash
chmod +x gpu_release.sh
./gpu_release.sh 6000  # 阈值可选，默认4096
```

**配置：** 编辑脚本中的 `$bigModels` / `BIG_MODELS` 列表，改为你实际安装的 Ollama 模型。

---

## game-on.ps1

切换到游戏态：停止 AI 生成容器（comfyui/fooocus）+ 卸载 Ollama 模型 + 显存确认。

```powershell
powershell -ExecutionPolicy Bypass -File game-on.ps1
# 自定义阈值（默认 2048MB）
.\game-on.ps1 -ThresholdMB 3072
```

---

## run_comfy.js

通用 ComfyUI 工作流运行器：提交 → 轮询 → 拉取全部输出（图片/视频/音频）。

**用法：**
```bash
node run_comfy.js <workflow.json> <output_prefix> [timeout_minutes]
```

**示例：**
```bash
node run_comfy.js ../workflows/h3-t2v.json my_video
# 输出保存到 ../outputs/my_video_*.mp4
# 自定义超时（默认 30 分钟）
node run_comfy.js ../workflows/h3-t2v.json my_video 60
```

**环境变量：**

| 变量 | 默认 | 说明 |
|---|---|---|
| `COMFY_HOST` | `localhost` | ComfyUI 地址 |
| `COMFY_PORT` | `8188` | ComfyUI 端口 |
| `OUTPUT_DIR` | `../outputs` | 输出目录 |
| `RUN_TIMEOUT` | `30` | 超时时间（分钟） |

**前置：** Node.js 16+，ComfyUI 运行中。
