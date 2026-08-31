# engine/ — 调度引擎层

> GMae 指挥家的核心决策引擎，负责任务准入、显存预算、队列调度、QoS 降级和看门狗。
> 本层依赖 core/，不依赖 services/（通过依赖注入或回调调用服务）。

## 模块清单

| 模块 | 职责 |
|------|------|
| `admission_gate.py` | 准入闸门：任务提交前的规则校验（显存预算/模型登记/场景冲突） |
| `budget.py` | 显存预算引擎：计算各模型的显存占用与加载/驱逐决策 |
| `queue.py` | 任务队列：FIFO 队列 + worker 线程 + ComfyUI 工作流执行 |
| `qos.py` | QoS 引擎：显存水位分级（ok/warning/emergency）+ 降级建议 + 自动防死机 |
| `eviction_guard.py` | 驱逐门卫：检查并驱逐低优先级模型/容器释放显存 |
| `gen_stats.py` | 生成统计：任务完成率/平均耗时/成功率的持久化统计 |
| `reaper.py` | 服务收割者：监控服务活跃度，自动停止空闲服务 |
| `scanner.py` | 模型扫描器：扫描已安装模型并登记到 registry |
| `watchdog.py` | 看门狗：监控服务健康状态，自动重启崩溃服务 |

## 核心流程

```
用户提交任务
    ↓
admission_gate.check()  → 准入校验
    ↓
budget_engine()         → 显存预算计算
    ↓
queue.enqueue()         → 入队
    ↓
worker 线程
    ├─ eviction_guard.evict()  → 必要时驱逐
    ├─ _load_workflow()        → 加载工作流
    └─ _queue_submit_comfy()   → 提交 ComfyUI
    ↓
qos 后台线程              → 持续监控显存水位
```

## 设计原则

1. **状态集中**：所有引擎状态存储在 core.registry，不使用模块级全局变量
2. **锁保护**：涉及复合读写的状态变更使用模块级锁（如 _qos_lock）
3. **错误链**：底层异常使用 `raise ... from` 保留完整错误链
4. **可测试**：每个引擎模块可独立单元测试，不依赖外部服务
