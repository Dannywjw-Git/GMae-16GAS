# GMae_Amanda 工作区（GMae 独立推进舱）

> **定位**：本文件夹是 **GMae 指挥家**（GMae-16GAS 开源大赛参赛项目）的**独立推进工作区**，与 `D:\Users\Danny\Documents\家庭智能中枢` **完全切割**（2026-08-28 主公指示，最高优先）。
> **用法**：所有 GMae 相关的开发/规划/材料/**全部输出**一律在本工作区推进与落盘；**不回写主仓库、不读取主仓库**（历史遗留文件除外，按需可读作参考）。
> **路径说明**：本文档内所有路径已适配本工作区根目录。
> **创建**：2026-08-28 ｜ 由主公指定为独立推进项目，与主仓库切割。

---

# AGENTS.md — 项目总入口（新 Agent 必读）

> **本文件是所有 AI Agent 接手本项目的第一入口。必须先读完本文件，再按指引阅读相关文档。**
> 最后更新：2026-08-27

---

## 🧠 记忆系统架构（三层指针体系）

本项目由三个 Agent 轮换协作（豆包 / WorkBuddy / DSH），记忆体系统一如下：

### 第一层：GMae 总项目（最高权威）
- **工作文件夹**：`D:\Users\Danny\Documents\GMae_Amanda\`
- **核心权威记忆文件**：`docs\家庭智能中枢建设方案_总纲_v3.0.md`
- **所有其它文档通过指针围绕总纲展开**，不得与总纲冲突
- **工作交接文档**：`工作交接.md`（根目录，跨 Agent/会话衔接用）

### 第二层：16GAS 子项目（参赛作品）
- **工作文件夹**：`D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\`
- **核心权威记忆文件**：`docs\调度中心架构与交互设计.md`
- **其它文档通过指针围绕蓝图展开**：`项目进度跟踪.md`、`开发日志.md`、`WATCHDOGS.md` 等

### 第三层：模块级文档
- 各模块自有 README / AGENTS / memory 文件
- 必须指向上一层核心权威文件

### Agent 命名兼容
不同 Agent 的记忆入口文件名可能不同：
- 豆包：`AGENTS.md`
- WorkBuddy：`memory.md`（如存在，内容与 AGENTS.md 一致）
- DSH：按其习惯命名（如存在，内容与 AGENTS.md 一致）
- **无论叫什么名字，内容必须指向同一套核心权威文件**

---

## ⚠️ 新 Agent 必读清单（按顺序，不得跳过）

| 序号 | 文件 | 位置 | 权威级别 | 必读原因 |
|------|------|------|---------|---------|
| 0 | **工作交接文档** | `工作交接.md`（根目录） | — | 上一个 Agent 留下的当前状态、未完成任务、注意事项 |
| 1 | **本文件** | `AGENTS.md`（根目录） | 总入口 | 记忆系统架构、禁令、操作规范 |
| 2 | **建设方案总纲 v3.0** | `docs\家庭智能中枢建设方案_总纲_v3.0.md` | ⭐最高权威 | 项目整体规划、战略、架构，所有决策的依据 |
| 3 | **看门狗登记册** | `16gb-ai-studio\vram-console\WATCHDOGS.md` | 操作约束 | 所有自启动/看门狗的唯一登记处，**禁止重复创建** |
| 4 | **16GAS 项目记忆** | `16gb-ai-studio\AGENTS.md` | 子项目权威 | 详细服务清单、操作约束、当前状态 |
| 5 | **显存管理最高指南** | `docs\显存管理最高指南.md` | 技术权威 | 16GB 单卡调度的最高规则，**违反会死机** |
| 6 | **调度中心架构与交互设计** | `16gb-ai-studio\docs\调度中心架构与交互设计.md` | 子项目权威 | 16GAS 的设计框架（架构+机制+交互），实施前必读 |
| 7 | **进度跟踪** | `16gb-ai-studio\docs\项目进度跟踪.md` | 状态 | 当前任务状态，避免重复工作 |
| 8 | **开发日志** | `16gb-ai-studio\docs\开发日志.md` | 历史 | 踩坑记录，避免重蹈覆辙 |
| 9 | **模型评测台帐** | `docs\模型评测台帐.md` | 参考 | 全模态模型评测结果、评分、能力上限结论 |

---

## 项目概述

**GPU Maestro-显存指挥家（GMae）** — 消费级 AI 服务器的显存编排专家：管"AI 生成工具怎么在消费级显卡上活得好"的那一层，覆盖所有消费级 AI 服务器（不限于 16GB）。

- **核心引擎**：Prism Engine-棱镜引擎（P-Eng）
- **首个落地子项目**（16GB 单卡参考实现）：16G-AI-Studio（16GAS）
- **标语**：One GPU, Infinite Models
- **开源大赛**：2026 上海开源软件应用创新大赛 — 智算云赛道

### 当前模型栈（2026-08-27）
| 模态 | 模型 | 状态 |
|------|------|------|
| 文生图（标准） | SDXL 1.0 | ✅ 跑通 |
| 文生图（高质量） | Flux.1 dev Q5 GGUF | ✅ 跑通（Fooocus 商业级） |
| 文生视频 | Wan2.2-TI2V-5B（9.3GB FP16） | ✅ 已跑通（480x480x17帧，峰值~10.9GB；替代 H3，H3 因 52GB OOM 不可行） |
| 文生音乐 | ACE-Step 1.5 Turbo | ✅ 已测（7.5分，轻微断音）；Music3 也可用 |
| 本地对话 | qwen3.5:9b | ✅ 跑通 |

> **Wan2.2 VAE 坑**：5B TI2V 必须用 `wan2.2_vae.safetensors`（1.3GB，48通道），不能用 `wan_2.1_vae`（16通道）。工作流用 ComfyUI 内置模板。
> **视频生成能力上限结论（2026-08-27 实测）**：16GB 卡上 Wan2.2-TI2V-5B 只能做"氛围感/意境类"短片（风景、慢镜头、单一主体）；**人物复杂动作必翻车**（480p 红裙舞女压力测试证实手部/肢体崩坏）。不要期待高质量人物动态。
> **EasyAIVid**：❌ 已评估后删除（2026-08-27）。其 Wan2.2-TI2V-5B 全量 diffusers 模型 34GB，设计面向 48GB 双卡，16GB 卡 + 32GB 内存跑 sequential_offload 内存顶满且极慢（480p 5秒约 11 分钟），已删除应用+源码+模型（约 39.4GB）。文生视频统一用 ComfyUI + GGUF 量化版。

---

## 🚫 绝对禁令（违反会导致系统损坏或数据丢失）

1. **禁止 `docker compose up -d comfyui`** — 会重建容器，清空 torch/SageAttention/自定义节点等所有改动。改容器用 `docker exec`/`docker cp`，完成后必须 `docker commit`。
2. **禁止显存打满** — 16GB 卡打满 = 系统死机。生成前必须释放显存到 <4GB。
3. **禁止重复创建看门狗** — 唯一看门狗是 `vram-console/watchdog.py`，已登记在 WATCHDOGS.md。新增/修改前必须先读 WATCHDOGS.md 并停止现有看门狗。
4. **禁止 home server 长期挂 exit node** — 仅下载大文件时临时启用，用完即关。
5. **禁止用 pythonw.exe 启动 watchdog.py** — 经测试不稳定，subprocess 会异常退出。用 python.exe + 最小化窗口。
6. **禁止用 junction/mklink 迁移 Docker 数据** — 会导致 WSL2 ext4.vhdx 丢失，所有镜像容器清空。Docker 数据迁移必须用官方方法：Docker Desktop → Settings → Resources → Advanced → Disk image location。（2026-08-26 事故教训）
7. **禁止盲目运行 >10GB 的模型** — 运行前必须计算：模型文件大小 + 量化方式 + 中间计算 ≈ 峰值显存，超过物理上限直接标记"不可行"。（H3 52GB 模型 OOM 教训）
8. **禁止根据文件大小判断下载完成** — aria2 等工具会预分配磁盘空间，文件大小正确不代表内容完整。下载后必须用 verify_file.py 或对应格式工具验证完整性。（torch wheel 损坏教训）

---

## 🔑 关键文件位置

| 类别 | 位置 |
|------|------|
| 项目根目录 | `D:\Users\Danny\Documents\GMae_Amanda\` |
| 子项目代码 | `16gb-ai-studio\` |
| 调度中心 | `16gb-ai-studio\vram-console\` |
| 文档目录 | `docs\` |
| 安装包/备份 | `_installers\` |
| 全局脚本 | `scripts_global\` |
| 产出物（图/视频/音频） | `outputs\`（images/、videos/、audio/ 子目录） |

---

## 🌐 基础设施与 VPS

| 设备 | 公网 IP | Tailscale IP | 用途 | 状态 |
|------|---------|-------------|------|------|
| ai-homeserver（本机） | — | 100.102.52.12 | 家庭服务器，运行所有 AI 服务 | ✅ 在线 |
| ~~ai-exit-jp（东京旧）~~ | ~~207.148.107.141~~ | ~~100.81.128.51~~ | ~~exit node + 文件中转，23G 磁盘~~ | ❌ 已下线（2026-08-27） |
| **ai-registry-jp（东京新·主力）** | **167.179.66.179** | **100.126.118.93** | **Exit Node + Docker Registry（5000端口）+ Split Tunnel，52G 磁盘** | ✅ 在线 |
| lisahost-hk（香港） | 64.90.14.210:39784 | 100.109.41.127 | Docker Registry Mirror，CMI 优化线路 | 📨 退款中（工单732676） |
| ~~ai-exit-sg（新加坡）~~ | ~~149.28.134.107~~ | ~~100.103.131.14~~ | 已下线 | ❌ 下线 |

> **ai-registry-jp（167.179.66.179 / 100.126.118.93）**：2026-08-26 上线，Vultr 东京，52G SSD，Ubuntu。已配置 Tailscale Exit Node + Split Tunnel（ACL exitNodeFilter：Cloudflare/GitHub/Google IP段走日本，国内直连）。Docker Registry 运行在 5000 端口，本地 Docker 已配置 `insecure-registries: ["167.179.66.179:5000"]`。SSH 密钥已配置（~/.ssh/id_ed25519），密码存用户变量 `VULTR_ROOT_55G`。
>
> **Split Tunnel 使用方法**：设备在 Tailscale 客户端选择 exit node = ai-registry-jp（一次性设置），之后自动分流——国外常用服务（Docker Hub/GitHub/Google等）走日本，国内直连，无需手动切换。家人手机/平板同理。

---

## 🛠️ 服务管理速查

| 服务 | 管理方式 | 端口 |
|------|---------|------|
| 调度中心 | `vram-console/start.bat` / `stop.bat` / `status.bat` | 8787 |
| OWUI | Docker 容器 `open-webui-open-webui-1` | 3000 |
| ComfyUI | Docker 容器 `comfyui`（**禁止 compose up -d**） | 8188 |
| Ollama | Docker 容器 `ollama` | 11434 |
| Immich | Docker compose | 2283 |
| SearXNG | Docker 容器 `searxng` | 8888 |

---

## 📋 Agent 操作规范

1. **接手先读**：按上方必读清单顺序阅读，不得跳过
2. **修改先查**：修改任何自启动/看门狗/定时任务前，先查 WATCHDOGS.md
3. **完成更新**：完成任何重大变更后，更新进度跟踪和开发日志
4. **看门狗管理**：
   - 启动服务：用户手动双击 `start.bat`（Agent 工具调用的后台进程会被沙箱清理）
   - 查看状态：双击 `status.bat` 或 `curl http://127.0.0.1:8787/api/health`
   - 停止服务：双击 `stop.bat`
5. **命名规范**：项目总名 GMae，核心引擎 P-Eng，子项目 16GAS，文档中视情况使用全称或简称
6. **🚫 蓝图禁止擅改（主公铁律，2026-08-28）**：`16gb-ai-studio/docs/调度中心架构与交互设计.md`（蓝图）是设计权威，**任何修改必须先经主公同意**——不允许"顺手修正/顺带更新"式擅改，哪怕发现它和代码不一致。确需改动，先给改动方案+理由，等主公批准再改；未获批准前保持原样。

---

## 📞 遇到问题

1. 先查 `docs/开发日志.md` — 可能已有踩坑记录和解决方案
2. 再查 `docs/显存管理最高指南.md` — 显存相关问题的最高权威
3. 查 `16gb-ai-studio/AGENTS.md` — 服务详情和操作约束
4. 查 `vram-console/WATCHDOGS.md` — 自启动/看门狗相关问题

---

*本文件是项目总入口，任何 Agent 接手必须先读。更新此文件需同步更新相关文档。*

