# GPU Maestro-显存指挥家 · 调度中心

> **新 Agent 必读：先读 `WATCHDOGS.md`（看门狗登记册），再操作本目录任何文件。禁止重复创建看门狗。**

> **项目**：GPU Maestro-显存指挥家（GMae）
> **子项目**：16G-AI-Studio（16GAS）— 16GB 单卡全模态 AI 工作站
> **核心引擎**：Prism Engine-棱镜引擎（P-Eng）
> **标语**：One GPU, Infinite Modalities

16GB 单卡的显存调度 Web UI。6 场景一键切换，Prism Engine 智能显存管理，防止打满死机。

## 功能

- 📊 实时显存监控（已用/总量/百分比/温度）
- 🎯 6 场景一键切换：对话 / SDXL出图 / H3出视频 / Flux出图 / 音乐 / 游戏
- 🔄 Ollama 模型组合切换（9B / 0.6B / 27B 量化版）
- 🛑 一键释放显存（卸载全部 Ollama 模型）
- 📖 显存账本速查（各服务占用+允许状态）
- 🛡️ 切换前自动显存预检（<4G 强制释放，符合显存管理最高指南 M1 铁律）
- 🐳 ollama 容器化适配（docker exec 调用）

## 快速开始

### Windows

```bash
# 前置：Python 3.8+（标准库即可，零依赖）
cd vram-console
start.bat
# 浏览器打开 http://localhost:8787
```

### Linux / macOS

```bash
cd vram-console
python3 server.py
# 浏览器打开 http://localhost:8787
```

## 配置

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `VRAM_CONSOLE_PORT` | `8787` | 服务端口 |
| `VRAM_CONSOLE_HOST` | `0.0.0.0` | 监听地址（默认所有接口，设 `127.0.0.1` 仅本机） |
| `VRAM_CONSOLE_TOKEN` | _(空)_ | API 认证 Token，设置后所有 POST 和 `/api/status` 需带 `X-API-Key` 请求头 |
| `GPU_RELEASE_PS1` | `../scripts/gpu_release.ps1` | 显存释放脚本路径 |
| `GAME_ON_PS1` | `../scripts/game-on.ps1` | 游戏模式脚本路径 |

> **安全提示**：默认监听 `0.0.0.0`（支持内网/Tailscale 访问），无认证。如需公网暴露，务必设置 `VRAM_CONSOLE_TOKEN`，否则任何人都可控制你的 AI 环境。

## 模型列表配置

> **当前**：编辑 `server.py` 中的 `BIG_MODELS` 列表
> **未来（P1）**：统一改为 `resources/registry.json` 配置驱动，加模型不改代码

```python
BIG_MODELS = ["qwen3.5:9b", "qwen3:0.6b", "qwen3.8:27b-rvn-q3km", "qwen3.8:27b-iq3xxs"]  # 按实际模型修改
```

## 场景说明

| 场景 | 动作 | 适用 |
|---|---|---|
| 对话态 | 加载 9B 模型，关闭出图服务 | 日常聊天/写作/RAG |
| SDXL出图 | 释放模型，启动 SDXL 生成 | 标准文生图 |
| H3出视频 | 释放模型，H3 独占全卡（ComfyUI） | 文生/图生视频+原生音频 |
| Flux出图 | 释放模型，Flux 独占全卡 | 高质量文生图 |
| 音乐态 | 释放模型，Music3 独占全卡（ComfyUI） | AI 写歌 |
| 游戏态 | 释放全部 AI，关文生图容器 | 玩游戏/串流 |

> **铁律**：切换场景前自动检测显存，若空闲 <4G 强制先释放（M1 铁律），防止打满死机。
> **依据**：《显存管理最高指南》v1.3 — 16GB 单卡错峰调度的唯一权威规则。

## 技术栈

- 后端：Python 标准库（http.server），零依赖
- 前端：单文件 HTML + 原生 JS，无构建
- 数据：实时从 `nvidia-smi` 和 Ollama API 获取

## 截图

*待补充*
