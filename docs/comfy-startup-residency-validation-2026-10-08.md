# ComfyUI 启动与实际驻留来源验收（2026-10-08）

## 结论与证明范围

可选只读观察扩展已在现有 ComfyUI 容器激活，源码摘要与仓库两文件一致。一次真实 SDXL 512×512、8 步、seed 51 生成后，fresh 快照识别 UNet、CLIP、VAE，三者完整驻留、未打补丁、来源文件元数据一致、未知组件为零。模型文件 SHA256 在采集前独立重算；观察接口自身仍明确 `artifact_digest_verified=false`。这些证据不等于任意模型内容认证或 warm 调度收益，warm 准入保持关闭。

## 启动协议

现有生产重启缺少登记启动峰值，被安全拒绝。使用显式本机实验入口 `scripts/calibrate_comfy_startup.py`，同账户 GPU 0 系统锁绑定原任务账本；拒绝其他/未确认任务与 Ollama 驻留、运行 Fooocus；先受管卸载，再 fresh torch 低水位与物理空闲核验。固定实验容量预算 10,240 MiB、余量 2,560 MiB，不以未经实测的估计伪装 Profile。正常 HTTP/服务入口不接收实验标志，普通生产重启继续要求 Profile。

实验容量是保守规划估计，不是硬件显存限额或 OOM 保证；外部客户端及跨账户不隔离。命令意图与回执使用持久操作账本；成功回执加 fresh 同容器运行状态，仅证明命令与目标状态，服务版本/接口就绪和 GPU 样本分别核验。不会自动重试或自动安装生产峰值。已有私有容器快照保留，未重建容器、未公开镜像。

首次校准在重启命令前因 Windows 本地编码无法解码 Docker UTF-8 输出而失败；保留原始失败记录。修复直接与独立命令执行的 Docker 解码后，第二次命令返回 0，容器 ID 一致，ComfyUI 0.34.0 / Python 3.10.12 / torch 2.5.1+cu121 未变，观察源码摘要匹配，启动到就绪后额外 15 秒共采样 35.968 秒。119 样本、0 错误、整卡保守计数 `max(used,total-free)` 最大 1,665 MiB。包含后台/桌面，有限采样可能漏瞬时峰值；一次样本不足以确定通用启动预算。

## 原始证据

| 证据 | SHA256 |
| --- | --- |
| [命令前失败](evidence/comfy-startup-calibration-20261008.json) | `343fb936f705800c8001df1e33a4501f68dcd79d5fa1877767405bcf3a439206` |
| [启动成功](evidence/comfy-startup-calibration-second-attempt-20261008.json) | `5ae1497e4734f41aaa55bb334ffba8634049f2c46129b7cf176518c005562666` |
| [SDXL seed 51](evidence/sdxl-observer-512-seed51-20261008.json) | `0b19fde07d3b2065a6f4467169a52df4faeb2d1a86295ab98dbf8430ee30d396` |
| [启动采集版本](evidence/collectors/startup-20261008.py) | `d762e83ddf8a7a19b57057ef72582c412228aed8c2f76c631091744735d0a2c8` |
| [seed 51/52 采集版本](evidence/collectors/measure_comfy_workload-seed51.py) | `024d7118033033aff39665397e22b6640d2e00d73fe8976b0390bfc832ab5b35` |

SDXL seed 51：188 样本、0 错误，后端 success、采样器未缓存，生成窗口 49.031 秒，used 观测峰值 8,705 MiB。该窗口从提交开始到终态观察，不包括模型摘要核验与准备。GPU 型号/驱动/匿名设备标识、模型摘要、参数、后端实际环境及前后观察均在 raw；不可拿它直接对比包含摘要核验的旧端到端时间。

## 复现与未完成

先完成依赖安装、受管容器和现有备份，保证无其他任务。运行 `python scripts/calibrate_comfy_startup.py --output <新的文件>`，再运行 `python scripts/measure_comfy_workload.py --prepare-unloaded --capture-residency --seed 51 --output <新的文件>`。输出拒绝覆盖；已确认命令失败或未知时先核验账本与后端，不能盲目重启。

完整自动化 538 项通过（16.05 秒）。真实驻留身份已覆盖当前 SDXL 和三组件；其他模型、文件恶意替换、跨账户隔离、生产 warm 准入、编排性能收益、混合负载对照、重复稳定性仍未完成。启动后加强了实验标志类型和其他 GPU 服务空闲检查，首次成功原始协议已有 CLI 预检，不据此宣称新守卫本身实机验收。下一步将实际驻留状态绑定测量阶段增长及正式预算，做重复对照。

## 驻留生成 seed 52

[原始数据](evidence/sdxl-observer-resident-512-seed52-20261008.json)，SHA256 `bdedca01f4fc3bb0f15c9802a43193fa4ccbc9a9ba953dc4e9554607bcf9ac2d`。同配置、seed 52，生成窗口 1.562 秒、7 样本、0 错误、采样器未缓存。保守计数基线 8,307 MiB、峰值 8,979 MiB，增长 672 MiB；前后实际三组件完整驻留、后端实例相同、load_epoch=1 未变。仍为独立实验入口；正式 warm 准入未实现。不能用增长直接代替已绑定、留足余量的生产预算，不能将两次单样本之比当作编排加速。
