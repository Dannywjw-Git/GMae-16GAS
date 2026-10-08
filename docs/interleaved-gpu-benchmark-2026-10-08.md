# 同进程均衡交错 GPU 对照（2026-10-08）

## 当前配置的结果

同一 RTX 4060 Ti 16GB、driver 591.86、ComfyUI 0.34.0 / torch 2.5.1+cu121、SDXL 512×512 / 8 步 / CFG 6 / 固定提示词，仅 seed 不同。正式队列、原任务账本与同账户 GPU 0 所有权贯穿整个进程。比较 GMae 保守整卡包络与显式安装、实际来源核验的驻留增量策略。

| 策略 | 实测成功 | 端到端中位数 | 范围 | 累计受管卸载调用 | 保守计数观测峰值 |
| --- | --- | ---: | --- | ---: | ---: |
| 保守 | 4 / 4 | 60.7345 秒 | 55.469–66.250 秒 | 4 | 8,907 MiB |
| 驻留增量 | 4 / 4 | 9.305 秒 | 9.047–9.563 秒 | 0 | 8,968 MiB |

这组结果证明当前已校准配置在完整驻留起点下可以减少 GMae 安全准入中的多余卸载。对照是 GMae 保守安全策略，尚未覆盖原生 ComfyUI 直接提交的同口径对照，不能据此宣称超越原生后端缓存或推广到其他 GPU/工作流。这里没有观测到降低显存峰值；8 次成功也不构成 OOM 保证。

## 预声明协议与计时

先执行 seed 57 驻留预热，完整保存 75.000 秒、292 样本及身份核验，排除在稳定组统计之外。之后固定均衡顺序 `C R R C C R R C`，每种策略 4 次，每次 fresh 快照必须证明三组件完整驻留、空闲且来源一致，再经正式队列执行。采样器缓存必须为 false；实际准入路径必须与分组策略一致；未确认工作、错误路径、采样错误或失败均停止，不自动补跑。

时间从正式入队到持久任务终态，包括准入、fresh 身份/容量查询、释放及物理回收等待（若发生）、提交和终态轮询。同进程模型摘要缓存以 fresh 容器/文件身份核验保持有效，首次摘要计算只发生在预热；不是跳过内容核验。采样期间部分离线回归/分析亦在 CPU 上执行；CPU/磁盘缓存和后台桌面没有控制，顺序不是随机化，结果仅描述这一组试验。

全部 9 次（含预热）任务 done、后端 success、采样器未缓存、0 采样错误；结束后 unfinished tasks=0、pending resource operations=0。正式计数仍使用 `max(used,total-free)`，模型体积独立参与大模型互斥。

| 序号 | 策略 | seed | 端到端秒 | 卸载调用 | 保守峰值 MiB | 样本 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 0 | resident | 57 | 75.000 | 0 | 8982 | 292 |
| 1 | conservative | 58 | 66.250 | 1 | 8894 | 255 |
| 2 | resident | 59 | 9.563 | 0 | 8957 | 38 |
| 3 | resident | 60 | 9.047 | 0 | 8957 | 36 |
| 4 | conservative | 61 | 57.719 | 1 | 8893 | 225 |
| 5 | conservative | 62 | 63.750 | 1 | 8904 | 245 |
| 6 | resident | 63 | 9.313 | 0 | 8968 | 37 |
| 7 | resident | 64 | 9.297 | 0 | 8968 | 37 |
| 8 | conservative | 65 | 55.469 | 1 | 8907 | 218 |

## 可复核交付与复现

[完整 manifest](evidence/interleaved-queue-20261008/manifest.json) 为每份 raw 固定文件名和 SHA256；[独立汇总](evidence/interleaved-queue-20261008/summary.json) 保留逐次结果和预热。两份文件 SHA256 分别为 `69ae832543577bd8da934c834152ec620bd704f47eb53c14e520a84f8b4e7b83`、`22d9206d504a1114f7a0a1f0c6fb5a3a93f3ac034bf9faf301f0f0bb7ee356bd`。raw 只将活动 token 转为摘要，没有改写计量。

实际采集源码提交 `debebe6031749c4e378c6ab3f94023fee4ff1fe0`，push CI `37739227759` success。归档 [序列采集器](evidence/interleaved-queue-20261008/run_interleaved_queue_benchmark.py) SHA `5365bf1bf116d22e8d2e8859e9970a84674dcb505bdae9ad461736e96fbda76d`；[单次采集器](evidence/interleaved-queue-20261008/run_profiled_queue_trial.py) SHA `66d9a987d3a2187d8b17976bcfa08404469355211ec9d5a082e418a66014d3aa`；[独立分析器](evidence/interleaved-queue-20261008/analyze_queue_benchmark.py) SHA `aec51a8900f4f21b176dbc36d0733badc682ffb6ac4f8ef45064919e0ca5efa5`。

先按前阶段报告分别安装同一 cold raw、cold+resident raw 到两个独立目录，确保后端及校准来源匹配。运行 `scripts/run_interleaved_queue_benchmark.py`，提供 `--conservative-profile`、`--resident-profile`、新的 `--trials-directory` 与 `--output`；使用新的 seed 范围。分析用 `scripts/analyze_queue_benchmark.py --manifest ... --trials-directory ... --output ...`。安装/输出拒绝覆盖；发现未知工作先核验原账本，不盲目重启或换新数据库。

当前完整 567 项自动化通过（16.40 秒），含错误策略、未确认状态、数据摘要、配置变化、失败/缓存、无效计时等拒绝场景。测试夹具不作为性能证据。剩余：直接后端同口径基线、更多参数/模型、混合负载、真实恢复故障验收、稳定安装/Release 与演示交付。
