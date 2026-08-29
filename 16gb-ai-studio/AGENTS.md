# AGENTS.md — 项目记忆与操作指南

> 本文件供 AI Agent（豆包/Cursor/Copilot 等）快速理解项目状态和操作约束。
> 最后更新：2026-08-26

## ⚠️ 接手前必读（不得跳过）

### 记忆系统架构
- **GMae 总项目最高权威**：`../docs/家庭智能中枢建设方案_总纲_v3.0.md`
- **16GAS 子项目核心权威**：`docs/调度中心架构与交互设计.md`（本目录 docs 下）
- **工作交接**：`../工作交接.md`（跨 Agent/会话衔接）

### 必读清单
1. **`../工作交接.md`** — 上一个 Agent 留下的当前状态和待办
2. **`../AGENTS.md`** — 项目总入口、禁令、记忆系统架构
3. **`docs/调度中心架构与交互设计.md`** — 本子项目的设计框架（架构/机制/交互），实施前必读
4. **`vram-console/WATCHDOGS.md`** — 所有看门狗/自启动的唯一登记册，**禁止重复创建**
5. **`../docs/显存管理最高指南.md`** — 显存调度最高权威，违反会死机

---

## 项目概述

**GPU Maestro-显存指挥家（GMae）** — 消费级 AI 服务器的显存编排专家，核心引擎 Prism Engine-棱镜引擎（P-Eng），让一块 GPU 如棱镜般分出多种模态能力。

**首个落地子项目：16G-AI-Studio（16GAS）** — GMae 在 16GB 单卡上的参考实现/验证实例：跑通全模态本地 AI 生成（文生图/图生图/文生视频/图生视频/AI写歌/本地对话）。

- 项目总名：GPU Maestro-显存指挥家（GMae）
- 核心引擎：Prism Engine-棱镜引擎（P-Eng）
- 子项目：16G-AI-Studio（16GAS）
- 标语：One GPU, Infinite Models
- 开源路径：路径D（开源社区 + 技术服务）
- 仓库：GitHub `Dannywjw-Git/Local-AI-Studio`（私有）、Gitee `dnnywang/local-ai-studio`（私有）
- 开源大赛：OS2026 上海开源软件应用创新大赛，个人参赛，赛道：智算云（异构算力调度与 GPU 池化 / 推理加速），截止 10月11日

## 当前系统状态（2026-08-25）

### 硬件
- GPU：RTX 4060 Ti 16GB
- RAM：32GB
- CPU：i5-13400TEF
- 系统：Windows + WSL2 + Docker Desktop 29.7.2

### 服务清单

| 服务 | 部署方式 | 端口 | 状态 | 备注 |
|------|----------|------|------|------|
| ComfyUI | Docker 容器 `comfyui` | 8188 | ✅ 正常 | torch 2.13.0+cu130 + SageAttention 1.0.6（已启用），镜像 `comfyui-h3:v3` |
| Open WebUI | Docker 容器 `open-webui-open-webui-1` | 3000 | ✅ 正常 | 数据持久化到 `D:\docker\open-webui\data`，IP 已改 host.docker.internal |
| ollama | Docker 容器 `ollama` | 11434 | ✅ 正常 | 模型目录挂载 `D:\ollama\models`（30.9GB），GPU 加速，2026-08-26 容器化完成 |
| SearXNG | Docker 容器 `searxng` | 8888 | ✅ 正常 | |
| STT (whisper.cpp) | 宿主机 Python | 10303 | ✅ 正常 | `D:\whisper-cpp\stt_adapter.py` |
| Immich | Docker | 2283 | ✅ 正常 | |
| GMae 调度中心（P-Eng） | 宿主机 Python（开机自启） | 8787 | ✅ 正常 | `vram-console/server.py`，监听 0.0.0.0，启动项 `Startup\VRAM_Console.vbs`，带日志运行 |

### Tailscale 网络

| 设备 | Tailscale IP | 公网 IP | 用途 |
|------|-------------|---------|------|
| ai-homeserver（本机） | 100.102.52.12 | — | 家庭服务器 |
| ~~ai-exit-jp（东京旧）~~ | ~~100.81.128.51~~ | ~~207.148.107.141~~ | ~~exit node + 文件中转，23G 磁盘，延迟 ~280ms~~ ❌ 已下线（2026-08-27） |
| **ai-registry-jp（东京新）** | — | **167.179.66.179** | **Docker Registry 镜像中转，52G 磁盘，端口 5000** |
| **lisahost-hk（香港）** | **100.109.41.127** | **64.90.14.210:39784** | **exit node + Docker Registry Mirror，延迟 ~35ms，CMI 优化线路** |
| ~~ai-exit-sg（新加坡）~~ | ~~100.103.131.14~~ | ~~149.28.134.107~~ | ❌ 已下线（2026-08-26） |

> **新日本 VPS（167.179.66.179）**：2026-08-26 上线，Vultr 东京，52G SSD，Ubuntu，Docker Registry 运行在 5000 端口。本地 Docker 已配置 `insecure-registries: ["167.179.66.179:5000"]`，用于中转 ghcr.io 等国内无法直接拉取的大镜像（如 ComfyUI 13.5GB）。SSH 密钥已配置，密码存用户变量 `VULTR_ROOT_55G`。
> 香港 VPS（丽萨主机）于 2026-08-26 上线，CMI/CU2/CN2 三网直连，移动宽带优化。已配置 Docker Registry Mirror 缓存代理（`http://64.90.14.210:5000`），国内 Docker Desktop 配置 registry-mirrors 指向此地址即可加速拉取。Docker Desktop (WSL2) 无法访问 Tailscale IP，需用公网地址。

## 关键禁令（必须遵守）

1. **禁止 `docker compose up -d comfyui`** — 会重建容器，清空容器内所有改动（torch/SageAttention/自定义节点）。改容器用 `docker exec`/`docker cp`/`docker restart`，完成后必须 `docker commit` 固化。
2. **显存铁律** — 显存打满 = 系统死机。生成前必须运行 `gpu_release.ps1` 释放到 <4GB。
3. **home server 不要长期挂 exit node** — 仅下载大文件时临时启用，用完即关。
4. **容器内 pip 直接下载 nvidia-* 包极慢** — 必须用宿主机 curl 批量下载 wheel 到 `_installers/`，再 cp 进容器用 `--find-links` 安装。
5. **SageAttention 启用方式** — 必须写 `/etc/comfyui_args.conf` 加 `--use-sage-attention`，环境变量 `SAGEATTN=1` 无效。当前 comfyui-h3:v3 已启用，日志显示 `[INFO] Using sage attention`。sageattention 1.0.6 与 torch 2.13.0+cu130 兼容。

## 常用路径

| 用途 | 路径 |
|------|------|
| 项目根目录 | `D:\Users\Danny\Documents\家庭智能中枢\16gb-ai-studio\` |
| torch/nvidia wheel 包 | `D:\Users\Danny\Documents\家庭智能中枢\_installers\`（21个文件，2.8GB） |
| ComfyUI 模型 | `D:\docker\comfyui\workspace\models\` |
| OWUI 数据 | `D:\docker\open-webui\data\` |
| OWUI compose | `D:\docker\open-webui\docker-compose.yml` |
| ollama 模型 | `D:\ollama\models\` |
| STT 服务 | `D:\whisper-cpp\stt_adapter.py` |
| H3 测试视频 | `D:\Users\Danny\Documents\家庭智能中枢\outputs\h3_t2v_test_00001_.mp4` |

## 已固化 Docker 镜像

| 镜像 | 大小 | 说明 |
|------|------|------|
| `comfyui-h3:v1` | ~48GB | 基础版：torch 2.13 + ComfyUI 0.33 |
| `comfyui-h3:v2` | ~48GB | 装了 sageattention 1.0.6 包但启动参数未加 `--use-sage-attention`（未实际启用） |
| `comfyui-h3:v3` | ~48GB | **当前使用**：SageAttention 已启用（`/etc/comfyui_args.conf` 含 `--use-sage-attention`），SDXL 出片验证通过 |

> 尚未导出 tar，新机器部署时再 `docker save`。

## 待办事项

> 注意：本清单只覆盖 **16gb-ai-studio 开源项目**。家庭智能中枢整体待办（OWUI 升级/姜维/n8n/语音等）见 `../docs/家庭智能中枢建设方案_总纲_v3.0.md` §7.3。

### 🔴 高优先级（主线）

- [ ] ~~**OWUI + ComfyUI 打通（Function Calling 一条龙）**~~ **🅿️ 已搁置为远期**（2026-08-27 战略定位：专注专家显存编排；"一句话出片"是伪需求，9B 工具调用可靠性未验证）。**当前主线**：Step 0-8 专家显存编排，见 `docs/调度中心架构与交互设计.md`
- [ ] 开源大赛准备：效果展示素材、作品介绍 PDF、演示视频（截止 10月11日）
- [x] 开源项目 P0 安全修复（2026-08-25 完成）：S1命令注入、S2未授权访问、S3缺失game-on.ps1

### 🟡 中优先级

- [x] ollama 容器化（2026-08-26 完成）：镜像通过东京 VPS 中转下载（分割文件法 + aria2 批量），容器名 `ollama`，挂载模型目录，GPU 加速正常，OWUI 连通验证通过
- [ ] 导出 ComfyUI 镜像 tar（新机器部署用）
- [ ] STT 服务容器化
- [ ] 统一 docker-compose.yml（产品化阶段1）
- [x] run_comfy.js 超时机制 + 内部标识移除（2026-08-25 完成）
- [x] combo_switch 模型存在性检查（2026-08-25 完成）

### 🟠 审计报告中仍未修复

- [ ] README 补充模型许可证说明（Flux.1 dev 非商用等）
- [ ] 验证 Docker Compose 模板可用性
- [ ] 补充效果展示素材（至少 1 张图 + 1 个视频 + 1 段音频）
- [ ] 补充 CONTRIBUTING.md / CHANGELOG.md
- [ ] 添加单元测试 / 集成测试

### 🟢 低优先级

- [ ] GitHub Desktop 中文版（无官方中文版，可用浏览器翻译）
- [ ] Docker Desktop 升级（当前 29.7.2 稳定，不追新）

## 文档索引

| 文档 | 内容 |
|------|------|
| `README.md` | 项目主页（特性/快速开始/模型清单/许可证） |
| `CONTRIBUTING.md` | 贡献指南（开发环境/提交规范/PR流程/代码风格） |
| `CHANGELOG.md` | 更新日志（语义化版本） |
| `docs/deployment-replication-checklist.md` | 系统复制部署待办清单（含当前状态） |
| `docs/troubleshooting.md` | 踩坑全集（nvidia包下载、SageAttention等） |
| `docs/minimax-h3-deployment.md` | H3 部署指南（含 torch 2.13 升级完整步骤） |
| `docs/productization-roadmap.md` | 产品化与分发部署路线图（三阶段） |
| `docs/vram-governance.md` | 显存管理指南（防死机铁律，精简版） |
| `docs/business-analysis.md` | 商业分析（路径D） |
| `docs/audit-report.md` | 第三方独立审计报告（S1/S2/S3已修复） |
| `docs/article-16gb-ai-studio.md` | 技术文章草稿 |
| `docs/handover.md` | 交接记录（多Agent协作） |

## VPS 操作

- ~~东京旧：`ssh root@100.81.128.51`（Tailscale）或 `root@207.148.107.141`（公网），Ubuntu，SSH 密钥登录，Docker 已装，23G 磁盘~~ ❌ 已下线（2026-08-27）
- **东京新（Registry）**：`ssh root@167.179.66.179`（公网），Ubuntu，SSH 密钥登录，Docker 已装，52G 磁盘，Registry 端口 5000，密码存用户变量 `VULTR_ROOT_55G`
- **香港（丽萨主机）**：`ssh -p 39784 root@64.90.14.210`（公网）或 `ssh -p 39784 root@100.109.41.127`（Tailscale），Ubuntu 22.04，1核1G+1G swap，20G磁盘，Docker 29.7.2，Docker Registry Mirror 运行在 5000 端口
- ~~新加坡：`ssh root@100.103.131.14`（Tailscale）或 `root@149.28.134.107`（公网）~~ ❌ 已下线（2026-08-26）

### 香港 VPS 关键信息（2026-08-26 上线）

| 项目 | 值 |
|------|-----|
| 服务商 | 丽萨主机 lisahost.com |
| 套餐 | 香港三网直连 CMI/CU2/CN2 精品网络 ISP VPS - 基础版 |
| 公网 IP | 64.90.14.210 |
| SSH 端口 | 39784（非默认 22，防扫描） |
| Tailscale IP | 100.109.41.127（主机名 lisahost-hk） |
| 系统 | Ubuntu 22.04.5 LTS |
| 内存/磁盘 | 1G RAM + 1G swap / 20G SSD |
| Docker | 29.7.2，已安装运行 |
| Registry Mirror | `http://64.90.14.210:5000`（公网）/ `http://100.109.41.127:5000`（Tailscale） |
| 容器 | registry-mirror（registry:2，proxy 模式缓存 Docker Hub） |
| 防火墙 | UFW 未启用，iptables 有 Tailscale 规则 |

> 香港 VPS 的 SSH 密钥登录曾被加固脚本误禁用（PubkeyAuthentication=no），当前仅密码登录。后续需修复：`sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config && systemctl restart sshd`，确认密钥可用后再禁用密码登录。
> Registry Mirror 缓存目录 `/var/lib/registry`，已配每天凌晨 3 点清理 7 天前的缓存。
