# 真实 Ollama 控制进程崩溃恢复

2026-10-08，现有 RTX4060Ti / 16,380MiB / 驱动591.86，Ollama0.33.0 / Qwen3.5:9b Q4_K_M，沿用已安装精确8K请求Profile、原SQLite账本和GPU0同账户所有权，保留2.5GiB空间。

## 机制与可信边界

Ollama本身没有本项目可使用的任务历史ID。复用既有 `core/command_worker.py` 独立执行机制，将实际HTTP请求交给一次性 `core/ollama_worker.py`。子执行器从原账本读取固定任务/请求摘要，只有submitting且意图匹配才发送；原子命令claim避免同一命令重复执行。父进程失去响应不重试，完整回执由独立执行器写入原命令日志。

恢复核验同一任务、预留token、精确执行argv、请求摘要、命令confirmed/rc0及完整响应中的model/done/token，再持久化任务终态、关闭操作日志并解除预留。其他命令rc0、容器状态或空模型列表都不能替代对应回执。JSON命令输出有60,000字符上限，避免持久结果截断；超限/异常保留未知。输出正文保存在本地账本，公开材料仅保留摘要及指标。

## 真实故障链

采集源码 `3db1c5bc19c8015d177479ce234de028ef8cf642`，执行器实现首次提交 `44948e423913373e4123581580ec1b7c1c16c390`，未替换后端为模拟服务。

1. 实际请求已提交，任务submitting，唯一受监督命令inflight，尚无持久响应；故障前GPU实际used **6,245MiB**。
2. 验证本次启动控制进程的父关系记录、原生创建时间和Python可执行文件，持有原生句柄后仅终止它。Windows虚拟环境启动器PID14396与实际控制进程PID35060不同，实际退出码1。未终止Ollama容器或其他用户进程。
3. 新控制端重新取得原GPU锁，使用原账本恢复；任务和资源均uncertain。第一次核验返回 `UNCONFIRMED_EXECUTION`，预留继续保留，未重放。
4. 原独立执行器完成真实请求并保存对应回执；再次核验成功，原任务done、原操作confirmed、唯一命令confirmed/rc0，无新增委托命令，资源预留解除。

273个GPU样本、零采样错误，整卡保守峰值 **8,319MiB**（max(used,total-free)）。真实响应处理6,182输入token、24输出token，done=true / done_reason=stop，后端total_duration27.617秒。这是故障恢复证据，不是性能对照或加速结论。CPU检查/桌面后台未隔离，采样可能漏峰值。

恢复后另受管卸载Qwen，记录命令结果、空模型列表和fresh物理回收；任务/资源账本无未确认工作。聚合运行统计已本地备份并恢复，不当作实验raw。

## 保留的失败首轮

首次采集器误将虚拟环境启动器PID视为实际控制PID，在故障注入前退出；原任务继续正常完成。失败raw和原账本done记录侧文件、释放证据完整保留，不将其列为成功崩溃试验。修复后使用原生创建时间/可执行文件指纹与固定进程句柄防止PID重用，并用新输出路径复核；没有在未知执行中重新提交。

## 证据与复现

[完整raw、失败首轮、真实完成记录、两份释放证据、源码版本和摘要](evidence/ollama-crash-recovery-20261008/manifest.json)。独立分析检查故障前无响应、实际GPU占用、未知保持、原任务/命令一致、唯一成功委托回执和采样；一致性检查不是对人为伪造数据的认证，采集源与运行条件仍需独立审查。

```text
python scripts/run_ollama_crash_trial.py --raw <已安装校准raw> --profile-dir <独立Profile目录> --output <新的故障raw>
python scripts/analyze_ollama_crash_trial.py <故障raw>
python scripts/measure_ollama_release.py --output <新的释放raw>
```

仅在相同已核验部署、无未知/未完成任务、其他AI负载已释放时执行。CLI只对自己启动并验证指纹的控制进程注入故障，拒绝覆盖raw，不终止后端服务。Windows路径已真实验收；Linux采集器路径未进行真实GPU故障验证。

## 完成状态与限制

自动化测试与精确CI见PROJECT_STATUS/HANDOFF。本次证明 **控制进程崩溃、独立执行器继续运行、回执完成后的原任务恢复**，不证明机器重启、执行器同时死亡、网络永久失联、GPU驱动崩溃或即时取消。没有回执时仍保留未知，需要继续核验；不能宣布请求失败后自动重放或全局exactly-once保证。

当前启动做有界恢复核验，回执尚未保存时可通过 `POST /api/coordinator/reconcile` 再次核验；试验显式等待现有回执后调用该路径，没有新增常驻恢复看门狗，未宣称所有未知场景全自动清理。

请Chat Agent独立评审：委托边界与精确argv/请求匹配、命令claim、回执/任务/日志写入顺序、缺失与错误回执保留、Windows进程指纹和真实故障链。下一步优先混合任务界面、同口径直接后端基线及安装/Release/演示交付；真实机器/执行器丢失另列验收，不无限扩展框架。
