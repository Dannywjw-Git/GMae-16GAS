# GPU Maestro - 显存指挥家 (GMae)

> **让 16GB 消费级显卡跑通全模态本地 AI 生成** — 文生图、图生图、文生视频、图生视频、AI 写歌、本地对话。不排队、不花钱、数据不出本地。

**核心引擎**: Prism Engine - 棱镜引擎 (P-Eng) — 一块 GPU 如棱镜般分出多种模态能力
**首个子项目**: 16G-AI-Studio (16GAS) — 参赛 2026 上海开源软件应用创新大赛 · 智算云赛道
**标语**: One GPU, Infinite Modalities

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ComfyUI](https://img.shields.io/badge/ComfyUI-0.33.0+-blue)](https://docs.comfy.org/)
[![GPU](https://img.shields.io/badge/GPU-16GB-green)]()
[![Docker](https://img.shields.io/badge/Docker-Required-blue)]()

---

## ✨ 核心特性

| 能力 | 模型 | 16GB 实测 |
|---|---|---|
| 🎨 文生图（标准） | SDXL 1.0 | ~60秒/张（1024×1024） |
| 🎨 文生图（高质量） | Flux.1 dev Q5 GGUF | ~2分30秒/张 |
| 🎬 文生视频 | Wan 2.2 TI2V-5B | 部署中（替代 H3） |
| 🎵 AI 写歌 | MiniMax Music 3 | ~82秒/首（30秒） |
| 💬 本地对话 | qwen3.5:9b | ~40 tok/s |
| 🎛️ 显存调度中心 | 自研 | 6场景一键切换，防死机 |

> ⚠️ MiniMax H3 因模型+文本编码器共 ~52GB，16GB 加载峰值 OOM，已标记不可行，改用 Wan 2.2。
> 所有生成本地完成，无需 API Key，无需联网（首次下载模型除外）。

---

## 🖼️ 效果展示

### 调度中心界面
![调度中心](console.png)
*显存监控 + 场景切换 + 服务状态，单页管理全部 AI 服务*

### Flux 高质量文生图
![Flux Sample](docs/assets/flux_sample.png)
*Fooocus + Flux.1 dev Q5 GGUF，16GB 卡 2分30秒/张*

### SDXL 文生图
![SDXL Sample](docs/assets/sdxl_sample.png)
*标准质量，~60秒/张*

### 文生视频 / AI 写歌
*视频素材待 Wan 2.2 模型部署后补充；Music3 音乐见 `outputs/`*

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────┐
│              GPU Maestro 调度中心                │
│         (显存管理 · 场景切换 · 服务编排)          │
├──────────┬──────────┬──────────┬────────────────┤
│  OWUI    │ ComfyUI  │ Ollama   │  Immich       │
│ (对话入口)│(图/视频/音乐)│(本地LLM) │  (图片管理)    │
└──────────┴──────────┴──────────┴────────────────┘
         │           │           │
         └───────────┴───────────┘
                     │
              ┌──────▼──────┐
              │  Prism Engine │
              │  (显存调度核心) │
              └─────────────┘
```

### 六大场景
| 场景 | 显存预算 | 说明 |
|------|---------|------|
| 💬 对话态 | ~7.6-9.7G | Ollama LLM + OWUI |
| 🎨 ComfyUI | 6.5-14.5G | SDXL / Flux / H3 / Music3 |
| 🖼️ Fooocus | ~6.9G | 零门槛画图，用毕必停 |
| 🎮 游戏态 | 2-4G | 释放全部 AI 显存 |

### 显存调度铁律
- **M1**: 生成前必须释放显存到 <4GB，防止打满死机
- **M2**: 27B 模型独占，切换前必须停止 9B/0.6B
- **M3**: ComfyUI 三合一账本：SDXL ~9.6G / Flux 13G / Music 14.5G

---

## 🚀 快速开始

### 前置要求
- NVIDIA GPU ≥ 16GB 显存（推荐 RTX 4060 Ti 16G）
- Docker Desktop（Windows）或 Docker Engine（Linux）
- 至少 50GB 磁盘空间（模型文件）

### 安装步骤
1. 克隆仓库
2. 拉取 Docker 镜像
3. 下载模型文件到对应目录
4. 启动调度中心
5. 访问 http://localhost:8787

*详细部署文档见 `docs/deployment-replication-checklist.md`*

---

## 📁 项目结构

```
16gb-ai-studio/
├── vram-console/          # GPU Maestro 调度中心（核心）
│   ├── server.py          # 后端服务（Python 标准库，零依赖）
│   ├── watchdog.py        # 看门狗自动重启
│   ├── index.html         # 前端页面
│   ├── resources/
│   │   └── registry.json  # 资源注册表（配置驱动，P1）
│   ├── start.bat / stop.bat / status.bat
│   └── WATCHDOGS.md       # 看门狗统一登记册
├── workflows/             # ComfyUI 工作流（可直接导入）
│   ├── sdxl-t2i.json
│   ├── flux-t2i.json
│   ├── h3-t2v.json / h3-i2v.json
│   └── music3-t2audio.json
├── scripts/               # 全局工具脚本
│   ├── gpu_release.ps1/sh # 生成前显存释放
│   ├── vram_cleanup.ps1   # 通用显存清理
│   ├── game-on.ps1        # 游戏态切换（释放全部AI显存）
│   └── run_comfy.js       # ComfyUI 启动辅助
├── docs/                  # 文档
│   ├── 调度中心架构与交互设计.md  # 16GAS 设计框架
│   ├── 项目进度跟踪.md
│   ├── 开发日志.md
│   ├── 显存管理指南.md
│   ├── 作品介绍.md / .pdf  # 参赛材料
│   └── assets/            # 效果展示素材
├── docker/compose-examples/  # Docker 部署示例
├── AGENTS.md              # 项目记忆与操作指南
├── CONTRIBUTING.md        # 贡献指南
├── CHANGELOG.md           # 变更日志
└── LICENSE                # MIT
```

---

## 🏆 开源大赛

**2026 上海开源软件应用创新大赛 · 智算云赛道**

- 参赛项目：16G-AI-Studio（GPU Maestro 首个落地子项目）
- 赛道定位：异构算力调度与 GPU 池化 / 推理加速
- 技术创新点：
  1. 消费级 16GB 单卡跑通 6 模态全栈生成
  2. 配置驱动的资源注册表（registry.json），消除硬编码
  3. 智能显存调度引擎，防止 OOM 死机
  4. 看门狗自动恢复，服务高可用

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

### 模型许可证说明
- SDXL 1.0: CreativeML Open RAIL++-M
- Flux.1 dev: 非商用许可（FLUX.1-dev Non-Commercial License）
- MiniMax H3 / Music3: 详见 MiniMax 官方许可
- Qwen 系列: Apache 2.0 / Qwen 许可

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

*One GPU, Infinite Modalities — GPU Maestro*
