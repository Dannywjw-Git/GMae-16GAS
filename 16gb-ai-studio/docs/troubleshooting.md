# 踩坑全集（本地 AI 生成环境）

> 所有坑均有实测来源。遇到同症状直接查表。

---

## 一、显存 / GPU（最高危，踩错=死机）

| 坑 | 症状 | 修复 |
|---|---|---|
| 🔴 显存打满=死机 | num_ctx 32K → KV cache 爆 → 模型加载失败 → 重试循环 → 内存泄漏 → 死机 | 永远留余量；num_ctx≤16384；embed 走 CPU；监控进程内存 |
| 9B Modelfile 埋雷 | 任何不带 num_ctx 的请求默认 64K → 爆显存 | `ollama show <model> --modelfile` 查；Modelfile 里固定 num_ctx=16384 |
| "已强制CPU"是错觉 | 代码 `DEVICE="cuda" if torch.cuda.is_available()` 自动选GPU | 必须 `CUDA_VISIBLE_DEVICES=-1`（空串""无效，torch读到None仍用GPU） |
| Fooocus 启动即预加载 | 显存 12.5G 打满、对话态余量不足 | 用毕 `docker stop fooocus`，用时再 start |
| SDXL+9B 共存险 | 峰值 15.9GB 出图成功，余量 0.5G | 维持"出图前释放 9B"纪律 |
| gpu_release 漏模型 | 小模型（0.6B）1.6G 叠加超 16G 顶格 | 模型列表必须包含所有已加载模型 |
| ComfyUI 默认模板 SD1.5 | 报 `v1-5-pruned.ckpt not in [...]` | 下拉改 `sd_xl_base_1.0.safetensors` + SDXL 参数 |

---

## 二、Ollama（反复假死顽疾）

| 坑 | 症状 | 修复 |
|---|---|---|
| **假死特征** | 端口 LISTENING 但 API 请求超时 + CLOSE_WAIT 堆积（不是慢！） | kill 全部 → 按启动脚本重启 → 刷新模型列表 |
| `ollama ps` 拉起 GUI | serve 未起时 CLI 自动拉起 app，且可能失败 | 诊断别用 CLI 试探；用 `curl /api/version` + 检查 serve 进程 |
| **think 参数层级** | `options.think=false` 无效 → 模型纯思考、content 空 | `think` 放**请求顶层**，不是 options 里 |
| 双 serve 竞态 | 双进程曾误删模型 | 单 serve 铁律；自启唯一源 |
| OWUI 残注册表 | "Model not found"（Ollama 宕机时重建 OWUI 导致） | **重建 OWUI 前先确认 Ollama 已响应**；已重建则调一次 /api/models 刷新 |
| server.log 停更 | serve 无日志活动 = 异常信号 | 查进程时间线 + 环境变量（MODELS 路径是否正确） |
| `ollama stop` 多参数 | 一次只收1个模型名，多参数报错且只停 fallback 的第一个 | 逐个 stop，每个核对 rc |

---

## 三、Windows / 环境

| 坑 | 症状 | 修复 |
|---|---|---|
| git bash `taskkill //F` | 报"无效参数 - '//F'" | 用 PowerShell `Stop-Process -Name xxx -Force` |
| PowerShell 禁 .ps1 | 执行策略拦截 | 一律 `-ExecutionPolicy Bypass -File` |
| 长驻服务进程树回收 | Start-Process 起的服务随会话死 | **schtasks 一次性任务**：`/create /run /delete` |
| Windows curl 写 /dev/null | 下载探测报错 EXIT 23 | 路径用 `D:/` 格式，别用 /dev/null |
| PowerShell `%` 通配符 | `like '%python%'` 被安全扫描误判 | 用 `.Contains('python')` |
| 中文/emoji 脚本编码 | .ps1/.bat 中文乱码或执行错 | UTF-8 with BOM |
| PowerShell `>` 重定向 | 默认 UTF-16，文件乱码 | 用 `[System.IO.File]::WriteAllText(path, content, [System.Text.Encoding]::UTF8)` |

---

## 四、网络 / 镜像 / 下载（国内环境）

| 坑 | 症状 | 修复 |
|---|---|---|
| `host.docker.internal` 早期版本抖动 | 旧版 Docker Desktop 容器内连宿主机 60% 失败率 | 当前 Docker Desktop 29.7+ 已稳定，OWUI 等服务已改用 host.docker.internal 并验证连通；如遇连通问题可回退局域网 IP 直连（如 192.168.1.8） |
| GitHub git 协议镜像失效 | ls-remote 通但 fetch 拿旧数据 | **gh.ddlc.top zip 下载**（唯一可用代理） |
| hf-mirror 大文件单连必断 | 超大文件 curl 中途断 | 魔搭直连（13-18MB/s 稳定）或分段多线程 |
| 清华 PyPI 缺最新版 | 特定版本包没有 | **阿里云源** `mirrors.aliyun.com/pypi/simple/` |
| pip 遇版本错误中止 | requirements 里一个包失败 → 后续全没装 | 修好卡住的包后**必须重跑完整 requirements** |
| **🔴 容器内 pip 下 nvidia-* 包极慢** | pypi.nvidia.com 容器内仅几百 KB/s，cudnn/cublas 等 200-400MB 大包反复断、卡死 | **宿主机 curl 批量下载**（几十 MB/s）→ `docker cp` 进容器 → `pip install --find-links /tmp/`。禁止在容器内直接 pip install 大的 nvidia 包 |
| **--find-links 对部分包不生效** | nvidia-cusparse/cusolver 已在 /tmp/，pip 仍从网络下 | 版本通配符（`==12.6.3.3.*`）匹配问题。容忍：让它下（仅这两个包慢），或重命名 wheel 为 pip 期望的精确文件名 |
| **pip cache 为空** | 容器内 `pip cache list` 无输出，重复下载 | ai-dock 镜像可能禁用了缓存。不要依赖 cache，所有大包必须本地 wheel 安装 |
| **nohup 后台 pip 输出缓冲** | `tail -f` 日志长时间不更新，误以为卡死 | 日志被块缓冲。判断真实进度：`ls -lh /tmp/pip-unpack-*/*.whl` 看临时文件大小是否增长 |
| Tailscale 免费版不解析子域名 | `xxx.ts.net` nslookup 不存在 | 走路径路由 / 直连端口 |
| n8n/Immich 前端绝对根路径 | 强行子路径路由白屏 | 端口直连（WireGuard/Tailscale 等效安全） |

---

## 五、Docker / ComfyUI 容器

| 坑 | 症状 | 修复 |
|---|---|---|
| **docker cp 破坏 models 软链** | 升级后模型列表空（unet_name not in []） | `rm -rf /opt/ComfyUI/models && ln -s /workspace/models /opt/ComfyUI/models` |
| **docker cp 破坏 output 权限** | SaveAudio `[Errno 13] PermissionError` | `mkdir + chown -R user:ai-dock /opt/ComfyUI/output` |
| ai-dock 输出宿主不同步 | 容器出图但宿主看不到 | `docker cp comfyui:/opt/ComfyUI/output/xxx ./` |
| torch 太旧 | `infer_schema kernel_size has unsupported type` | 升级 torch≥2.6 |
| **🔴 ComfyUI 0.33 需 torch 2.13** | 启动 FATAL，旧 torch 2.4.1 直接不兼容 | 必须升 torch 2.13.0+cu130（见下方 torch 升级标准流程） |
| **🔴 docker restart 清空 /tmp** | 之前 cp 进容器的 wheel 文件全没了 | /tmp 是临时文件系统，重启即清。wheel 放宿主机 _installers/ 目录，需要时重新 cp |
| **🔴 docker compose up -d 重建容器** | 容器内所有改动（torch升级、ComfyUI代码、自定义节点）全部丢失，回退到镜像默认版 | **禁用 `docker compose up -d comfyui`**。改容器用 `docker exec`/`docker cp`/`docker restart`。改动完成后**必须 `docker commit` 固化** |
| **容器内改动未固化** | 下次重建又回退 | `docker commit comfyui comfyui-h3:v1` → `docker save -o comfyui-h3-v1.tar comfyui-h3:v1` |
| xformers 版本不匹配 | pip 报 xformers 需特定 torch | **可忽略**（ComfyUI graceful fallback） |
| ComfyUI 0.33 缺依赖 | `ModuleNotFoundError: sqlalchemy/comfy_aimdo/blake3` | 容器内 venv 执行 `pip install -r requirements.txt` |
| 镜像停更 | ai-dock digest 23个月不变 | 容器内手动升级 ComfyUI 代码 |
| **SageAttention 启用方式** | 设环境变量 `SAGEATTN=1` 无效，ComfyUI 不识别 | 必须用命令行参数 `--use-sage-attention`，写入 `/etc/comfyui_args.conf`，重启生效。验证：日志出现 `Using sage attention` |
| **xformers 版本不兼容** | torch 2.13 与 xformers 0.0.28 不匹配，报 warning | 可忽略，ComfyUI fallback 到 pytorch attention / SageAttention。如需彻底消除可 `pip uninstall xformers` |

### torch 升级标准流程（ComfyUI 0.33 必需）

> 容器内 pip 下 nvidia-* 包极慢，**必须用宿主机下载 + cp 进容器**。

```bash
# 1. 宿主机批量下载所有 wheel（_installers/ 目录）
#    torch + triton + torchvision + torchaudio 从 download.pytorch.org
#    16个 nvidia-* 包从 pypi.nvidia.com
#    （URL 清单见 minimax-h3-deployment.md）

# 2. cp 进容器
docker cp _installers/*.whl comfyui:/tmp/

# 3. 容器内安装（全部本地 wheel，不走网络）
docker exec comfyui /opt/environments/python/comfyui/bin/pip install \
  /tmp/torch-2.13.0+cu130-*.whl \
  /tmp/torchvision-0.28.0+cu130-*.whl \
  /tmp/torchaudio-2.11.0+cu130-*.whl \
  /tmp/triton-3.7.1-*.whl \
  --find-links /tmp/

# 4. 验证
docker exec comfyui /opt/environments/python/comfyui/bin/python -c "import torch; print(torch.__version__)"

# 5. 装 ComfyUI requirements
docker exec comfyui /opt/environments/python/comfyui/bin/pip install -r /opt/ComfyUI/requirements.txt

# 6. 启动验证 → 出片验证 → docker commit 固化
```

---

## 六、模型生成特定坑

### Music 3
| 坑 | 症状 | 修复 |
|---|---|---|
| CLIP/VAE 配错 | `shape invalid` 报错 | CLIPLoader 必须用 `minimax_music3_text_encoder_*` + `type=minimax`；VAELoader 必须用 `minimax_music3_dav` |
| 时长不同步 | 生成截断或报错 | TextEncode 的 `max_duration` 与 EmptyLatentAudio 的 `seconds` 必须一致 |
| 长时长断音 | 90s+ 在 16G 卡有断音 | 60s 最稳；歌词量与时长强相关，6段歌词需 150s+ |
| BPM 提速无效 | 改 BPM 不能让歌词唱完 | Music3 是一次性生成，BPM 调整救不了歌词长度 |

### Flux
| 坑 | 症状 | 修复 |
|---|---|---|
| Q8 压垮引擎 | 生成失败/显存爆 | 16G 卡用 Q5_K_S，禁用 Q8 |
| cfg 不对 | 画面过饱和/发灰 | Flux 用 cfg=1（蒸馏模型），不是 7 |
| 采样器不对 | 画质差 | euler + simple scheduler，20步 |

### H3
| 坑 | 症状 | 修复 |
|---|---|---|
| TE-Speed 失真 | 文字乱码、手/嘴崩坏 | 禁用 TE-Speed，只用 SageAttention |
| 忘挂 Turbo LoRA | 速度慢一倍 | 必须加 `LoraLoaderModelOnly(minimax_h3_fl2va_4step_lora)` |
| 分辨率超 768p | 生成异常 | 开源权重封顶 768p，别强求 2K/4K |

---

## 七、OWUI / 知识库

| 坑 | 症状 | 修复 |
|---|---|---|
| config 表裸文本 | retrieval/config 500、页面空白 | config 表字符串值必须是 JSON 格式（`"value"` 带引号） |
| 升级后 custom.js 失效 | 指标显示不出来 | UI 重设计后 DOM 变了，需重写选择器 |
| Filter inlet 签名变 | 升级后 Filter 报错 | 0.11+ 签名 `(self, body, __user__)` 无 request |
| native FC 下 KB 不注入 | 知识库附加了但模型不用 | 小模型用 legacy 模式（自动附加），或用 Filter 兜底 |
| Ollama 默认 ctx 2048 | RAG 检索结果被截断 | 设 `OLLAMA_CONTEXT_LENGTH=8192` 或更高 |

---

*持续更新。遇到新坑请补充到对应分类。*
