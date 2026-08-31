# services/ — 外部服务封装层

> GMae 指挥家与外部 AI 服务的交互层，封装 Ollama/ComfyUI/Docker 等服务的 API 调用。
> 本层依赖 core/ 和 engine/，被 api/ 层调用。

## 模块清单

| 模块 | 职责 |
|------|------|
| `ollama.py` | Ollama 服务封装（模型列表/加载/停止/PS 监控） |
| `comfy.py` | ComfyUI 服务封装（显存释放/工作流提交/历史查询） |
| `comfy_ws.py` | ComfyUI WebSocket 实时进度推送 |
| `docker.py` | Docker 容器管理（列表/启动/停止/场景推断/等待就绪） |
| `scene.py` | 场景识别与切换（dialogue/image/video/audio/game） |
| `status.py` | 聚合状态服务（GPU/容器/模型/显存台账的并行查询与缓存） |
| `vram_helper.py` | 显存辅助工具（释放脚本/进度条/VMWP 特殊处理） |
| `helper.py` | Helper 服务（自动保护配置/系统信息） |

## 设计原则

1. **容错优先**：所有外部服务调用都有 try-except，失败时返回安全默认值
2. **超时控制**：所有网络请求设置合理超时（5-15秒），避免阻塞
3. **缓存策略**：status 模块使用 2.5s TTL 缓存，避免频繁查询外部服务
4. **无状态**：服务层不持有持久状态，所有状态通过 core.registry 共享
5. **错误返回**：统一使用 `(ok, data, error)` 元组或 `{"ok": bool, ...}` 字典返回

## 依赖关系

```
services/  →  core/ (配置/日志/注册表)
services/  →  engine/ (预算/准入查询)
    ↑
    └── 被 api/ 层调用
```

## 注意事项

- ComfyUI 容器禁止使用 `docker compose up -d` 重建（会清空自定义节点）
- 显存释放必须先确认无任务在运行，避免中断生成
- VMWP 进程（Windows 虚拟机工作进程）的显存占用需特殊处理，不计入可释放显存
