# GPU Maestro - 显存指挥家 (GMae)

> **让 16GB 消费级显卡跑通全模态本地 AI 生成** — 文生图、图生图、文生视频、图生视频、AI 写歌、本地对话。不排队、不花钱、数据不出本地。

**核心引擎**: Prism Engine - 棱镜引擎 (P-Eng) — 一块 GPU 如棱镜般分出多种模态能力
**首个子项目**: 16G-AI-Studio (16GAS) — 参赛 2026 上海开源软件应用创新大赛 · 智算云赛道
**标语**: One GPU, Infinite Models

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
| 🎬 文生视频 | Wan 2.2 TI2V-5B | 已跑通（480x480x17帧） |
| 🎵 AI 写歌 | MiniMax Music 3 | ~82秒/首（30秒） |
| 💬 本地对话 | qwen3.5:9b | ~40 tok/s |
| 🎛️ 显存调度中心 | 自研 | 6场景一键切换，防死机 |
| 🔍 可观测性引擎 | 自研 | 事件关联 + 故障场景库 + 告警降噪 |
| 🩺 根因诊断 | 自研 | 5秒检测 + 根因Top3 + 事件时间线 |
| 🗺️ 拓扑图 + 健康度 | 自研 | GPU→容器→模型→任务四层拓扑 + 4维度健康评分 |
| 🖥️ 全新 WEBUI | 自研 | 8页面 + 组件化设计 + 信息架构清晰 |

> ⚠️ MiniMax H3 因模型+文本编码器共 ~52GB，16GB 加载峰值 OOM，已标记不可行，改用 Wan 2.2。
> 所有生成本地完成，无需 API Key，无需联网（首次下载模型除外）。

### 🆕 可观测性与诊断能力（S2/S3 新增）

| 能力 | 说明 |
|------|------|
| **事件关联引擎** | 统一事件格式 + 时间线 API + 根因推断规则引擎（5+4规则） |
| **故障场景库** | 5种典型故障场景 + 可执行处置步骤 + 注入脚本 |
| **告警降噪** | 告警聚合 + 静默 + 升级，避免告警风暴 |
| **根因诊断** | 告警触发时自动回溯5分钟事件流，输出根因候选 Top3 + 置信度 |
| **一键处置** | 诊断后提供可执行处置建议（释放显存/切换场景/卸载模型） |

### 🆕 拓扑图与健康度（S5 新增）

| 能力 | 说明 |
|------|------|
| **四层拓扑** | GPU → 容器 → 模型 → 任务，SVG 可视化，节点可点击查看详情 |
| **健康度评分** | 4维度加权评分（显存/容器/模型/服务），实时更新 |
| **进程级显存** | 穿透 Windows → WSL2 → Docker → 容器 → 模型，看到每一层显存占用 |

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
┌─────────────────────────────────────────────────────────────┐
│                    GMae WEBUI (前端)                         │
│  Dashboard · 显存账本 · 模型管理 · 诊断中心 · 告警中心 · 拓扑图  │
├─────────────────────────────────────────────────────────────┤
│                 API 层 (api/endpoints/)                      │
│        12模块 · 45端点 · 统一响应格式 · Token认证             │
├─────────────────────────────────────────────────────────────┤
│              中间层引擎 (engine/ + services/)                │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐  │
│  │ 显存预算  │ 事件总线  │ 根因诊断  │ 告警管理  │ 健康评分  │  │
│  │ 准入控制  │ 时间线    │ 规则引擎  │ 聚合降噪  │ 拓扑构建  │  │
│  └──────────┴──────────┴──────────┴──────────┴──────────┘  │
├─────────────────────────────────────────────────────────────┤
│              核心层 (core/ + clients/)                       │
│  配置管理 · 状态缓存 · 硬件探测 · 日志 · 统一Client封装        │
├─────────────────────────────────────────────────────────────┤
│              外部服务 (Docker · Ollama · ComfyUI · Helper)   │
└─────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 后端 | Python 3.10+ 标准库 | 零外部依赖，仅用标准库 |
| 前端 | 原生 HTML/CSS/JS | 无框架，组件化设计，11个JS模块 |
| 数据 | JSON 文件 | 配置驱动，无数据库依赖 |
| 部署 | Docker Desktop + WSL2 | Windows/Linux 兼容 |

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
├── vram-console/              # GMae 调度中心（核心）
│   ├── server.py              # 后端服务入口（Python 标准库，零依赖）
│   ├── config.json            # 配置文件（端口/Token/服务清单）
│   ├── start.bat / stop.bat / status.bat  # 服务管理脚本
│   ├── WATCHDOGS.md           # 看门狗统一登记册
│   ├── api/                   # API 层（12模块 · 45端点）
│   │   ├── endpoints/         # 端点模块（status/vram/models/diagnose/alerts/topology等）
│   │   ├── router.py          # 路由分发
│   │   ├── middleware.py      # 中间件（认证/日志/CORS）
│   │   └── status_cache.py    # 状态缓存（TTL 10秒，热路径<500ms）
│   ├── core/                  # 核心层
│   │   ├── config.py          # 配置管理
│   │   ├── registry.py        # 通用状态存储
│   │   ├── event_bus.py       # 事件总线（标准化 + 时间线）
│   │   ├── hardware_probe.py  # 硬件探测
│   │   ├── logger.py          # 结构化日志
│   │   └── status_cache.py    # API响应缓存
│   ├── engine/                # 中间层引擎
│   │   ├── budget.py          # 显存预算
│   │   ├── admission_gate.py  # 准入控制
│   │   ├── diagnose.py        # 根因诊断（规则引擎，5+4规则）
│   │   ├── alert_manager.py   # 告警管理（聚合/静默/升级）
│   │   ├── health_score.py    # 健康度评分（4维度加权）
│   │   ├── topology.py        # 拓扑图构建（四层GPU→容器→模型→任务）
│   │   ├── scanner.py         # 资源扫描
│   │   ├── qos.py             # 服务质量
│   │   └── watchdog.py        # 看门狗
│   ├── services/              # 业务服务层
│   │   ├── docker.py          # Docker 容器管理
│   │   ├── ollama.py          # Ollama 模型管理
│   │   ├── comfyui.py         # ComfyUI 工作流
│   │   ├── helper.py          # Helper 客户端（进程管理+API调用）
│   │   ├── vram_helper.py     # Helper 服务端（独立脚本，UAC提权）
│   │   ├── scene.py           # 场景管理
│   │   └── status.py          # 状态聚合
│   ├── clients/               # 统一客户端封装
│   │   ├── process_client.py  # 子进程调用统一封装
│   │   ├── helper_client.py   # Helper HTTP API 客户端
│   │   ├── health_client.py   # 健康探测客户端
│   │   ├── docker_client.py   # Docker 客户端
│   │   ├── ollama_client.py   # Ollama 客户端
│   │   ├── comfyui_client.py  # ComfyUI 客户端
│   │   └── nvidia_smi.py      # nvidia-smi 封装
│   ├── observability/         # 可观测性
│   │   └── health_probe.py    # 服务健康探测
│   ├── scripts/               # 工具脚本
│   │   └── fault_inject.py    # 故障注入脚本（4种场景+安全保护）
│   ├── web/                   # 前端（全新 WEBUI，S4 重做）
│   │   ├── index.html         # 入口HTML
│   │   ├── css/               # 样式（拆分为5个文件）
│   │   │   ├── variables.css  # CSS变量
│   │   │   ├── base.css       # 基础样式
│   │   │   ├── layout.css     # 布局
│   │   │   ├── components.css # 通用组件
│   │   │   └── pages/         # 页面样式
│   │   └── js/                # 脚本（拆分为11个文件）
│   │       ├── app.js         # 入口（175行）
│   │       ├── core/          # 核心模块（utils/eventbus/state/api/router）
│   │       ├── components/    # 组件（icons/toast/modal）
│   │       └── pages/         # 页面渲染
│   └── tests/                 # 测试
├── workflows/                 # ComfyUI 工作流
├── docs/                      # 文档
│   ├── 调度中心架构与交互设计.md    # 16GAS 设计蓝图（权威）
│   ├── 16GAS系统重构计划_v1.0.md   # 重构计划（S0-S6）
│   ├── 代码质量整改计划_v2.0.md     # 代码质量整改（P0-P3）
│   ├── 大赛演示脚本_v1.0.md         # 演示脚本（5分钟完整版）
│   ├── 前端代码规范_v1.0.md         # 前端代码规范
│   └── assets/                  # 效果展示素材
├── AGENTS.md                  # 项目记忆与操作指南
├── CONTRIBUTING.md            # 贡献指南
├── CHANGELOG.md               # 变更日志
└── LICENSE                    # MIT
```

---

## 🏆 开源大赛

**2026 上海开源软件应用创新大赛 · 智算云赛道**

- 参赛项目：16G-AI-Studio（GPU Maestro 首个落地子项目）
- 赛道定位：异构算力调度与 GPU 池化 / 推理加速
- 技术创新点：
  1. **消费级 16GB 单卡跑通 6 模态全栈生成** — 文生图/文生视频/AI写歌/本地对话
  2. **四层全链路显存可观测** — 穿透 Windows→WSL2→Docker→容器→模型，看到每一层显存占用
  3. **可解释的根因诊断引擎** — 基于规则的推断（非AI黑盒），告警触发时自动回溯5分钟事件流，输出根因Top3+置信度
  4. **故障注入→告警→根因→处置完整闭环** — 5种故障场景库 + 可执行处置步骤 + 一键释放
  5. **配置驱动的资源注册表** — 消除硬编码，动态服务清单
  6. **智能显存调度引擎** — 6场景一键切换，防止 OOM 死机
  7. **看门狗自动恢复** — 服务崩溃自动重启，高可用
  8. **零外部依赖** — 后端纯 Python 标准库，前端原生 HTML/CSS/JS，无框架

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

*One GPU, Infinite Models — GPU Maestro*
