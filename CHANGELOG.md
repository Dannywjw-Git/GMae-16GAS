# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增
- `scripts/game-on.ps1`：游戏态显存释放脚本（停 AI 容器 + 卸 Ollama 模型 + 显存确认）
- `CONTRIBUTING.md`：贡献指南
- `CHANGELOG.md`：本文件
- `examples/output-samples/.gitkeep`：输出样例目录占位

### 修复
- **SageAttention 正式启用**：`/etc/comfyui_args.conf` 添加 `--use-sage-attention`，重启后日志显示 `[INFO] Using sage attention`，SDXL 出片验证通过（1分钟）。固化镜像 `comfyui-h3:v3`。此前 v2 仅安装了 sageattention 1.0.6 包但未加启动参数（实际未启用）。
- **S1 命令注入**：`vram-console/server.py` 新增 `_safe_model_name()` 白名单校验 + `run_args()` 使用 `shell=False` 参数数组，`model_action()`/`docker_action()`/`ollama_stop()` 全部参数化
- **S2 未授权访问**：默认监听从 `0.0.0.0` 改为 `127.0.0.1`，新增 `VRAM_CONSOLE_TOKEN` 可选 Token 认证（`X-API-Key` 请求头），POST JSON 解析失败返回 400
- **M1 无超时**：`scripts/run_comfy.js` 新增默认 30 分钟超时（`RUN_TIMEOUT` 环境变量或第4参数可覆盖）
- **M2 内部标识**：`run_comfy.js` 的 `client_id` 前缀从 `dsh-ltx23-` 改为 `local-ai-studio-`
- **M3 硬编码模型**：`combo_switch()` 从 Ollama `/api/tags` 动态获取已安装模型，未安装时友好提示跳过
- `docs/article-16gb-ai-studio.md`：修正 Gitee 链接拼写错误（`loacal` → `local`）、H3 文本编码器大小（15.7GB → 14.6GB）
- `docs/deployment-replication-checklist.md`：修正 ComfyUI 镜像大小（~10GB+ → ~48GB）
- `docs/troubleshooting.md`：更新 host.docker.internal 说明（当前版本已稳定，早期版本有抖动）

### 文档
- `docs/audit-report.md`：S1/S2/S3 标注"已修复（2026-08-25）"
- `docs/productization-roadmap.md`：更新 OWUI/ollama 组件状态、优先级说明
- `docs/vram-governance.md`：添加完整版指针说明
- `vram-console/README.md`：新增 `VRAM_CONSOLE_HOST`/`VRAM_CONSOLE_TOKEN` 环境变量说明
- `scripts/README.md`：新增 game-on.ps1 说明、run_comfy.js 超时参数说明

---

## [0.1.0] - 2026-08-25

### 新增
- 项目初始化：16GB AI Studio 开源仓库创建
- `vram-console/`：显存调度中心（Python 标准库后端 + 单文件 HTML 前端），5 场景一键切换
- `scripts/run_comfy.js`：ComfyUI 工作流运行器（提交→轮询→拉取输出）
- `scripts/gpu_release.ps1` / `.sh`：生成前显存释放脚本（跨平台）
- `workflows/`：5 个开箱即用工作流（SDXL/Flux/H3 T2V/H3 I2V/Music3）
- `docker/compose-examples/`：Docker Compose 部署模板
- `docs/`：完整文档体系（部署指南/踩坑集/审计报告/商业分析/产品化路线图/技术文章）
- `AGENTS.md`：项目记忆与操作指南（AI Agent 必读）
- `docs/handover.md`：多 Agent 协作交接记录

### 技术成果
- ComfyUI 0.33.0 + torch 2.13.0+cu130 + SageAttention 部署成功
- MiniMax H3 文生视频（640×640·5s·带音频）4 分钟出片验证
- MiniMax Music 3 AI 写歌验证通过
- 已固化 Docker 镜像 `comfyui-h3:v1`（基础）/ `v2`（含 SageAttention）

---

*格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)*
