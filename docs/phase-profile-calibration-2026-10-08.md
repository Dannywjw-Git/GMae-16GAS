# 真实 GPU 加载条件与参数校准

日期：2026-10-08。分支 `feat/phase-profile-calibration-20261008`，基于 PR #9 的 `2ef4329`。该基础提交的 PR CI `37730589456` 与 push CI `37730586264` 均 success。本阶段先测清重复卸载的代价与驻留增量；尚未实现 warm 准入，也没有 GMae 调度加速结论。

## 新工具与条件

采集器允许实际 width/height/steps/cfg 控制，先验证并固定 payload，再取得正式 GPU 0 所有权。最大实验范围 1024×1024、20 步，并非这些范围全部已测。未知账本、后台活动、Ollama 驻留或运行中的 Fooocus 均拒绝孤立实验。长时间模型摘要核验后，释放前及提交前再次核验工作。

`--prepare-unloaded` 使用正式协调器和操作日志请求 ComfyUI `/free`，持续核验物理可用容量、利用率和 fresh CUDA 0 torch 占用，最多 30 秒。只有 torch 驻留不超过 64 MiB、物理可用不少于 10,752 MiB、利用率不超过 20 才进入此条件；随后再次记录实际起点。命令成功不能替代容量证明。CPU/磁盘缓存未清空，不能称作完全冷启动。

`--resident-baseline` 不释放模型；要求实际 torch 驻留超过 64 MiB，但不证明驻留的是哪个 checkpoint。两种标志互斥。正式队列的安全策略没有因此放宽。

## 实际结果

以下四次均为真实 GPU 成功终态、采样错误 0、采样器缓存未命中。提示词固定为公开红色茶壶，8 步、cfg 6.0、批量 1。每种配置/条件目前各一次，不能提供统计保证。

| 配置 | 条件 | 生成窗口秒 | 起始整卡 MiB | 整卡峰值 MiB | 观测增长 MiB | 样本 / 错误 |
| --- | --- | --- | --- | --- | --- | --- |
| 512×512 / seed 47 | 卸载且低 torch 已核验 | 40.891 | 1773 | 9011 | 7238 | 156 / 0 |
| 512×512 / seed 48 | 保留驻留内存，模型身份未证明 | 1.578 | 8433 | 9105 | 672 | 7 / 0 |
| 768×768 / seed 49 | 卸载且低 torch 已核验 | 37.750 | 1799 | 9977 | 8178 | 146 / 0 |
| 768×768 / seed 50 | 保留驻留内存，模型身份未证明 | 2.578 | 8442 | 9978 | 1536 | 11 / 0 |

时间窗口从独立持久提交前开始，至后端成功历史被观察到结束；不包含约一分钟的模型摘要核验、实验准备卸载和初始安全检查。这不同于 PR #9 正式队列 143.5 秒端到端口径。基础模型/CLIP/latent 节点在驻留试验中缓存，采样器未缓存；卸载后两次 cached_node_ids 均为空。加载、编译、磁盘缓存、桌面背景等条件影响耗时，因此不得据此计算“GMae 加速倍数”。768 的卸载试验比 512 略快亦不能解读为更高分辨率更快。

卸载 seed 47 的 `/free` 即时回收报告为 0 MiB，之后 4.422 秒的整个准备过程中 torch 和物理占用逐步下降，最终起始 torch 约 8.125 MiB。两次卸载后基线均为这个量级。驻留起点 torch 为 6,947,425,310 字节，仍观察到 672/1,536 MiB 的额外整卡增长。不能使用“已加载即零增量”，也不能从两个点拟合普遍公式。

硬件 RTX 4060 Ti、16,380 MiB、驱动 591.86。实际服务 ComfyUI 0.34.0、Python 3.10.12、PyTorch 2.5.1+cu121；模型 SHA-256 `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b`。原始文件保留完整硬件摘要、服务/启动摘要、工作流、提交身份、采样和终态。

## 复现与独立分析

```powershell
.venv\Scripts\python.exe scripts\measure_comfy_workload.py --prepare-unloaded --seed 47 --output unloaded512.json
.venv\Scripts\python.exe scripts\measure_comfy_workload.py --resident-baseline --seed 48 --output resident512.json
.venv\Scripts\python.exe scripts\measure_comfy_workload.py --prepare-unloaded --width 768 --height 768 --seed 49 --output unloaded768.json
.venv\Scripts\python.exe scripts\measure_comfy_workload.py --resident-baseline --width 768 --height 768 --seed 50 --output resident768.json
.venv\Scripts\python.exe scripts\analyze_workload_trials.py --raw unloaded512.json resident512.json unloaded768.json resident768.json --output analysis.json
.venv\Scripts\python.exe scripts\diagnose_profile_budget.py --raw resident768.json --output budget-diagnostic.json
```

实验产生真实生成任务，应在受管部署且无其他用户工作时运行。输出文件不覆盖；超时任务保留未知，不自动重放。直接采集路径使用正式进程所有权和持久提交边界，但绕过编排器生成准入，是对照/校准工具，不是产品行为验收。

分析工具重验原始成功证据、环境和工作流身份，再按不含 seed/输出名的配置及完整环境分组；不会合并不同尺寸或驱动。`scheduler_benefit_proven` 与 `residency_identity_proven` 明确为 false，观测增长不能直接作为可复用 warm 预算。

## 原始数据和采集版本

- [sdxl-unloaded-512-seed47-20261008.json](evidence/sdxl-unloaded-512-seed47-20261008.json)：`fc86fd456ab63b75e740043af9ca35b879b16ce22cd5335893b5caa09d3d7a17`。
- [sdxl-resident-512-seed48-20261008.json](evidence/sdxl-resident-512-seed48-20261008.json)：`dcef91d5e8bfae075f2509443ec05835518810e4dbde0e54fd93b71e9519abe0`。
- [sdxl-unloaded-768-seed49-20261008.json](evidence/sdxl-unloaded-768-seed49-20261008.json)：`abff4f0b261a8d1ead2908c22d6e4bc0048676f3d2e80f422c723d59e2e75583`。
- [sdxl-resident-768-seed50-20261008.json](evidence/sdxl-resident-768-seed50-20261008.json)：`7d0c0eae76781c3e7e5e4e641c8e5f5453741bf58935f4ac44d71a608f74bd50`。

[分析 JSON](evidence/sdxl-loading-conditions-analysis-20261008.json)可从原始文件重新生成。seed 47 使用的采集器在运行后增加了驻留标志的低 torch 拒绝检查，其原始版本按 recorded SHA-256 严格复原并保存在 [版本快照](evidence/collectors/measure_comfy_workload-seed47.py)；seed 48–50 的采集器见 [版本快照](evidence/collectors/measure_comfy_workload-seeds48-50.py)。这两个文件供源码摘要复核，原运行入口位于 scripts/，不要直接从归档目录运行。公开原始数据字节与本地原件一致，未公开协调器 token、私人任务或模型路径。

## 已证明的问题与下一步

只读将 768 实测峰值加 512 MiB 余量得到 10,490 MiB，代入当前保守预算：[诊断记录](evidence/sdxl-768-whole-device-budget-diagnostic-20261008.json)。实际驻留时目标 loaded=false，decision=free_L2，要求释放约 5.4 GiB。这是 read-only 预算诊断，未安装 Profile、未核验正式准入。说明当前历史模型身份和重复计量仍使可复用工作流请求卸载。

必须采用 fresh 模型/组件驻留身份与分阶段校准，才可减少卸载。详见 [下一阶段设计](phase-profile-design.md)。只读核查已部署 ComfyUI 的 LoadedModel/ModelPatcher 源码，确认存在实际 loaded_size 接口；观察扩展尚未实现或部署。无需改变核心目标或引入另一套调度框架。

尚未完成：可信 warm 准入、真实编排策略对照、重复/交错试验、混合 AI 负载、广泛参数网格、真实取消/崩溃恢复、完整安装验证及 Release/演示材料。768 校准文件可构建严格匹配的保守 Profile，但当前正式部署未启用或验证这个配置。

## 自动化与交接

完整 489 项测试通过（15.61 秒），新增 19 项实验条件与分组验证；名称检查 0 阻断、65 既有警告，编译和 diff 检查通过。本阶段新 CI 按实际 HEAD 单独核验。测试中的合成条件只验证拒绝/分组，不作为性能证据。

独立评审重点：生成时间与端到端时间的口径、驻留身份未证明、释放检查不能只认 HTTP 成功、参数组不混合、源文件摘要可复核，以及下一阶段 warm 预算的失败关闭条件。不等待独立 Chat 反馈继续推进。
