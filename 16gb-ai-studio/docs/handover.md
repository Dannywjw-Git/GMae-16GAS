# 交接记录

> 记录每次会话的操作内容、成果和待办，方便多 Agent 协作和会话切换。

## 2026-08-26 会话 #5（香港 VPS + Docker Registry Mirror）

### 本次完成

1. **香港 VPS 采购与上线**
   - 服务商：丽萨主机（lisahost.com），支付宝付款，48小时无条件退款
   - 套餐：香港三网直连 CMI/CU2/CN2 精品网络 ISP VPS - 基础版，1核1G/20G SSD/50Mbps
   - 公网 IP：64.90.14.210，SSH 端口 39784，Ubuntu 22.04.5 LTS
   - 移动宽带实测延迟 ~35ms（Tailscale P2P 直连）

2. **Docker Registry Mirror 搭建（核心成果）**
   - 在香港 VPS 上运行 `registry:2` 容器，配置为 Docker Hub proxy cache 模式
   - 监听 `0.0.0.0:5000`（公网+Tailscale 均可访问）
   - 国内 Docker Desktop 配置 `registry-mirrors: ["http://64.90.14.210:5000"]` 即可加速
   - 缓存目录 `/var/lib/registry`，已配 crontab 每天凌晨 3 点清理 7 天前缓存
   - 验证：Registry 日志确认来自国内 IP（183.193.41.62）的 pull 请求已到达并代理到 Docker Hub

3. **Tailscale exit node 配置**
   - 香港节点主机名 `lisahost-hk`，Tailscale IP 100.109.41.127
   - ~~已开启 IP 转发和 exit node 广告，与东京 ai-exit-jp 并列~~（东京旧已于 08-27 下线，当前唯一 exit node 为 ai-registry-jp）

4. **Docker 安装**
   - Docker 29.7.2，通过官方 apt 源安装
   - 添加了 1G swap 防止 OOM

### 遇到的坑

1. **安全加固脚本改密码后失联** — 第一个加固脚本（vps_harden.py）随机生成新密码但未记录，导致 SSH 无法登录。通过丽萨主机面板重置密码解决。后续脚本不再自动改密码。
2. **dpkg 锁被占用** — 之前中断的 apt 进程导致 `dpkg --configure -a` 报错。清理锁文件后重新安装成功。
3. **paramiko 长连接断开** — 后台 Python 脚本通过 paramiko 执行长时间命令时，SSH 连接易断导致命令中断。改用 `nohup` 在 VPS 本地后台执行脚本，SSH 断了也不影响。
4. **Docker Desktop (WSL2) 无法访问 Tailscale IP** — WSL2 网络栈与 Windows 主机的 Tailscale 不通，`docker pull` 走 Tailscale IP 超时。解决方案：Registry 监听公网 IP，Docker Desktop 用公网地址。
5. **ComfyUI 镜像名不存在** — `yanwk/comfyui-boot`、`obeliks/comfyui`、`ai-dock/comfyui` 等多个镜像在 Docker Hub 上无 `latest` 标签，全部返回 404。需确认具体镜像名和标签后再拉取。
6. **国内 Docker 镜像源大面积失效** — 南大（403）、daocloud（白名单）、163 等均不可用。香港 VPS Registry Mirror 是当前最稳定的方案。

### 注意事项

- 香港 VPS 的 SSH 密钥登录曾被加固脚本误设为 `PasswordAuthentication no` 但公钥未配成功，导致密钥和密码都登不上。当前通过面板重置密码后仅密码登录可用。**后续需修复 SSH 配置**：先确认公钥已写入 `~/.ssh/authorized_keys`，再设 `PubkeyAuthentication yes`，测试密钥登录成功后才禁用密码登录。
- Registry Mirror 当前暴露公网（0.0.0.0:5000），无认证。后续应加 IP 白名单（仅允许国内家宽 IP）或 basic auth。
- VPS 仅 20G 磁盘，Registry 缓存需定期清理，已配 crontab。
- ComfyUI 镜像尚未成功拉取，需确认可用的镜像名/标签。

### 下一步建议

1. **修复香港 VPS SSH 密钥登录** — 恢复 PubkeyAuthentication，配置密钥后禁用密码登录
2. **Registry Mirror 加安全限制** — IP 白名单或 basic auth，防止被滥用
3. **确认可用的 ComfyUI Docker 镜像** — 在 Docker Hub 搜索带 latest 标签的镜像，或用具体版本标签
4. **测试 Registry Mirror 拉取速度** — 拉一个已知存在的镜像（如 alpine、nginx）验证缓存和回国速度
5. **开源大赛准备**（截止 10月11日）— 效果展示素材、演示视频、作品介绍 PDF

### 关键文件变更

| 文件 | 变更 |
|------|------|
| `AGENTS.md` | Tailscale 表格添加香港节点，VPS 操作部分新增香港 VPS 详细信息 |
| `docs/handover.md` | 本次交接记录 |
| `scripts/vps_*.py` | 新建多个 VPS 管理脚本（安装Docker/Registry/Tailscale等） |

---

## 2026-08-26 会话 #4（SageAttention 启用）

### 本次完成

1. **SageAttention 正式启用**
   - 背景：之前文档记录说 SageAttention "已安装并启用"，但实际检查发现 `/etc/comfyui_args.conf` 中没有 `--use-sage-attention` 参数，日志也没有 SageAttention 输出。sageattention 1.0.6 包装了但没启用。
   - DSH 交接文档记录：sageattention 1.0.6 + `--use-sage-attention` 会让 ComfyUI 起不来（08-25 早的环境）。
   - 本次操作：备份配置 → 添加 `--use-sage-attention` → supervisorctl restart comfyui → 启动成功，日志显示 `[INFO] Using sage attention`。
   - 验证：SDXL 文生图测试通过（1分钟出片，1612KB PNG），SageAttention 下生成功能正常。
   - 固化：`docker commit comfyui comfyui-h3:v3`（48.2GB）。
   - 结论：在 torch 2.13.0+cu130 + ComfyUI 0.33.0 环境下，sageattention 1.0.6 + `--use-sage-attention` 可以正常工作。DSH 当时的启动失败可能是因为环境不同（torch 版本？ComfyUI 版本？）。

2. **文档修正**
   - AGENTS.md：ComfyUI 镜像更新为 v3，SageAttention 状态更新为"已启用"，镜像清单区分 v1/v2/v3
   - CHANGELOG.md：添加 SageAttention 启用记录
   - deployment-replication-checklist.md：镜像版本更新

### 镜像版本说明

| 镜像 | 状态 |
|------|------|
| comfyui-h3:v1 | 基础版：torch 2.13 + ComfyUI 0.33 |
| comfyui-h3:v2 | 装了 sageattention 1.0.6 包但未加启动参数（未实际启用） |
| comfyui-h3:v3 | **当前使用**：SageAttention 已启用，SDXL 出片验证通过 |

### 注意事项

- ComfyUI 容器当前运行中（端口 8188），SageAttention 已启用
- 旧镜像 v1/v2 仍保留，可删除释放空间（各 48GB）
- 如需导出 tar 用于新机器部署：`docker save -o comfyui-h3-v3.tar comfyui-h3:v3`

### 下一步建议

1. **OWUI + ComfyUI 打通**（主线）：在 OWUI 对话中直接调用 ComfyUI
2. **开源大赛准备**（截止 10月11日）：效果展示素材、演示视频、作品介绍 PDF
3. 可选：删除旧镜像 v1/v2 释放 ~96GB 硬盘空间

### 关键文件变更

| 文件 | 变更 |
|------|------|
| 容器内 `/etc/comfyui_args.conf` | 添加 `--use-sage-attention` |
| `AGENTS.md` | 镜像版本 v2→v3，SageAttention 状态更新 |
| `CHANGELOG.md` | 添加 SageAttention 启用记录 |
| `docs/handover.md` | 本次交接记录 |

---

## 2026-08-26 会话 #3（文档整理与纠错）

### 本次完成

1. **事实错误修正（5项）**
   - `article-16gb-ai-studio.md`：Gitee 链接拼写错误 `loacal-ai-studio` → `local-ai-studio`（2处）
   - `article-16gb-ai-studio.md`：H3 文本编码器大小 15.7GB → 14.6GB（与 README/部署指南一致）
   - `deployment-replication-checklist.md`：ComfyUI 自定义镜像 ~10GB+ → ~48GB
   - `productization-roadmap.md`：ollama 容器化状态"进行中" → "暂停（镜像拉取困难）"
   - `productization-roadmap.md`：OWUI 组件状态从"IP硬编码/命名卷" → "已完成持久化+IP改造"

2. **矛盾点统一（3项）**
   - `troubleshooting.md`：host.docker.internal 从"一律用IP直连" → "当前版本已稳定，早期版本有抖动，遇问题可回退IP"
   - vram-console 双副本同步：安全修复后的 `server.py`（16572 bytes）已同步到正式部署位置 `D:\scripts\vram-console\`，旧版备份为 `server.py.bak-20260826-pre-security-fix`
   - `vram-governance.md`：顶部添加指针说明，指向家庭智能中枢内部完整版《显存管理最高指南》v1.3

3. **文档去重与状态更新（3项）**
   - `audit-report.md`：S1/S2/S3 正文添加"✅ 已修复（2026-08-25）"标注及修复说明，原问题描述保留参考
   - `productization-roadmap.md`：头部优先级从"ComfyUI恢复" → "开源大赛准备+OWUI打通"
   - `deployment-replication-checklist.md`：OWUI坑1/坑2/坑3方案A标记完成，新增P0安全修复完成项

4. **缺失文档补充（3项）**
   - 新建 `CONTRIBUTING.md`：贡献指南（开发环境/提交规范/PR流程/代码风格/安全要求）
   - 新建 `CHANGELOG.md`：更新日志（v0.1.0 + Unreleased，语义化版本）
   - `README.md`：许可证章节扩展，列出各模型许可证（Flux.1 dev 非商用/SDXL RAIL/H3&Music3 Apache2.0），项目结构新增 CONTRIBUTING/CHANGELOG/game-on.ps1/gpu_release.sh

### 验证

- Grep 确认 `loacal` 拼写错误仅在 CHANGELOG 历史记录中保留
- CONTRIBUTING.md / CHANGELOG.md 文件存在
- D:\scripts\vram-console\server.py 大小 16572 bytes，与项目内版本一致

### 注意事项

- 当前 vram-console 服务运行的是项目内版本（沙箱 python，PID 54980），正式部署位置 D:\scripts\ 已同步但未重启
- 重启电脑后若用 start_vram_console.bat 启动，将运行 D:\scripts\ 的安全修复版
- 家庭智能中枢总纲中 vram-console 路径写的是 D:\scripts\vram-console\，与实际部署一致

### 下一步建议

1. **开源大赛准备**（截止 10月11日）：效果展示素材、演示视频、作品介绍 PDF、仓库改 Public
2. **OWUI + ComfyUI 打通**（主线）：在 OWUI 对话中直接调用 ComfyUI 生成图/视频/音频
3. 重启 vram-console 服务使用正式部署位置版本（可选，当前运行正常）

### 关键文件变更

| 文件 | 变更 |
|------|------|
| `docs/article-16gb-ai-studio.md` | 修正 Gitee 链接拼写 + H3 文本编码器大小 |
| `docs/deployment-replication-checklist.md` | 修正镜像大小 + 标记完成状态 + 新增安全修复项 |
| `docs/productization-roadmap.md` | 更新 ollama/OWUI 状态 + 优先级说明 |
| `docs/troubleshooting.md` | 更新 host.docker.internal 说明 |
| `docs/audit-report.md` | S1/S2/S3 标注已修复 + 修复说明 |
| `docs/vram-governance.md` | 添加完整版指针 |
| `README.md` | 扩展模型许可证说明 + 更新项目结构 |
| `CONTRIBUTING.md` | 新建 |
| `CHANGELOG.md` | 新建 |
| `D:\scripts\vram-console\server.py` | 同步安全修复版（旧版备份） |

---

## 2026-08-25 会话 #2（安全修复）

### 本次完成

1. **S1 命令注入修复**（server.py）
   - 新增 `_safe_model_name()` 模型名白名单校验（正则 `^[A-Za-z0-9._:/\-]+$`，长度≤128）
   - 新增 `run_args()` 函数使用 `shell=False` + 参数数组执行命令
   - `model_action()`: name 校验 + `ollama run/stop` 改用参数数组
   - `docker_action()`: name 白名单（comfyui/fooocus）+ action 白名单（start/stop/restart）+ 参数数组
   - `ollama_stop()` / `ollama_stop_all()`: 改用参数数组
   - `run()` 保留 `shell=True` 但仅用于内部硬编码命令（nvidia-smi、docker ps 等）

2. **S2 未授权访问修复**（server.py）
   - 默认监听地址从 `0.0.0.0` 改为 `127.0.0.1`
   - 新增环境变量 `VRAM_CONSOLE_HOST` 可覆盖监听地址
   - 新增可选 Token 认证：环境变量 `VRAM_CONSOLE_TOKEN`，设置后所有 POST 和 `/api/status` 需带 `X-API-Key` 请求头
   - 监听非 localhost 且无 Token 时打印 WARNING
   - POST body JSON 解析失败返回 400（之前静默忽略）

3. **S3 缺失 game-on.ps1 修复**
   - 新建 `scripts/game-on.ps1`：停止 comfyui/fooocus 容器 + 卸载 Ollama 模型 + 显存确认
   - 支持 `-ThresholdMB` 参数（默认 2048MB）
   - 容器未运行时自动跳过，不报错

4. **M1 run_comfy.js 超时机制**
   - 新增超时：默认 30 分钟，环境变量 `RUN_TIMEOUT` 或第4个命令行参数可覆盖
   - 超时后打印错误并退出码 1
   - 进度日志每 5 分钟打印一次（去重）

5. **M2 内部标识移除**（run_comfy.js）
   - `client_id` 前缀从 `dsh-ltx23-` 改为 `local-ai-studio-`

6. **M3 combo_switch 模型硬编码修复**（server.py）
   - 新增 `ollama_tags()` 从 Ollama API 动态获取已安装模型列表
   - combo_switch 执行前检查模型是否已安装，未安装时返回 "SKIP: model not installed" 友好提示
   - stop 操作只停止已安装的模型

7. **L2 输入校验增强**（run_comfy.js）
   - workflow 文件不存在时友好报错
   - workflow JSON 解析失败时友好报错

### 验证

- Python 语法检查通过（`python -m py_compile server.py`）
- Node.js 语法检查通过（`node --check run_comfy.js`）
- 未做运行时测试（需重启 vram-console 服务验证）

### 注意事项

- vram-console 服务当前可能仍在运行旧版本，需重启生效：`taskkill /f /im pythonw.exe` 后重新 `start.bat`
- 默认监听改为 127.0.0.1 后，局域网其他设备无法访问（这是预期的安全改进）
- 如需局域网访问，设置 `VRAM_CONSOLE_HOST=0.0.0.0` 和 `VRAM_CONSOLE_TOKEN=your_token`

### 下一步建议（按优先级）

1. **重启 vram-console 验证安全修复**（确认服务正常、前端可访问）
2. **开源大赛准备**（截止 10月11日）
   - 生成效果展示素材（样例图/视频/音频）
   - 录制演示视频
   - 写作品介绍 PDF
   - 仓库改 Public
3. ~~**ollama 容器化**（待网络好时，用新加坡 exit node）~~ ✅ 已完成（2026-08-26，东京 VPS 中转下载，新加坡已于 08-26 下线）
4. **导出 ComfyUI 镜像 tar**（新机器部署用）

### 关键文件变更

| 文件 | 变更 |
|------|------|
| `vram-console/server.py` | S1/S2/M3/L2 安全修复，新增 run_args/_safe_model_name/ollama_tags，默认监听 127.0.0.1 |
| `scripts/run_comfy.js` | M1 超时机制 + M2 内部标识移除 + L2 输入校验 |
| `scripts/game-on.ps1` | 新建，游戏态显存释放脚本 |
| `AGENTS.md` | 待办事项标记完成 |
| `docs/handover.md` | 本次交接记录 |

---

## 2026-08-25 会话交接

### 本次完成

1. **ComfyUI 恢复**（前序会话完成，本次确认）
   - torch 2.13.0+cu130 安装（宿主机下载 wheel → cp 进容器）
   - ComfyUI 0.33.0 + 完整 requirements
   - SageAttention 安装并启用（`--use-sage-attention` 参数）
   - H3 T2V 出片验证成功（640×640×73帧，带音频）
   - docker commit 固化：comfyui-h3:v1（基础）、comfyui-h3:v2（含SageAttention）

2. **OWUI 数据持久化**
   - 导出容器内数据 625MB 到 `D:\docker\open-webui\data`
   - 修改 docker-compose.yml：命名卷 → 绑定挂载 `./data`
   - 重建容器，验证数据完整（用户/聊天/RAG文档）

3. **OWUI IP 硬编码改造**
   - 4 个环境变量从 `192.168.1.8` 改为 `host.docker.internal`
   - OLLAMA_BASE_URLS、RAG_OLLAMA_BASE_URL、SEARXNG_QUERY_URL、AUDIO_STT_OPENAI_API_BASE_URL
   - 验证全部连通：ollama 200、SearXNG 200、STT 404（服务通但路径不存在，正常）
   - compose 备份：`docker-compose.yml.bak-20260825-persist`

4. **STT 服务确认**
   - 位置：`D:\whisper-cpp\stt_adapter.py`
   - 类型：whisper.cpp Python 适配器，OpenAI 兼容 API
   - 端口：10303

5. **产品化路线图文档**
   - 新建 `docs/productization-roadmap.md`
   - 三阶段：可复现 → 一键部署 → 一键升级

6. ~~**新加坡 exit node 上线**~~ ❌ 已下线（2026-08-26）
   - ~~Vultr 新加坡，Ubuntu 24.04，公网 IP 149.28.134.107~~
   - ~~Tailscale IP 100.103.131.14，主机名 ai-exit-sg~~
   - ~~延迟 ~71ms（P2P 直连），比东京 ai-exit-jp（~280ms）快 3-4 倍~~
   - ~~IP 转发已开启，可作为 exit node 使用~~

7. **垃圾清理**
   - VPS：删除 ollama.tar、关闭 80/8888 端口
   - 本地：删除 ollama 残留文件 ~9.6GB
   - Docker：清理悬空镜像 2.5GB

### 本次未完成 / 遇到的坑

1. **ollama 容器化失败**
   - Docker Hub 直连慢（国内）
   - 阿里云镜像源 `registry.cn-hangzhou.aliyuncs.com/ollama/ollama` 不存在
   - 东京 VPS 中转：docker save → nginx → aria2 下载，但 tar 文件损坏（缺少 manifest.json）
   - 原因：VPS 上 docker save 多次冲突，文件不完整；aria2 续传可能也有问题
   - 结论：当前保持宿主机安装，不影响使用，待后续网络好时直接 `docker pull`

2. **Docker Desktop GUI 卡死**
   - 拉取大镜像时 GUI 按钮变灰，CMD 仍可继续
   - 建议：大镜像拉取用 CMD，不用 GUI

### 下一步建议（按优先级）

1. **🔴 OWUI + ComfyUI 打通（主线任务）**
   - 目标：在 OWUI 对话中直接调用 ComfyUI 生成图片/视频/音频
   - 方案：OWUI Function Calling / 自定义工具 / API 集成
   - 价值：一个对话界面完成所有 AI 生成，产品化核心

2. **开源大赛准备**（截止 10月11日）
   - 生成效果展示素材（样例图/视频/音频）
   - 录制演示视频
   - 写作品介绍 PDF
   - 仓库改 Public

3. **开源项目审计报告未修复项**
   - README 补充模型许可证说明（Flux.1 dev 非商用等）
   - 验证 Docker Compose 模板可用性
   - 补充 CONTRIBUTING.md / CHANGELOG.md
   - 添加单元测试 / 集成测试

4. ~~**ollama 容器化**（待网络好时）~~ ✅ 已完成（2026-08-26，东京 VPS 中转）
   - ~~用新加坡 exit node 直接 `docker pull ollama/ollama:latest`~~（新加坡已于 08-26 下线）
   - 启动容器：--gpus all、-p 11434:11434、-v D:\ollama\models:/root/.ollama/models
   - 停宿主机 ollama 进程，验证 OWUI 连通

5. **导出 ComfyUI 镜像 tar**（新机器部署用）
   - `docker save -o comfyui-h3-v2.tar comfyui-h3:v2`（约 48GB）

6. **统一 docker-compose.yml**（产品化阶段1）
   - 把 ComfyUI、OWUI、SearXNG、ollama（容器化后）、STT（容器化后）纳入一个 compose

### 关键文件变更

| 文件 | 变更 |
|------|------|
| `AGENTS.md` | 新建，项目记忆与操作指南 |
| `docs/productization-roadmap.md` | 新建，产品化三阶段路线图 |
| `docs/deployment-replication-checklist.md` | 更新，标记 OWUI 完成项、添加新加坡 exit node、更新开源大赛状态 |
| `docs/troubleshooting.md` | 更新，添加 SageAttention 启用方式、xformers 不兼容 |
| `README.md` | 更新，项目结构添加 AGENTS.md |
| `D:\docker\open-webui\docker-compose.yml` | 修改，绑定挂载 + host.docker.internal |
| `D:\docker\open-webui\docker-compose.yml.bak-20260825-persist` | 新建，修改前备份 |

### 环境变量

- ~~`VULTR_ROOT_SIG`：新加坡 VPS root 密码（SSH 密钥失效时用）~~ ❌ 新加坡 VPS 已于 2026-08-26 下线，此环境变量已失效
- `GITHUB_ACCESS_TOKEN`：GitHub Personal Token（已存入用户变量）
