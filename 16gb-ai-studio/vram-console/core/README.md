# core/ — 核心基础设施层

> GMae 指挥家的底层基础设施，所有上层模块的公共依赖。
> 本层不依赖 engine/ 或 services/，避免循环依赖。

## 模块清单

| 模块 | 职责 |
|------|------|
| `config.py` | 全局配置加载与阈值管理（REGISTRY 初始化、阈值读取） |
| `registry.py` | 线程安全的全局状态注册表（所有可变状态的唯一权威来源） |
| `logger.py` | 统一日志系统（log_event/log_error/toast_notify） |
| `exceptions.py` | 自定义异常类体系（业务错误 vs 系统错误） |
| `hardware_probe.py` | 硬件探测（GPU/显存/内存/系统/Docker 可用性） |
| `thresholds.py` | 显存阈值常量与动态阈值计算 |
| `utils.py` | 通用工具函数（run_args 等） |

## 设计原则

1. **无状态优先**：除 registry 外，core 层模块不持有全局可变状态
2. **线程安全**：registry 所有读写操作内部加锁，调用方无需关心
3. **错误分类**：所有异常继承自 GMaeError，分为 BusinessError 和 SystemError
4. **日志统一**：禁止 print()，统一使用 logger 模块

## 依赖关系

```
core/  ←  engine/  ←  services/  ←  api/
  ↑
  └── 被所有层依赖
```
