# GPU Maestro - 显存指挥家（GMae）

> **一卡，全模态（1 GPU，∞ AI）** — 消费级显卡的显存编排专家。
> 让一块 16GB（乃至 8G~48G）消费级显卡上的对话、文生图、文生视频、文生音乐等所有 AI 模型，被一个编排层管理得井井有条——**不打架、不死机、不手动**。

GPU Maestro **不是又一个 AI 生成工具**，而是管"AI 生成工具怎么在这块消费级显卡上活得好"的那一层：

- **门卫**：服务登记簿白名单 + 未登记进程检测驱逐 + 警告通知，杜绝"谁抢到显存是谁的"
- **指挥家**：动态显存预算 + QoS 服务质量降级 + 空闲回收 + 任务队列编排，安全约束下最大化吞吐和体验
- **秒级切换**：模型级 `/free` 释放替代容器级重启（10-30 秒），六场景一键切换

**首个落地项目**：`GMae-16GAS`（GPU Maestro-16G-AI-Studio）— 16GB 单卡全模态工作站，参赛 2026 上海开源软件应用创新大赛 · 智算云赛道。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ComfyUI](https://img.shields.io/badge/ComfyUI-0.33.0+-blue)](https://docs.comfy.org/)
[![GPU](https://img.shields.io/badge/GPU-8G~48G-green)]()
[![Docker](https://img.shields.io/badge/Docker-Required-blue)]()

---

## ✨ 核心特性（16GB 实测）

| 模态 | 模型 | 实测 |
|---|---|---|
| 🎨 文生图（标准） | SDXL 1.0 | ~60 秒/张（1024×1024） |
| 🎨 文生图（高质量） | Flux.1 dev Q5 GGUF | ~2分30秒/张（商业级画质） |
| 🎬 文生视频 | Wan 2.2 TI2V-5B | 480p 氛围/意境短片 |
| 🎵 AI 写歌 | ACE-Step / Music3 | ~82 秒/首 |
| 💬 本地对话 | qwen3.5:9b | ~40 tok/s |
| 🎛️ 显存编排 | 自研 P-Eng | 六场景一键切换，杜绝 OOM 死机 |

> 全部生成本地完成，无需 API Key、无需联网（首次下载模型除外）。
> ⚠️ 16GB 卡上视频生成的能力上限是"氛围感/意境类"短片；人物复杂动作必翻车（显存约束，非模型问题）。

---


## 📊 Benchmark 实测数据（16GB RTX 4060 Ti）

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 显存分解准确率 | **0.45% 误差** | GMae 估算 6656MB vs torch 实际 6686MB（SDXL 生成中） |
| 场景切换耗时 | **平均 9.7s** | 6/6 成功，最快 4.2s（容器已运行），最慢 16.7s（含释放） |
| auto_protect 响应 | **<10s 触发** | 空闲 834MB 时自动 L4 停止 Ollama，1s 内恢复到 11GB |
| 9B LLM 推理速度 | **43.5 tok/s** | qwen3.5:9b，显存 10.3GB/15.0GB total |
| 全模态能力矩阵 | SDXL 6.7GB / Flux 11.7GB / Wan2.2 10.9GB / Music3 14.5GB | 16GB 卡串行调度不翻车 |

> 完整 Benchmark 报告见 [16gb-ai-studio/vram-console/benchmark/benchmark_report.md](16gb-ai-studio/vram-console/benchmark/benchmark_report.md)

## 🏗️ 系统架构

### 三层架构（感知 → 账本 → 执行）

```
用户界面层（指挥台）：舞台总览 / 乐手名册 / 乐谱队列 / 演出日志
        ↓
调度中心（P-Eng 核心，Python 后端）
  感知层（耳）：进程级显存 / ComfyUI 事件 / 服务活跃度
  账本层（脑）：预算引擎 / 服务登记簿 / QoS 状态机 / 模型登记台
  执行层（手）：分级释放 L1-L4 / 驱逐 / 场景管理 / 任务队列
        ↓
执行引擎（乐手）：Ollama / ComfyUI / Fooocus / [可扩展]
```

### 角色演进：从门卫到指挥家

```
阶段1 遥控器 ── 被动：切场景、看总量
阶段2 门卫   ── 防御：登记簿白名单 + 未登记驱逐 + 警告
阶段3 指挥家 ── 编排：QoS 降级 / 空闲回收 / 任务队列
```

---

## 🚀 快速开始

### 前置要求
- NVIDIA GPU ≥ 8GB 显存（推荐 16GB，预算引擎动态适配 8G~48G）
- Docker Desktop（Windows）或 Docker Engine（Linux）
- 至少 50GB 磁盘空间（模型文件）

### 安装步骤
1. 克隆仓库：`git clone https://github.com/Dannywjw-Git/GMae-16GAS.git`
2. 按 [16gb-ai-studio/vram-console/README.md](16gb-ai-studio/vram-console/README.md) 配置调度中心
3. 下载模型到对应目录（Ollama / ComfyUI）
4. 启动调度中心：`16gb-ai-studio/vram-console/start.bat`（Windows）或 `start.sh`（Linux）
5. 访问 http://localhost:8787

> 完整架构设计见 [16gb-ai-studio/docs/调度中心架构与交互设计.md](16gb-ai-studio/docs/调度中心架构与交互设计.md)

---

## 📁 项目结构

```
GMae-16GAS/
├── 16gb-ai-studio/          # 16G-AI-Studio 子项目（参赛作品）
│   ├── vram-console/        # 调度中心（P-Eng 核心引擎）
│   │   ├── engine/          # 调度引擎（qos/budget/eviction/topology）
│   │   ├── gpu/             # GPU 感知层（monitor/processes）
│   │   ├── services/        # 服务适配层（docker/comfy/ollama）
│   │   ├── api/             # REST API 路由
│   │   ├── core/            # 基础层（config/logger/platform_detect）
│   │   ├── benchmark/       # 系统级 Benchmark 套件
│   │   ├── resources/       # 配置驱动（registry.json/hardware_profile.json）
│   │   ├── start.bat/.sh    # 启动脚本（Windows + Linux）
│   │   └── WATCHDOGS.md     # 看门狗统一登记册
│   ├── docs/                # 子项目文档（蓝图/进度/开发日志）
│   └── scripts/             # 子项目工具脚本
├── workflows/               # ComfyUI 工作流（可直接导入）
├── scripts/                 # 全局工具脚本
├── docs/                    # 项目级文档（总纲/显存指南/评测台帐）
├── docker/                  # Docker 部署示例
├── ROADMAP.md               # 项目路线图
├── CONTRIBUTING.md          # 贡献指南
├── CHANGELOG.md             # 变更日志
└── LICENSE                  # MIT
```

---

## 🏆 开源大赛

**2026 上海开源软件应用创新大赛 · 智算云赛道**

- 参赛项目：`GMae-16GAS`（GPU Maestro-16G-AI-Studio）
- 赛道定位：异构算力调度 / GPU 池化 / 资源效率（消费级单卡投影）
- 技术创新点：
  1. 消费级单卡跑通全模态生成（对话/图/视频/音乐）
  2. 配置驱动的资源注册表（registry.json），换模型只改一处
  3. 动态预算引擎 + 分级释放（秒级 `/free`），杜绝 OOM 死机
  4. 准入制 GPU 治理（登记簿 + 驱逐）+ 主动编排（QoS/回收/队列）

---

## 🗺️ 路线图

> 详细路线图见 [ROADMAP.md](ROADMAP.md)

### Step 0-8

```
Step 0 壳升级（多线程 + 桌面通知）
Step 1 ComfyUI /free 打通          ← 秒级释放
Step 2 进程级显存感知（compute-apps）
Step 2.5 服务登记簿 + 三级驱逐      ← 门卫
Step 3 模型登记台（扫描器 + 试跑校准）
Step 4 预算引擎（跑前算账）
Step 5 QoS 服务质量引擎            ← 指挥家
Step 6 Idle Reaper 空闲回收
Step 7 ComfyUI WebSocket 事件源
Step 8 任务队列（批量/无人值守）    ← 指挥家终态
```

---

## 📄 许可证

[MIT License](LICENSE)

### 模型许可证说明
- SDXL 1.0: CreativeML Open RAIL++-M
- Flux.1 dev: FLUX.1-dev Non-Commercial License
- Qwen 系列: Apache 2.0 / Qwen 许可
- 各模型许可详见对应官方文档

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

*一卡，全模态（1 GPU，∞ AI）— GPU Maestro*
