# 系统复制部署待办清单

> 目标：当前系统（ComfyUI + OWUI + ollama + Immich + SearXNG + Caddy）可一键复制到新机器。
> 创建时间：2026-08-25
> 状态：待逐项处理

## 一、ComfyUI 侧（当前主线）

- [x] torch 2.13+cu130 安装完成
- [x] ComfyUI 完整 requirements 安装
- [x] SageAttention 安装并启用（`--use-sage-attention` 参数）
- [x] ComfyUI 启动验证（/object_info 含 H3 节点）
- [x] H3 T2V 出片验证（640×640×73帧，带音频，成功）
- [x] **docker commit comfyui-h3:v1**（基础版，torch 2.13 + ComfyUI 0.33）
- [x] **docker commit comfyui-h3:v2**（装了 sageattention 1.0.6 包但未启用参数）
- [x] **docker commit comfyui-h3:v3**（SageAttention 已启用 `--use-sage-attention`，SDXL 出片验证通过，**当前使用**）
- [ ] docker save -o comfyui-h3-v3.tar comfyui-h3:v3（导出镜像，用于新机器部署）
- [x] **P0 安全修复**（2026-08-25）：S1命令注入、S2默认监听127.0.0.1+Token认证、S3补充game-on.ps1

## 二、OWUI 侧（3 个坑）

### 坑1：数据未持久化（最紧急）
- [x] 导出当前 OWUI 容器内数据：`docker cp open-webui-open-webui-1:/app/backend/data D:\docker\open-webui\data`（625MB）
- [x] 重建 OWUI 容器，挂载数据卷：`./data:/app/backend/data`（绑定挂载到 D 盘）
- [x] 验证数据持久化生效（用户/聊天记录/RAG文档完整）

### 坑2：IP 硬编码
- [x] OWUI 环境变量中 `192.168.1.8` 替换为 `host.docker.internal`
  - OLLAMA_BASE_URLS ✅
  - RAG_OLLAMA_BASE_URL ✅
  - SEARXNG_QUERY_URL ✅
  - AUDIO_STT_OPENAI_API_BASE_URL ✅
- [x] 验证各服务连通（ollama 200、SearXNG 200、STT 404但服务通）

### 坑3：ollama 是宿主机安装
- [x] 方案A：保持宿主机安装，新机器手动装 ollama + 拷模型（**当前状态，正常使用中**）
- [ ] 方案B（推荐）：ollama 容器化，用官方镜像 `ollama/ollama`，挂载模型目录
  - ⏸️ **2026-08-25 尝试容器化，镜像拉取困难（Docker Hub 国内慢、VPS 中转 save 文件损坏），待后续网络好时处理**
- [x] 确认 STT 服务（10303 端口）：`D:\whisper-cpp\stt_adapter.py`（whisper.cpp Python 适配器，OpenAI 兼容 API）

## 三、可复用资产清单

| 资产 | 大小 | 位置 | 复用方式 |
|------|------|------|----------|
| H3 模型全套 | ~52GB | D:\docker\comfyui\workspace\models\ | 直接拷贝 |
| Music3 模型 | ~14GB | 同上 | 直接拷贝 |
| SDXL/Flux 模型 | 若干GB | 同上 | 直接拷贝 |
| ollama 模型 | ~31GB | D:\ollama\models\ | 直接拷贝 |
| **torch 2.13 wheel 全套** | **~2.6GB** | **D:\Users\Danny\Documents\家庭智能中枢\_installers\*.whl** | **直接拷贝，新机器 cp 进容器安装** |
| ComfyUI 自定义镜像 | ~48GB | commit 后导出 | docker load |
| OWUI 数据 | 未知 | 容器内（待持久化） | 拷贝数据目录 |
| 工作流 JSON | <1MB | 项目目录 | 直接拷贝 |
| docker-compose.yml | <1KB | 待整理 | 直接拷贝 |
| 显存调度脚本 | <1MB | 项目目录 | 直接拷贝 |

> **🔑 torch wheel 全套是关键复用资产**：包含 torch+triton+torchvision+torchaudio+16个 nvidia-* 包，共 20 个 wheel。新机器无需重新下载（容器内 pip 下 nvidia 包极慢），直接 cp 进容器用 `--find-links` 安装。详见 `minimax-h3-deployment.md` 第三章。

## 四、新机器部署流程（目标）

1. 装 NVIDIA 驱动（支持 CUDA 13）+ Docker Desktop
2. 装 ollama（或容器化）→ 拷模型目录 → 启动
3. 装 STT 服务（10303端口）
4. docker load comfyui-h3-v1.tar
5. 拷贝所有模型目录 + 数据目录 + 配置
6. docker compose up -d
7. 验证全链路（OWUI → ollama / ComfyUI → H3 出片）

## 五、当前状态（2026-08-25 更新）

- ✅ ComfyUI 恢复完成：torch 2.13.0+cu130 + ComfyUI 0.33.0 + SageAttention
- ✅ H3 T2V 出片验证成功
- ✅ 已固化两个镜像：comfyui-h3:v1（基础）、comfyui-h3:v2（含 SageAttention）
- ✅ **OWUI 数据持久化**：绑定挂载到 D:\docker\open-webui\data（625MB）
- ✅ **OWUI IP 改造**：192.168.1.8 → host.docker.internal，全部服务连通验证通过
- ✅ **STT 服务确认**：D:\whisper-cpp\stt_adapter.py（whisper.cpp Python 适配器）
- ~~✅ **新加坡 exit node 上线**：ai-exit-sg（100.103.131.14 / 149.28.134.107），延迟 ~71ms，比东京快 3-4 倍~~ ❌ 已于 2026-08-26 下线，当前唯一 exit node 为东京 ai-exit-jp
- ✅ **ollama 容器化**（2026-08-26 完成，东京 VPS 中转下载，镜像备份 `_installers/ollama.tar`）
- 待办：导出 ComfyUI 镜像 tar、开源大赛准备、统一 docker-compose

### Tailscale 网络节点

| 设备 | Tailscale IP | 公网 IP | 延迟 | 用途 |
|------|-------------|---------|------|------|
| ai-homeserver（本机） | 100.102.52.12 | — | — | 家庭服务器 |
| ~~ai-exit-jp（东京旧）~~ | ~~100.81.128.51~~ | ~~207.148.107.141~~ | ~~280ms~~ | ❌ 已下线（2026-08-27） |
| **ai-registry-jp（东京新·主力）** | **100.126.118.93** | **167.179.66.179** | **~280ms** | **唯一 exit node + Docker Registry:5000 + Split Tunnel** |
| ~~ai-exit-sg（新加坡）~~ | ~~100.103.131.14~~ | ~~149.28.134.107~~ | ~~71ms~~ | ❌ 已下线（2026-08-26） |

## 六、已验证的坑（避免重犯）

| 坑 | 影响 | 解决 |
|---|---|---|
| 容器内 pip 下 nvidia-* 包极慢 | 几百 KB/s，200-400MB 大包反复断 | 宿主机 curl 批量下载（几十 MB/s）→ cp 进容器 → --find-links 安装 |
| docker restart 清空 /tmp | wheel 文件丢失，需重新 cp | wheel 放宿主机 _installers/ 目录持久保存 |
| pip cache 为空 | 重复下载 | 不依赖 cache，全部本地 wheel 安装 |
| docker compose up -d 重建容器 | 容器内所有改动丢失 | 禁用！用 docker exec/cp/restart，完成后 docker commit 固化 |
| nohup 后台 pip 输出缓冲 | 日志不实时，误判卡死 | 检查 /tmp/pip-unpack-*/*.whl 临时文件大小判断进度 |
| --find-links 对部分包不生效 | cusparse/cusolver 仍从网络下 | 容忍（仅这两个包慢），或重命名 wheel 为精确文件名 |
| **SageAttention 启用方式** | 设环境变量 SAGEATTN=1 无效，ComfyUI 不识别 | 必须用命令行参数 `--use-sage-attention`，写入 `/etc/comfyui_args.conf` |
| **xformers 版本不兼容** | torch 2.13 与 xformers 0.0.28 不匹配，报 warning | 可忽略，ComfyUI fallback 到 pytorch attention / SageAttention |

## 七、开源大赛报名待办（OS2026 上海开源软件应用创新大赛）

> 截止：10月11日提交作品，10月24日上海线下总决赛。赛道：开源AI工具。**已决定报名，个人参赛（不组队）。**

- [x] 决定是否报名 → ✅ 报名，个人参赛
- [ ] GitHub/Gitee 仓库改为 Public
- [ ] 补充效果展示素材（样例图/视频/音频）
- [ ] 录制演示视频（启动→选工作流→出片→显存监控）
- [ ] 整理作品介绍 PDF（项目背景、技术架构、创新点、应用场景、路线图）
- [ ] 项目定位包装：从"家庭智能中枢"调整为"面向小微工作室/个人创作者的低成本 AI 生成工具链"
- [x] 组队 → ✅ 个人参赛，不组队
- [ ] 官网填写报名表单，提交材料至 oscc@oschina.cn
