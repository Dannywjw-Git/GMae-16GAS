# GPU Maestro-显存指挥家 · 调度中心

> **新 Agent 必读：先读 `WATCHDOGS.md`（看门狗登记册），再操作本目录任何文件。禁止重复创建看门狗。**

> **项目**：GPU Maestro-显存指挥家（GMae）
> **子项目**：16G-AI-Studio（16GAS）— 16GB 单卡全模态 AI 工作站
> **核心引擎**：Prism Engine-棱镜引擎（P-Eng）
> **标语**：One GPU, Infinite Models

16GB 单卡的显存调度 Web UI。场景一键切换 + Prism Engine 智能显存管理，防止打满死机。
设计权威：`16gb-ai-studio/docs/调度中心架构与交互设计.md`（蓝图，修改需主公同意）。

## 功能（对齐蓝图 Step 1-8）

- 📊 实时显存监控 + **进程级显存账本**（容器内 NVML PID + 进程自报显存拼接；生命周期追踪：何时开始/退出/首见显存/强制驱逐）
- 🎯 场景一键切换：对话 / SDXL出图 / Wan2.2出视频 / Flux出图 / 音乐 / 游戏
- 🛡️ 门卫 gpu_guard：登记簿 + 白占点名 + L0/L1/L2 驱逐（**绝不自动杀**，防误伤正在跑的任务）
- 🧮 **预算引擎**（`/api/budget`）：按蓝图§6 核算每个模型 `ok / free_L1 / free_L2 / reject` + 差多少 GB
- 🛡️ **QoS 服务等级引擎**：水位状态机（GREEN<8G / YELLOW 8~12G / RED>12G）+ RED 自动降 0.6B + 前端横幅 + 日志
- 📋 **模型登记台**（registry.json 配置驱动，加模型不改代码）+ **模型扫描器**（扫描实际 vs 登记，一键登记，写前备份）
- 🚦 **任务队列**（Step 8）：16G 单卡串行化，状态机 提交→排队→预检→释放→生成→完成，可取消
- 🕐 ComfyUI WebSocket 实时事件 + Idle Reaper 空闲回收（用毕必停自动化）
- 🖥️ Windows 桌面 GPU 进程：默认汇总；启用 Helper（UAC 确认）后可看逐进程明细 + 管理
- 🔄 Ollama 模型组合切换（9B / 0.6B / qwythos / darkidol …，registry combos 配置）

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

- **资源注册表**：`resources/registry.json` 是唯一数据源（system/containers/scenes/gpu_guard/ollama/comfyui 模型 + workflow 模板引用 + combos）。加模型/场景只改这一个文件，前端自动生效。
- **API Token**：`VRAM_CONSOLE_TOKEN` 环境变量或 `config.json`。设置后所有请求需带 `X-API-Key` 请求头。
- **端口**：`VRAM_CONSOLE_PORT`（默认 8787）；**监听**：`VRAM_CONSOLE_HOST`（默认 0.0.0.0，内网/Tailscale 访问）。

> **安全提示**：默认监听 `0.0.0.0` 无认证。公网暴露务必设置 Token，否则任何人可控制你的 AI 环境。

## 场景说明

| 场景 | 动作 | 适用 |
|---|---|---|
| 对话态 | 加载 9B 模型，关闭出图服务 | 日常聊天/写作/RAG |
| SDXL出图 | 释放模型，SDXL 生成（ComfyUI） | 标准文生图 |
| Wan2.2出视频 | 释放模型，Wan2.2-TI2V 独占（ComfyUI） | 文生视频（480p，氛围感类） |
| Flux出图 | 释放模型，Flux 独占全卡（ComfyUI） | 高质量文生图（Fooocus 商业级） |
| 音乐态 | 释放模型，Music3 独占全卡（ComfyUI） | AI 写歌 |
| 游戏态 | 释放全部 AI，关文生图容器 | 玩游戏/串流 |

> **铁律**：切换前自动检测显存，空闲 <4G 强制先释放（M1 铁律）。依据《显存管理最高指南》v1.3。

## 目录结构

```
vram-console/
├── server.py              # 后端（Python 标准库，零依赖）
├── index.html             # 前端（单文件 HTML + 原生 JS）
├── resources/registry.json # 资源注册表（唯一数据源）
├── workflows/             # 任务队列工作流模板（wan2.2_ti2v.json 等；API 格式，可参数化）
├── watchdog.py / WATCHDOGS.md  # 看门狗登记册（唯一登记处，禁止重复创建）
├── vram-helper.py         # Windows 桌面进程 Helper（提权后查/管桌面 GPU 进程）
├── start.bat / stop.bat / status.bat / run_watchdog.bat
└── logs/                  # 结构化运行日志
```

## 技术栈

- 后端：Python 标准库（http.server + ThreadingHTTPServer），零依赖
- 前端：单文件 HTML + 原生 JS，无构建
- 数据：nvidia-smi（NVML PID）+ 容器内进程自报显存（ollama /api/ps、comfyui /system_stats、fooocus 规格）+ ComfyUI API（/prompt /history /queue /free）+ WebSocket 实时事件
