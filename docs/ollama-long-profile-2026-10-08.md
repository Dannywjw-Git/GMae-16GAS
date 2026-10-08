# 长提示实测与正式 Ollama Profile

2026-10-08，RTX 4060 Ti / 16,380 MiB / 驱动 591.86，Ollama 0.33.0，已安装 Qwen3.5:9b / Q4_K_M。沿用单 GPU 0、原任务/资源账本及 2.5 GiB 保留余量；先受管释放 SDXL，核验低 torch/物理空闲，再执行 Qwen，不并行常驻两个大模型。

## 独立内容与参数身份

实际模型 blob 6,594,462,816 字节，独立 SHA256 `dec52a44569a2a25341c4e4d3fee25846eed4f6f0b936278e3a3c900bb99d37c`。这与 API 模型清单摘要 `9eda36c3f67d67f9c251f8672458315af91909fd38e53b7723a48cbbe2607cf7` 分别记录，不能混用。采集时核验内容地址、哈希前后文件状态和容器身份。正式准入 fresh 核验容器及文件元数据，按实例/路径/文件状态缓存内容摘要，假设模型正常不可变部署，不抵抗刻意伪造元数据。

Profile 绑定完整请求（包括提示词、seed、think、输出上限、上下文、keep_alive）及 GPU UUID 摘要/容量/驱动、容器、模型配置摘要、blob 内容和文件身份、Ollama 版本及清单摘要。改变提示词或参数不能复用；真实采集缺少 GPU 身份的首个长 2K 试验仅作校准观察，不能导入正式 Profile。8K 试验补齐 GPU 前后身份。重建容器或模型/环境变化需要重新校准。

## 实测与正式执行

| 条件 | 输入/输出 token | 样本 | 整卡保守峰值 MiB | 执行秒 |
|---|---|---|---|---|
| 长 2K 校准 | 1,574 / 22 | 147 | 8,018 | 37.922 |
| 长 8K 校准 | 6,182 / 24 | 152 | 8,321 | 39.250 |
| 相同 8K 请求普通测量准入 | 6,182 / 24 | 343 | 8,319 | 88.734 |

全部 done=true、done_reason=stop、模型摘要和实际上下文匹配，零采样错误。num_predict=32 是上限；正常 EOS 可提前结束，曾因分析器误要求输出恰为32而拒绝安装，已按真实语义修复并增加测试，未重写原始 token 结果。整卡计数为 max(used,total-free)，包含后台与驱动保留。

正式执行使用校准峰值 +512 MiB，即 **8,833 MiB**，保留额外 2,560 MiB 安全空间，通过正常协调器/预算/资源日志；没有替换注册表、HTTP 自报峰值或绕过未校准上下文。已实测精确 Profile 允许相应上下文预算；无测量覆盖的历史上下文仍拒绝。禁止证据跨服务或与 OperationSpec 的模型/上下文/操作不一致授权。

Profile 仅安装于独立可选 `data/profiles-ollama-long` / `data/profiles-ollama-public`，未修改默认配置。正式执行证据引用的公开校准 raw SHA256 为 `169728e2b4b790d23a6a800add4d70bfffbab4e6ead8fedea3a2707b59eb6a51`，公开字节与实际安装字节一致。公开执行记录中的临时 token 已改为摘要。三次之后均单独保存受管释放命令、后端空模型列表与 fresh GPU 回收，资源账本无未确认工作。

正式执行时间包含首次独立内容核验、准入及请求完成；校准时间从准备完成后计协调与请求，不含前置内容哈希。两种口径不能用来宣称速度对比。正式请求后端 total_duration 36.755 秒，不能与88.734秒混淆。试验期间有少量 CPU 自动化检查；CPU/磁盘/桌面后台未隔离。

## 证据和复现

[完整 raw、三份释放记录、独立汇总、采集源版本与摘要索引](evidence/ollama-long-profile-20261008/manifest.json)。长2K采集提交 `1605095`，长8K `5d40103`，普通测量准入 `39c6672`，完整哈希见索引；后续 verifier 与拒绝条件细化单独提交，源码副本摘要保留。自动化结果见 PROJECT_STATUS/HANDOFF 与 PR 精确 HEAD 检查。

```text
python scripts/measure_ollama_workload.py --ctx 8192 --prompt-kind long --output <新的校准raw>
python scripts/measure_ollama_release.py --output <新的释放raw>
python scripts/install_workload_profile.py --raw <已评审校准raw> --destination <独立Profile目录>
python scripts/run_profiled_ollama_trial.py --raw <相同校准raw> --profile-dir <独立Profile目录> --output <新的执行raw>
python scripts/measure_ollama_release.py --output <新的释放raw>
```

仅在现有模型、相同已核验部署、原账本无未知工作条件下执行；任何未知响应保留记录且不重放。安装显式拒绝覆盖，输出路径须为新文件。

## 尚未证明和独立评审

仅一个 GPU、两个有限合成提示和一次正式请求，各条件单次。6,182 token 并非填满8K，未覆盖完整窗口、长输出、批量、任意对话、最坏峰值或通用 OOM 保证。只证明精确请求的正式证据准入，**统一持久 LLM 任务队列、LLM 取消/重启恢复和混合吞吐对照仍未完成**。不能把精确 Profile 宣称为按长度泛化的模型预测器。

请 Chat Agent 复核：请求与 OperationSpec 一致性、证据固定和修改拒绝、API 清单与独立内容身份、缓存假设、整卡预算及双大模型互斥、实际普通准入记录和释放三层证据。下一步接入持久 LLM 任务及 SDXL↔Qwen 混合安全切换，补真实故障/直接后端基线，并收敛安装、Release 与演示交付。
