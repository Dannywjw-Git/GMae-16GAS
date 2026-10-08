# 可信驻留增量准入与正式队列试验（2026-10-08）

## 已实现及边界

正式队列可以显式安装冷/驻留两份原始测量：固定两份 raw 摘要和余量，核对实际工作流、GPU/驱动、服务版本/参数与模型内容摘要。只改变 seed/输出名可复用；尺寸、提示词等变化需要自己的测量。完整来源快照加 fresh 文件身份吻合时采用 `fresh_used + measured_growth + margin`，保留 2.5 GiB 余量；保守计数统一为 `max(used,total-free)`。

候选增量为 seed 52 的 672 MiB 增长 + 512 MiB 余量 = 1,184 MiB。三组件实际驻留为 6,618 MiB，单独用于大模型互斥，不能将任务增量当成小模型体积。只读观察接口的 `warm_admission_enabled=false` 表示观察器自身不给执行许可；主机正式协调器只在显式安装、原始证据和当前状态核验后决定准入。前端显示“任务额外显存（含余量）”。

观察接口缺失、未知/部分/加载中状态、后端实例改变、来源元数据/观察代码变化时回退冷包络；模型内容或执行环境不匹配登记证据时拒绝；已安装 raw 被改动或 accepted reference 不一致则拒绝执行。新加载轮次本身不等于未知：当前完整三组件、来源、字节和独立内容核验与校准条件完全相同，才允许在同一实例内复用；加载跨越校准窗口或轮次回退拒绝。外部客户端、跨账户及恶意伪造文件元数据不隔离，这不是显存硬配额或 OOM 保证。

## 原始正式运行

硬件为同一 RTX 4060 Ti 16GB / driver 591.86，实际 ComfyUI 0.34.0、torch 2.5.1+cu121，SDXL 文件摘要及工作流绑定见 seed 51/52 源校准。所有运行从空闲账本、同账户 GPU 0 锁、无其他受管模型/任务开始。512×512、8 步、CFG 6、同一提示词，仅 seed 不同。保守和驻留策略使用同一 cold seed 51、同一 512 MiB 余量；驻留策略额外安装 seed 52 raw。

| 运行 | 正式准入 | 端到端秒 | 受管卸载调用 | used 峰值 MiB | 样本 / 错误 | 任务 / 后端 / 采样器缓存 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| seed 53 | 驻留增量 | 76.531 | 0 | 8,721 | 295 / 0 | done / success / false |
| seed 54 | 驻留增量 | 72.500 | 0 | 8,708 | 282 / 0 | done / success / false |
| seed 55 | 保守整卡包络 | 134.469 | 1 | 8,662 | 520 / 0 | done / success / false |
| seed 56（重新加载后） | 驻留增量 | 72.250 | 0 | 8,707 | 286 / 0 | done / success / false |

计时从正式入队到持久任务终态，包括首次模型摘要核验、准入、卸载（若发生）、提交及终态轮询。每次使用新进程，摘要缓存未预热；不能拿这些时间与裸后端 1.562 秒相比。表中峰值为采集器原始 used 描述；安全判定使用更保守计数。

seed 54/55 使用提交 `1f554d02c044ac91788139a69fcf40708e017b5a`。seed 53 在补充显示 loaded/中文说明前采集，核心增量算法相同；不能宣称其验证后续全部源码。加载状态变化复核使用 `5f5df235505f4f39c45417d82da283f38b04e2fa`，seed 56 验证加载轮次 2 的完整状态可复用，前后轮次不变。完整 554 项自动化通过（16.14 秒），前端模块和协调器行为检查通过。

这是顺序执行的初步策略试验，不是随机交错统计基准。背景占用、CPU/磁盘缓存未控制，保守组一次，不发布普遍加速倍数或成功率保证。它验证当前配置的正式路径确实避免多余卸载；还须重复、交错次序和混合负载对照。

## 证据与复现

- [seed 53 raw](evidence/phase-queue-seed53-20261008.json)：`17e7e21bb920f562edf55da5bf32fbee13d6fedeaa6aa16fccf5bfe0e76d8387`。
- [seed 54 raw](evidence/phase-queue-seed54-20261008.json)：`7574c6421ec10151cf0c2e97044e235baca05b557ccd5f5ec2a9d6caaf4adf75`。
- [seed 55 raw](evidence/conservative-queue-seed55-20261008.json)：`e6f54303759c9705e26190d92d2b140a8af98d806249925a51994037ae7ddf66`。
- [采集源码版本](evidence/collectors/run_profiled_queue_phase-seeds53-55.py)：`12bf47a38e939d0145f3669e8bbb93d19eb0b289cbe4cedc469f4c6087e36dfa`。

以 `scripts/install_phase_profile.py --cold-raw <cold.json> --resident-raw <resident.json> --destination <新目录>` 显式安装，经审查的源数据必须匹配配置与环境。`scripts/run_profiled_queue_trial.py --profile-dir <目录> --seed <新 seed> --output <新 raw>` 使用正式队列。保守组用 `install_workload_profile.py` 仅安装同一 cold raw 到另一新目录。安装与采集拒绝覆盖。输出仅将活动预留 token 转为摘要，保留全部性能与状态证据；未公开可复用令牌。

生产默认 Profile 目录仍是既有 cold 配置，阶段 Profile 位于新的可选目录，未自动修改其他运行服务。发布前仍需完整安装验收、参数网格、混合负载、恢复故障试验及演示材料。

[seed 56 raw](evidence/phase-queue-after-reload-seed56-20261008.json)，SHA256 `c5ccb63e0c9636b08a3d7af99c6f41df999978e33c9d0a7c5f2d148dd4f226b8`，使用同一采集源码。原始诊断中的 `calibration_workflow_sha256` 沿用了 cold raw 的原始工作流；实际匹配使用相同的参数配置指纹并绑定两份 raw 摘要，四次时间/显存/终态不受该显示字段影响。后续修复将 cold/raw 来源与 resident 校准工作流明确分开，自动化覆盖该关联；不改写原始数据。最后四次试验后 unfinished tasks=0、pending operations=0。运行时历史计数另存本地，未将聚合平均数冒充本轮对照。
