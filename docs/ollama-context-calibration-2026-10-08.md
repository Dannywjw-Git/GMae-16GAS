# Qwen9B 有限上下文配置真实校准

2026-10-08，本机 RTX 4060 Ti（16,380 MiB、驱动 591.86），现有 Ollama 0.33.0、Qwen3.5:9b / 9.7B / Q4_K_M。API 模型摘要为 `9eda36c3f67d67f9c251f8672458315af91909fd38e53b7723a48cbbe2607cf7`，安装清单大小 6,594,463,106 字节。摘要来自后端清单，尚未独立校验模型 blob 内容，不能称为独立权重认证。

## 过程与边界

实际生成采集版本 `f6c2c64baa4715977c85f2f3017551208582de6a`。采集器持有 GPU 0 同账户跨进程所有权，使用原任务/资源账本，通过受管 ComfyUI 释放及 fresh 低 torch/物理空闲核验后才生成。第一次从已驻留 SDXL 切换；第二次在 Qwen 受管卸载、后端空列表及物理回收核验后执行。两次后均完成受管 Qwen 释放，释放报告分别记录命令结果、模型列表与 GPU 读数，资源账本无未确认操作。

首次校准使用仅在采集进程内有效的文件大小 ×1.2 +2,560 MiB 保守规划估计，另保留 2,560 MiB 安全余量，明确未实测。没有修改生产注册表，没有将历史 `vram_verified` 标志视为测量证据，也没有以校准结果自动授权生产准入。上下文仅允许 2,048 / 8,192；固定提示词、seed 20261008、temperature 0、think false、num_predict 32，输出正文仅存摘要。

## 观测结果

| 上下文配置 | 提示/输出 token | 样本数 | 整卡保守峰值 MiB | 后端驻留字节 | 请求完成秒 |
|---|---|---|---|---|---|
| 2,048 | 24 / 32 | 159 | 8,030 | 5,420,875,774 | 40.641 |
| 8,192 | 24 / 32 | 173 | 8,310 | 5,729,167,604 | 46.578 |

两次 done=true、done_reason=length，实际 /api/ps 的模型摘要和 context_length 匹配，采样错误为零。整卡保守计数取 max(used, total-free)，包含桌面后台和驱动保留；驻留字节来自 Ollama，不能替代峰值。计时包括协调准入及后端请求，不包含准备释放。每个配置仅一次；完整自动化 578 项通过（16.15 秒），测试夹具不作为真实性能证据。

这是短提示词、有限生成的上下文配置校准，**没有填满 2K/8K 的提示窗口，不是长提示词、长期生成、批量或最坏峰值证明**。两次差异包含未控制的桌面后台波动，不能直接解释为 KV cache 增长或性能退化。没有实际并行大模型、GPU embedding、成本收益或通用 OOM 保证。生成同时已卸载 SDXL，并未完成整个混合队列吞吐比较。普通生产 Qwen 准入及统一 LLM 持久任务队列尚未完成。

## 复现与审查

[原始数据、释放记录、采集源副本与 SHA256 索引](evidence/ollama-context-20261008/manifest.json)。公开 raw 的临时 reservation token 已改为摘要，其余采样/结果不变。release 与分析源码以索引中归档字节为准；生成源码另绑定上述 commit。

在已安装相同服务/模型、原账本无未知工作且获得同账户 GPU 所有权的机器上，使用仓库虚拟环境运行：

```text
python scripts/measure_ollama_workload.py --ctx 2048 --output <新的raw路径>
python scripts/measure_ollama_release.py --output <新的释放路径>
python scripts/measure_ollama_workload.py --ctx 8192 --output <新的raw路径>
python scripts/measure_ollama_release.py --output <新的释放路径>
python scripts/analyze_ollama_calibration.py <raw路径>
```

未知响应保留资源账本，不重放；输出拒绝覆盖。不要使用另一数据库绕开持有者/未确认操作。分析器验证完成、身份、上下文、计数和时间连续性，不证明数据本身可信或满上下文安全。

请独立 Chat Agent 复核：显式 bootstrap 的范围与生产隔离、短提示词限制、API 摘要与内容摘要差异、释放三层证据、原始峰值口径。下一步补长提示词实测与独立内容/环境身份，绑定完整请求参数形成正式 Ollama Profile，再进入 SDXL↔Qwen 持久混合任务对照；不继续扩展通用恢复框架。
