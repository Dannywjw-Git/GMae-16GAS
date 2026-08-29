# 家庭智能中枢 · 运维变更台账

> **用途**：记录每次对 OWUI/COMFY/容器/配置/脚本的改动（改了什么、为什么、何时、谁），排障时先看本台账，避免"这是谁改的、为什么这样"的考古。
> **规则**：每次变更记一行（追加在末尾）；重大变更（动库/动容器配置/升级）用 `###` 小标题详述。时间一律北京时间。
> **关联**：排障结论/新机制回写 `D:\dsh\skills\home-hub-owui-ops` 与 `home-hub-comfy-ops`。

## 2026-08

### 2026-08-27 豆包：东京旧 VPS（ai-exit-jp）正式下线 + 文档批量更新
- **背景**：东京旧 VPS（ai-exit-jp，207.148.107.141 / Tailscale 100.81.128.51，Vultr 东京 23G SSD）正式下线。该服务器曾作为 exit node + 文件中转，延迟 ~280ms。
- **当前状态**：Tailscale 设备列表中已无 ai-exit-jp。当前唯一 exit node 为东京新 ai-registry-jp（167.179.66.179 / 100.126.118.93，52G SSD，Split Tunnel + Docker Registry:5000，2026-08-26 上线）。
- **文档更新**：批量更新所有引用东京旧服务器的文件（共 11 个非归档文件）——
  - 核心记忆：`AGENTS.md`、`工作交接.md`、`16gb-ai-studio/AGENTS.md`、`docs/家庭智能中枢建设方案_总纲_v3.0.md`
  - 项目文档：`docs/README.md`、`docs/WorkBuddy自定义模型配置指南.md`、`16gb-ai-studio/docs/项目进度跟踪.md`、`16gb-ai-studio/docs/deployment-replication-checklist.md`、`16gb-ai-studio/docs/handover.md`
  - 历史日志（`docs/游戏串流子项目.md`、`ops-changelog.md` 旧条目）保留原样，记录的是当时的历史操作
- **脚本**：`scripts/vps_jp_*.py` 等针对旧服务器的脚本标记为 DEPRECATED

### 2026-08-26 豆包：新加坡 VPS 下线 + 文档配置批量更新
- **背景**：新加坡 VPS（ai-exit-sg，149.28.134.107 / Tailscale 100.103.131.14）已下线，用户手动从 Tailscale 管理后台移除该设备。
- **当前状态**：Tailscale 设备列表中已无 ai-exit-sg，唯一 exit node 为东京 ai-exit-jp（100.81.128.51 / 207.148.107.141，~280ms）。
- **文档更新**：批量更新所有引用新加坡服务器的文件——
  - 脚本（5个）：`tailscale_exitnode.py`、`tailscale_up.py`、`enable_forward.py`、`vps_init.py` 加 DEPRECATED 注释；`exitnode_speedtest.py` 移除新加坡测速项
  - `docs/README.md`：Exit Node 表格，新加坡标记已下线，东京改为唯一可用
  - `16gb-ai-studio/AGENTS.md`：Tailscale 表格 + VPS 操作部分更新
  - `docs/家庭智能中枢建设方案_总纲_v3.0.md`：成本表（双VPS→单VPS）、进度记录、待办、版本说明
  - `工作交接.md`、`16gb-ai-studio/docs/项目进度跟踪.md`、`开发日志.md`、`handover.md`：历史记录加已下线标注
- **影响**：下载 Docker 镜像/大文件时需使用东京 exit node（延迟较高但可用）；ollama 容器化已完成（东京中转），不受影响。

### 2026-08-26 豆包：调度中心 v2 修复（对齐显存管理最高指南 + ollama 容器化适配）
- **问题1 修复**：README 与代码场景数不一致 → 新增 `h3` 场景（MiniMax H3 文生/图生视频，走 ComfyUI 独占全卡），现共 6 场景：dialogue/comfy/h3/fooocus/music/game
- **问题2 修复**：BIG_MODELS 硬编码遗漏 27B → 扩展为 4 个模型（9b/0.6b/27b-rvn/27b-iq3xxs），且 ollama_stop_all 优先从 `/api/ps` 动态获取当前已加载模型列表，硬编码仅兜底
- **问题3 修复**：ollama 容器化后宿主机 CLI 失效 → 所有 ollama CLI 调用（stop/run）改为 `docker exec ollama ollama ...`，combo none 测试通过
- **问题4 修复**：切换场景前无显存预检 → scene_switch 开头新增 M1 铁律检查：若空闲显存 <4GB 自动先执行 gpu_release.ps1，防止打满死机
- **其他**：默认 HOST 从 127.0.0.1 改为 0.0.0.0（支持内网/Tailscale 访问）；启动警告更新为无 Token 时提示安全风险；LAST_SCENE 逻辑支持 h3 场景
- **依据**：《显存管理最高指南》v1.3 — M1 铁律（出图/游戏前必须释放到 <4G）、R2（27B/Flux 独占全卡）、§三 六大稳态

### 2026-08-26 豆包：ollama 容器化完成（东京 VPS 中转下载 + 分割文件法）
- **背景**：ollama 之前是宿主机安装，容器化是产品化统一部署的必要步骤。Docker Hub 直连国内慢、阿里云镜像源不存在、~~新加坡 VPS 中转带宽有限（~200KB/s）~~（新加坡已于 08-26 下线）。
- **最终方案**：东京 VPS（ai-exit-jp，207.148.107.141）装 nginx + docker pull ollama/ollama:latest（8.43GB）→ docker save 成 tar（3.2GB）→ split -b 100M 分割成 33 块 → 本地 aria2 批量下载（每文件单线程 -x1 -s1，并行 -j4，东京公网 IP）→ 剩余不完整文件用 PowerShell HttpWebRequest 带 Range 断点续传循环重试 → copy /b 合并 → tar -tf 验证 manifest.json → docker load。
- **关键坑**：① aria2 多线程单文件下载（-x16 -s16）会内容损坏（大小对但缺 manifest.json），必须用分割文件法 + 每文件单线程；② 东京 nginx 默认不支持 Range 请求，aria2 -c 续传无效，需用 HttpWebRequest 手动 AddRange；③ 本地到海外 HTTP 连接不稳定，大文件单线程下载易中途断开，分割成 100MB 小块 + 批量并行 + 断点续传是最稳方案；④ 最后一个分块 part_32 只有 24MB（3223-32*100），属正常。
- **容器配置**：`docker run -d --name ollama --restart unless-stopped -p 11434:11434 --gpus all -v D:\ollama\models:/root/.ollama/models ollama/ollama:latest`
- **验证**：容器内 nvidia-smi 正常（RTX 4060 Ti 16GB）、模型列表 API 返回 7 个模型（qwen3.8 27b、qwen3.5 9b、qwen3 0.6b、bge-m3 等）、qwen3:0.6b 推理 13.5 token/s、OWUI 容器内 curl host.docker.internal:11434 连通。
- **备份**：ollama.tar 保留在 `D:\Users\Danny\Documents\家庭智能中枢\_installers\ollama.tar`（3.2GB），新机器部署可直接 docker load；分块目录 `_installers\ollama_parts\` 可删除。
- **遗留**：ollama 尚未纳入统一 docker-compose.yml（产品化阶段 1 再做）；宿主机 ollama 进程已停止，如需回滚可重新启动。

### 2026-08-25 豆包：ComfyUI 恢复 + OWUI 持久化/IP改造 + 新加坡 exit node + 开源项目
- **ComfyUI 恢复**：torch 2.13.0+cu130 安装（宿主机 curl 批量下载 20 个 wheel 共 2.6GB → cp 进容器 → --find-links 安装）、ComfyUI 0.33.0 启动、SageAttention 安装并启用（必须用 `--use-sage-attention` 参数写 /etc/comfyui_args.conf，环境变量 SAGEATTN=1 无效）、H3 T2V 出片验证成功、docker commit 固化 comfyui-h3:v1（基础）和 comfyui-h3:v2（含 SageAttention，48.2GB）
- **OWUI 数据持久化**：导出容器内数据 625MB 到 D:\docker\open-webui\data，修改 docker-compose.yml 从命名卷改为绑定挂载 ./data，重建容器验证数据完整。备份：docker-compose.yml.bak-20260825-persist
- **OWUI IP 硬编码改造**：4 个环境变量从 192.168.1.8 改为 host.docker.internal（OLLAMA_BASE_URLS、RAG_OLLAMA_BASE_URL、SEARXNG_QUERY_URL、AUDIO_STT_OPENAI_API_BASE_URL），验证 ollama 200、SearXNG 200、STT 404（服务通）
- **STT 服务确认**：D:\whisper-cpp\stt_adapter.py（whisper.cpp Python 适配器，OpenAI 兼容 API，端口 10303）
- **新加坡 exit node 上线**：Vultr 新加坡 Ubuntu 24.04，公网 149.28.134.107，Tailscale 100.103.131.14，主机名 ai-exit-sg，延迟 ~71ms（P2P），比东京 ai-exit-jp（~280ms）快 3-4 倍。IP 转发已开启
- **16gb-ai-studio 开源项目创建**：路径D（开源社区+技术服务），GitHub Dannywjw-Git/Local-AI-Studio + Gitee dnnywang/local-ai-studio（均私有），含 AGENTS.md（项目记忆）、docs/handover.md（交接）、docs/productization-roadmap.md（产品化路线图）。OS2026 大赛个人参赛，截止 10月11日
- **ollama 容器化尝试失败**：Docker Hub 国内慢、阿里云镜像源不存在、VPS 中转 docker save 文件损坏（缺少 manifest.json），当前保持宿主机安装，不影响使用
- **垃圾清理**：VPS 删除 ollama.tar + 关 80/8888、本地删 ollama 残留 9.6GB、Docker 清悬空镜像 2.5GB
- **关键禁令重申**：禁 docker compose up -d comfyui（会清空容器内改动），改容器用 docker exec/cp/restart，完成后必须 docker commit

### 2026-08-25 DSH：调研 MiniMax H3 替代 LTX（16G 视频模型选型，主公定"以后装 full"）
- 起因：LTX-2.3 16G 实测质量差（低分辨率/跳帧/逻辑诡异），主公弃用，问社区有无 16G 实测好的视频模型
- 调研结论：**MiniMax H3** 是 16G 卡最佳选择——community QA 基准（2026-08，RTX 4060 Ti 16GB 同卡实测）：
  - full 版"全清晰、文字正确"，640×640·5s ~300s（预热后），原生音视频同步（自带音频=MV 神器）
  - pruned 版 864×480·5s ~109s，细节有"别扭感"（剪枝固有损失，真人场景不可用）
  - 与 LTX 对比：画质/分辨率/音视频同步全面胜出
- 本机状态：**H3 节点已就绪**（EmptyMiniMaxH3LatentAV / MiniMaxH3ImageToVideo 等），**模型未下载**
- **主公决定（08-25）**：**以后（别的会话）安装 MiniMax H3 full 版**
- 产出：`docs/MiniMax-H3部署计划.md`（部署提纲 + 已验证配置 + 七大避坑清单 + 下载源）；QA 基准关键坑：TE-Speed 在 8 步+INT8 必失真（禁用）、SageAttention 需手动启动 ComfyUI、模型文件名去 hash、首次生成预热慢
- MV 项目状态：画面路线暂停（等 H3 full 部署）；LTX 弃用已记录

### 2026-08-25 DSH：LTX-2.3 视频模型弃用（16G 实测不足，主公决定放弃）
- 背景：主公想做 MV 画面，尝试 LTX-2.3 文生视频（显存指南登记过"三模式实测全通"）
- 实测结果：**质量差**——704×512 低分辨率、跳帧、运动逻辑诡异（路灯漂移）、人物动作畸形；这是 **16G 卡跑 LTX 量化档的物理上限**，非提示词/配置能救
- 已尝试：① 纯风景空镜（去掉人物）② 静态图 SDXL（1024×1024，质量明显好于 LTX 视频）
- **主公决定（08-25）**：**LTX 视频模型放弃**，以后留意能在 16G 跑得好的模型
- 结论教训：**16G 卡文生视频 = 质量天花板**（需高分辨率+全精度要 24G+）；要动态画面优先用"静态图 + Ken Burns"（SDXL 出图质量可靠 + ffmpeg 缓慢运动），低成本无 bug
- 产出：MV_verse1_静态图_SDXL.png（1024×1024）验证了 SDXL 静态图方案可行；LTX 工作流 MV_LTX_工作流.json 保留（模型在,可回访）
- MV 项目状态：**画面路线暂停**（等更好模型，或主公转向"照片+字幕/Ken Burns"方案）

### 2026-08-25 DSH：尝试换 DeepSeek key（未完成，主公决定不处理）
- 起因：主公想给 deepseek-v4-flash-vision-exp 换新 API Key
- 探索：DSH 读 key 用 `launchEnvironmentOf`（启动环境快照），非实时 process.env；默认走 `DEEPSEEK_API_KEY`
- 尝试：settings.yaml 加 `apiKeyEnv: DEEPSEEK_DSH_API`（用户级新变量 sk-dde...）；但 DSH Web **仍需彻底干净重启**才能让启动快照读到新变量
- **卡点**：旧 `DEEPSEEK_API_KEY`（sk-d15...）被 OWUI 等服务共用，不能删；bat 重启后 DSH 仍显示"由启动环境提供"（读的还是旧快照/key）
- **结论（主公定）**：**不再处理**——旧 key 有他用，改全局环境变量风险大于收益
- 遗留：settings.yaml 已加 `apiKeyEnv: DEEPSEEK_DSH_API`（对当前 DSH 未真正生效，因启动快照未刷新）；如需回滚可删该行（备份在 `settings.yaml.bak-20260825-deepseek-key`）
- 附带：写了桌面"拉起DSH.bat"（仅拉起）+"重启DSH.bat"（重启+让配置生效）；DSH 计划任务 `AIHomeServer-DSHWeb` 自启正常

### 2026-08-24 DSH：OWUI 排查"儿子九寨沟天气查询"（只读，无改动）
- 现象：儿子（Shawn/王笑行）08-24 07:00 问「看下九寨沟的天气情况」→ SearXNG 搜索成功（21 条结果含景区官方预报），但回答为空（assistant 节点 done=False 无 usage）
- 根因：搜索链路正常，断在"工具调用后的二次生成"环节；OWUI 容器日志 07:02:44 搜索完成后无对 11434 的请求，07:19:21 儿子点停止键 + 追问「你还没有回答我」→ 新生成成功（简略回答，基于第二次质量较差的搜索）
- 关键教训：**容器内时间戳是 UTC**（docker logs/SQLite Unix 秒/fromtimestamp 默认），须 +8 换算；`chat_message` 表是 0.11 权威消息存储（assistant 回复在 output 字段，usage 完整），`chat.chat` JSON 是前端树状态
- 产出：新建 skill `home-hub-owui-ops`（含本台账引用、排障模板、查表）

### 2026-08-24 DSH：沉淀 OWUI/COMFY 运维 skill（无系统改动）
- 新增 `D:\dsh\skills\home-hub-owui-ops\SKILL.md`：OWUI 0.11 背景知识 + webui.db 结构（chat_message 表权威）+ 症状查表（天气查询中断/token 显示/Ollama 断连）+ usage 数据链路 + Filter 函数安装 + API 速记 + 排障模板
- 新增 `D:\dsh\skills\home-hub-comfy-ops\SKILL.md`：ComfyUI 背景知识（节点/工作流/模型目录）+ 症状查表（docker cp 破坏/模型列表空/PermissionError/torch 旧）+ 升级流程 + Music 3 出歌 + 排障模板
- 新增本台账 `docs/ops-changelog.md`

### 2026-08-24 DSH：修复 OWUI"网页搜索页面空白"（searxng_language 裸文本致 retrieval 500）
- 现象：主公在 OWUI 管理面板点"联网搜索"设置页，右侧空白
- 根因：`config.web.search.searxng_language` 被写成裸文本 `zh-CN`（非 JSON），`GET /api/v1/retrieval/config` 读取时 `json.loads` 抛 `JSONDecodeError` → 500 → 前端页面渲染空白。与 08-08/08-09 的 config 表 JSON 坑同类
- 修复：停容器 → 备份（`D:\docker\open-webui\webui.db.bak-20260824-0950-searxng-lang-fix`）→ 一次性容器挂卷执行 `UPDATE config SET value='"zh-CN"'`（json.dumps）→ 起容器 → 验证：新日志零 500、retrieval/config 不再崩溃
- 排查附带发现：`api_key_family.txt` 里 admin key 已过期（401）；WorkbuddyAPI key 权限不足不能读 retrieval/config（401 属正常权限拒绝）
- 教训：config 表裸文本坑不只影响 model/UI 配置，也会让 retrieval/web 搜索页面 500；检查脚本判断"JSON 合法性"时 int/float 裸值合法（SQLAlchemy 自动处理），只有字符串裸文本才真炸

### 2026-08-24 主公 + DSH：AI 原创音乐项目（MiniMax Music 3 · ComfyUI）完成
- **成果**：定稿 `outputs/MyMusic/MySong_天空之城_倾诉版_定稿_2026-08-24.mp3`（V-90324，90 秒，中文流行抒情·女声·忧伤倾诉·钢琴主导）
- **迭代历程**：8+ 版（30s→60s→90s→120s 多轮），关键迭代：模型三件套配错修复（CLIP/VAE 误用 SDXL → shape invalid）、BPM 提速试验（75 失败）、时长权衡（歌词完整 vs 断音取舍）
- **关键经验（已沉淀）**：① Music 3 是"一次性生成"不可局部修改，只能整版重生成/换 seed ② 歌词量与时长强相关，6 段歌词需 150s+，90s 会截断 ③ 长时长（90s+）在 16G 卡有断音，60s 最稳 ④ 提速 BPM 不能解决歌词唱完 ⑤ 显存潮汐实测：生成峰值 14.5G→完成自动卸载回 ~1.0G
- **配套产出**：`docs/settings-map/歌曲版本记录表.md`（版本参数全存档，可复现/微调）；MyMusic 目录整理（定稿+早期版保留，9 试验版移 _旧版本试验/）
- **关联**：显存指南已更新 v1.2（Music 3 实测数据）；ComfyUI skill 已含 Music 3 搭链坑

### 2026-08-24 DSH：显存指南 + 场景调度中心数据校正（v1.2）
- 背景：原创音乐项目全程实测显存，发现旧数据过时
- **校正 1（底噪）**：空载底噪 3.1G → **1.0–1.1G**（实测 905/780/1058 MiB，Ollama 空载+ComfyUI 空闲；旧 3.1G 含当时常驻）
- **校正 2（Music 3 峰值）**：15.1G → **14.5G**（90s 版实测峰值，空闲仅 1.6G 未爆）；生成完自动卸载回底噪 ~1.0G（"用完即卸"实证）
- **校正 3（生成耗时）**：补记实测 30s≈82s / 60s≈127s / 90s≈3-5 分钟（旧"30s 歌 4-6 分钟"过保守）
- **新增（搭链坑）**：CLIPLoader 必须 minimax te + type=minimax、VAELoader 必须 dav（误用 SDXL 的报 shape invalid）、max_duration 与 seconds 同步
- 改动文件：`docs/显存管理最高指南.md`（v1.2：§一底噪/§二账本/§三稳态/§5.2 细则/变更记录）+ `D:\scripts\vram-console\index.html`（5 处硬编码：底噪/对话态/ComfyUI/账本/占用总览；备份 index.html.bak-20260824-vram-update）；server.py 无硬编码无需改
- 验证：8787 服务运行中，前端刷新即生效

### 2026-08-24 DSH：生成 OWUI/ComfyUI 系统学习大纲（无系统改动）
- 新增 `docs/settings-map/学习大纲.md`：模块化学习路线
  - OWUI 8 模块（总览/连接/模型/搜索/RAG/记忆/语音/函数）——每模块=官方文档链接+家庭实例位置+实践操作
  - ComfyUI 5 模块（工作流/模型目录/输出/显存/升级）——C1-C3 今日已实操完成
  - 官方链接已核实（docs.openwebui.cn / docs.comfy.org 含中文版）
- docs/README 导航已加"学习大纲"入口

### 2026-08-24 主公：ComfyUI 教学实操（第 1-3 节，无系统改动）
- C1 工作流：读懂"瓶子.json"（SDXL 出图，KSampler steps 20 / cfg 6）
- C2 模型目录：找到 UNETLoader(gguf) 下拉 = `lux1-dev-q5_K_S.gguf`（Flux）+ `ltx-2.3...`（LTX 视频）
- C3 输出：容器 `/opt/ComfyUI/output/` 现有 4 图（今天 14:29-14:47 家人出图）+ LTX 视频/音频实验成果；澄清"另存工作流=存图纸 / 另存图片=存图 / docker cp=原始文件"
- 容器状态：教学前已停（Exited 143，10:06 正常停止），已 docker start 恢复

### 2026-08-24 主公：OWUI 搜索结果数量 3→5（教学实验）
- 改动：管理→设置→网页搜索→结果数量（`web.search.result_count`）从 3 改为 5
- 验证：问姜维"今天有什么新闻" → 回答列出 5 条（改前 3 条），效果直接可见
- 意义：主公第一次亲手改配置并观察因果；如觉得回答变长/变慢可改回 3

### 2026-08-24 DSH：建立配置地图（Settings Map，只读，无系统改动）
- 新增 `docs/settings-map/`：OWUI 配置地图 + ComfyUI 配置地图 + 快照目录
- 新增快照脚本（只读）：OWUI `snapshot_owui_config.py`（docker cp 进容器跑）、ComfyUI `snapshot_comfy.ps1` + `comfy_probe.sh`（宿主跑）
- 生成首份快照：`owui-config-snapshot-2026-08-24.md`（394 config key + 8 模型 + 2 函数 + 4 用户）、`comfy-snapshot-2026-08-24.md`（容器 Up、软链/output 健康、模型清单）
- 现状核对：ComfyUI 容器已从昨日的 Exited 恢复为 Up；模型软链、output 权限均健康
- 快照编码教训：PowerShell `>` 重定向默认 UTF-16，必须用 `[System.IO.File]::WriteAllText(..., UTF8)` 写 UTF-8 无 BOM

### 2026-08-24 DSH：语音链路诊断（诊断完成，修复挂起，主公定"以后处理"）
- 背景：主公反馈"整个对话一轮都很慢"，开始诊断语音链路
- 发现 1：语音看门狗（voice_watchdog）08-21 起未运行 → STT(:10303)/TTS(:10302) 挂掉无人拉起（只剩 whisper :10301）；已手动拉起 watchdog 恢复三件套
- 发现 2：TTS(:10302) 请求 502，但 edge-tts 直连/脚本/pythonw 跑都成功（1-1.7s）——疑为 :10302 进程实例问题（watchdog 父子成对进程），未最终定位
- 发现 3：STT(:10303) 日志"讯飞识别失败→兜底 whisper→`No module named 'numpy'`"——自研 stt_adapter 的 tts-venv 缺 numpy，讯飞主通道实际不可用
- 发现 4：OWUI 原生支持内置 whisper STT + 官方 Edge TTS 集成（openai-edge-tts 容器），引擎与现有 TTS 相同（晓晓）——中期可评估替换自研层
- 结论：语音"整轮慢"大头在姜维生成（9B ~45 tok/s），非语音引擎；TTS/STT 换方案只优化语音环节
- 状态：**挂起（主公 08-24 定"以后处理"）**。待办：① 修 stt_adapter 的 numpy 依赖 ② 定位 TTS 502 进程实例问题 ③ 评估官方 Edge TTS 集成替换自研 TTS

### 2026-08-25 DSH：沉淀 Music 3 创作配方 skill（主公选定，无系统改动）
- 起因：主公让回顾本会话，判断哪些知识值得提炼成 skill（现 5 个 skill 已覆盖容器运维/排障/显存合规）
- 选定：新建 `D:\dsh\skills\home-hub-music-3-ops\SKILL.md`（MiniMax Music 3 出歌创作配方与排障速查）
- **定位**：与 `home-hub-comfy-ops`（ComfyUI 容器运维/排障）互补，本 skill 是「创作方法论」——歌词/时长权衡、seed 复现、16G 实测参数、三件套搭链坑
- **内容**：8+ 次出歌迭代（V-90324 定稿）+ BPM75 死路试验沉淀——① 一次性生成不可局部改 ② 6 段歌词需 150s+、90s 截断、60s 最稳 ③ BPM 提速救不了歌词 ④ 生成峰值 14.5G→完自动卸回 ~1.0G ⑤ 三件套配对（CLIP=minimax te / VAE=dav）⑥ 版本纪律（seed 存档可复现）
- 关联：`docs/settings-map/歌曲版本记录表.md`（V-90324 完整参数样例）；本次仅新增 skill + 台账条目，无系统改动
- 未选项目（保留在 docs）：MiniMax H3 部署 skill（仍在 `docs/MiniMax-H3部署计划.md`）、comfy-ops 补 LTX 弃用行、DSH launchEnvironmentOf 换 key（主公已定不处理）

### 2026-08-25 DSH：部署 MiniMax H3 full，下线 LTX-2.3（主公指令）
- 结果：MiniMax H3 full 部署成功并实测出片。T2V 工作流 4 分钟产出 `outputs\h3t2v_h3_t2v_test_00001_.mp4`（H.264+AAC 有效视频音频）。
- 模型：`Comfy-Org/MiniMax-H3` 官方打包（full INT8 模型 31.7G + `qwen3vl_32b_minimax_h3_nvfp4_awq` 文本编码 14.6G + 视频 VAE 4.85G + 音频 VAE 0.56G）+ `joyfox/MiniMax-H3-Turbo` 4step LoRA 0.7G，共 ~52G 下载至 `D:\docker\comfyui\workspace\models\`。
- 工作流：核心节点（UNETLoader→LoraLoaderModelOnly→MiniMaxH3SigmaShift(shift_video=12/shift_audio=3)→BasicScheduler(4步)+KSamplerSelect(euler)+BasicGuider+SamplerCustomAdvanced）；CLIPLoader(type=minimax)；双 VAE + VAEDecode/VAEDecodeAudio + CreateVideo+SaveVideo。容器缺 MiniMaxH3LegacySampling/SageAttention/easy/FastVHSVideoSave 自定义节点，用核心节点等价替换；SageAttention 首跑未开（速度降档但可跑）。
- 显存：生成时独占 12.8–14G（08-25 实测），符合预期 ~12.5G；`POST /free` 端点在本机 0.33 异常（500），卸载需切场景或前端释放。
- LTX-2.3：4 文件（~17G）已删除；显存指南 v1.3 账本/稳态/变更记录已更新为 H3 独占态。
- 关联：`docs/MiniMax-H3部署计划.md`（状态已改为"已部署"）；`docs/显存管理最高指南.md`（v1.3）。

### 2026-08-25 DSH：暂停 ComfyUI 0.33 重装，产出交接（主公安排另一 agent 接手）
- 起因：给 H3 加 SageAttention 时 `docker compose up -d comfyui` 重建容器 → 重置回镜像默认 ComfyUI v0.2.2（torch 2.4.1），丢失之前 docker-cp 的 0.33 + H3 节点。已回退 sage 参数、修好 models 软链/output 权限、cp 入 master 源码、装齐 requirements。
- 阻塞：comfyui venv 需升 torch 2.13.0（报 `infer_schema kernel_size list[int]`，需要 torch 2.13）。本网络下载 torch 2.13(526MB)+cu13 库极不稳定（download.pytorch.org ~1MB/s 慢；阿里云 Read timeout / nvidia-cusparse 截断哈希不符），多次失败。
- 产出：`docs/MiniMax-H3部署交接_2026-08-25.md`（接手 agent 执行指南：torch 升级命令+网络建议、启动验证、界面可调工作流、docker commit 固化建议）；`h3_t2v_ui.json`（UI 图格式界面可调工作流，17 节点 18 连线已校验）；skill `home-hub-h3-ops`.
- 教训：ai-dock 的 ComfyUI 升级（docker cp + pip）不固化进镜像/卷，`docker compose up -d` 重建即丢。**恢复后必须 `docker commit comfyui <镜像>` 固化**。改容器用 docker exec/cp/restart，禁 compose up -d。

