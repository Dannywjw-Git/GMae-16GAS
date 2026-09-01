# GMae API 契约 v1.0

> **文档版本**：v1.0
> **创建日期**：2026-09-01
> **适用范围**：GMae 指挥家显存调度系统（P-Eng 执行引擎）所有 HTTP API
> **状态**：已冻结，新增端点需遵循本文档规范

---

## 1. 设计原则

1. **统一响应格式**：所有端点返回 JSON，必须包含 `ok` 字段
2. **失败必有 error**：`ok=false` 时必须包含 `error` 字段说明原因
3. **只读用 GET，操作用 POST**：严格区分查询和变更
4. **认证统一**：Session Cookie 或 X-API-Key 二选一
5. **向后兼容**：字段只增不删，废弃字段标记 `@deprecated`

---

## 2. 通用规范

### 2.1 Base URL

```
http://<host>:8787/api
```

### 2.2 认证

两种方式任选其一：

| 方式 | 说明 | 适用场景 |
|------|------|---------|
| Session Cookie | 登录后自动设置 `gmae_session` Cookie | 浏览器前端 |
| X-API-Key | 请求头携带 32 字符 token | CLI / 脚本 / 第三方集成 |

**Token 获取**：服务启动时生成，保存在 `.api_token` 文件。

### 2.3 统一响应格式

#### 成功响应

```json
{
  "ok": true,
  "...业务字段...": "..."
}
```

#### 失败响应

```json
{
  "ok": false,
  "error": "错误说明（人类可读）",
  "error_code": "ERROR_CODE（可选，机器可读）"
}
```

#### 认证失败

```json
{
  "ok": false,
  "error": "unauthorized: please login first",
  "need_login": true
}
```

HTTP 状态码：401

### 2.4 错误码体系

| HTTP 状态码 | 含义 |
|------------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 端点不存在 |
| 500 | 服务器内部错误 |
| 503 | 服务不可用（如模块未启用） |

### 2.5 请求头

```
Content-Type: application/json
X-API-Key: <32字符token>（可选）
```

---

## 3. 端点清单

### 3.1 公开端点（无需认证）

| 方法 | 路径 | 说明 | 关键字段 |
|------|------|------|---------|
| GET | `/api/health` | 健康检查 | `ok`, `ts`, `services.{gpu,ollama,comfyui}` |
| GET | `/api/auth/status` | 认证状态 | `ok`, `has_admin`, `admin_email`, `active_sessions` |
| POST | `/api/auth/setup` | 首次设置管理员 | `email`, `password` |
| POST | `/api/auth/login` | 登录 | `email`, `password`, `remember` |
| POST | `/api/auth/forgot` | 忘记密码 | `email` |
| POST | `/api/auth/reset` | 重置密码 | `email`, `code`, `password` |

### 3.2 状态查询（GET，需认证）

| 方法 | 路径 | 说明 | 关键字段 |
|------|------|------|---------|
| GET | `/api/status` | 全量状态聚合 | `ok`, `gpu`, `gpu_processes`, `containers`, `scene`, `qos`, `vram_ledger` |
| GET | `/api/logs?limit=N` | 读取日志 | `ok`, `logs[]` |
| GET | `/api/registry` | 注册表视图 | `ok`, `scenes`, `ollama_models`, `comfyui_models`, `containers` |
| GET | `/api/budget?context=m1:ctx1,m2:ctx2` | 显存预算引擎 | `ok`, `total_gb`, `used_gb`, `models[]`, `loaded_models[]` |
| GET | `/api/advice` | 显存优化建议 | `ok`, `suggestions[]` |
| GET | `/api/hardware` | 硬件信息 | `ok`, `profile`, `thresholds` |
| GET | `/api/scan` | 模型扫描结果 | `ok`, `sources.{comfyui,ollama}` |
| GET | `/api/queue` | 队列快照 | `ok`, `queue[]`, `tasks[]`, `worker_alive` |
| GET | `/api/comfy_events` | ComfyUI 事件 | `ok`, `events[]` |

### 3.3 显存与桌面（GET，需认证）

| 方法 | 路径 | 说明 | 关键字段 |
|------|------|------|---------|
| GET | `/api/desktop_vram` | 桌面进程显存 | `ok`, `processes[]` |
| GET | `/api/desktop/helper/status` | Helper 状态 | `ok`, `running`, `port` |

### 3.4 场景与组合（POST，需认证）

| 方法 | 路径 | 说明 | 请求体 | 关键字段 |
|------|------|------|--------|---------|
| POST | `/api/scene` | 切换场景 | `{"scene": "dialogue"}` | `ok`, `scene`, `actions[]`, `budget_check`, `duration_ms` |
| POST | `/api/combo` | 切换对话组合 | `{"combo": "fast"}` | `ok`, `combo`, `actions[]` |

**场景列表**（定义在 `resources/registry.json`）：
- `dialogue` — 对话态（10GB预算）
- `comfy` — SDXL出图（12GB预算）
- `h3` — H3出视频（16GB，独占）
- `fooocus` — Flux出图（16GB，独占）
- `music` — 音乐态（16GB，独占）
- `game` — 游戏态（5GB预算）

### 3.5 显存释放与门卫（POST，需认证）

| 方法 | 路径 | 说明 | 请求体 | 关键字段 |
|------|------|------|--------|---------|
| POST | `/api/free` | 一键释放 | 无 | `ok`, `freed_mb`, `free_mb_before`, `free_mb_after`, `stopped[]`, `running[]`, `success_count`, `total_count` |
| POST | `/api/guard` | 门卫操作 | `{"action": "kick", "pid": "..."}` 或 `{"evict": true}` | `ok`, `evicted[]` |

### 3.6 服务与模型（POST，需认证）

| 方法 | 路径 | 说明 | 请求体 | 关键字段 |
|------|------|------|--------|---------|
| POST | `/api/service` | 服务启停 | `{"name": "comfyui", "action": "start"}` | `ok`, `name`, `action`, `rc` |
| POST | `/api/model` | 模型加载/停止 | `{"name": "qwen3.5:9b", "action": "load"}` | `ok`, `name`, `action`, `rc` |

**服务名**：`comfyui`, `fooocus`
**模型操作**：`load`, `stop`
**安全机制**：模型名做格式校验（防注入），加载前检查显存（<4GB 拒绝）

### 3.7 桌面与容器控制（POST，需认证）

| 方法 | 路径 | 说明 | 请求体 | 关键字段 |
|------|------|------|--------|---------|
| POST | `/api/desktop/kill` | 结束桌面进程 | `{"pid": 1234}` | `ok` |
| POST | `/api/container/stop` | 停止容器 | `{"name": "fooocus"}` | `ok` |
| POST | `/api/desktop/helper/start` | 启动 Helper | 无 | `ok` |
| POST | `/api/desktop/helper/stop` | 停止 Helper | 无 | `ok` |

### 3.8 QoS 与自动保护（POST/GET，需认证）

| 方法 | 路径 | 说明 | 请求体 | 关键字段 |
|------|------|------|--------|---------|
| POST | `/api/qos/status` | QoS 状态 | 无 | `ok`, `level`, `suggestions[]`, `config` |
| POST | `/api/qos/check` | 触发 QoS 检查 | 无 | `ok`, `level`, `action` |
| POST | `/api/qos/execute` | 执行 QoS 建议 | `{"suggestion_id": "..."}` | `ok` |
| GET | `/api/auto-protect/status` | 自动保护状态 | 无 | `ok`, `enabled` |
| POST | `/api/auto-protect/config` | 配置自动保护 | `{"enabled": true}` | `ok` |

### 3.9 队列（POST，需认证）

| 方法 | 路径 | 说明 | 请求体 | 关键字段 |
|------|------|------|--------|---------|
| POST | `/api/queue` | 入队 | `{"model": "SDXL", "params": {...}}` | `ok`, `id` |
| POST | `/api/queue/cancel` | 取消任务 | `{"id": "..."}` | `ok` |

### 3.10 准入闸门（POST，需认证）

| 方法 | 路径 | 说明 | 请求体 | 关键字段 |
|------|------|------|--------|---------|
| POST | `/api/admission` | 准入检查 | `{"action": "...", "args": {...}}` | `ok`, `allowed`, `reason` |

### 3.11 扫描登记（POST，需认证）

| 方法 | 路径 | 说明 | 请求体 | 关键字段 |
|------|------|------|--------|---------|
| POST | `/api/scan/register` | 登记新模型 | `{"source": "comfyui", "name": "...", "vram_gb": 6.0}` | `ok` |

### 3.12 账户管理（POST，需认证）

| 方法 | 路径 | 说明 | 请求体 | 关键字段 |
|------|------|------|--------|---------|
| POST | `/api/auth/logout` | 登出 | 无 | `ok` |
| POST | `/api/auth/change-password` | 修改密码 | `{"old_password": "...", "new_password": "..."}` | `ok`, `message` |

---

## 4. 关键数据结构

### 4.1 场景切换结果

```json
{
  "ok": true,
  "scene": "comfy",
  "error": null,
  "budget_check": {
    "ok": true,
    "required_mb": 12288,
    "current_free_mb": 14000,
    "releasable_mb": 2000,
    "total_available_mb": 16000,
    "message": "需要 12.0GB，可用 15.6GB"
  },
  "duration_ms": 8500,
  "vram_free_before": 14000,
  "vram_free_after": 6000,
  "actions": [
    {
      "step": "启动 ComfyUI",
      "action": "docker_start",
      "rc": 0,
      "output": "comfyui",
      "critical": true,
      "skipped": false
    }
  ]
}
```

### 4.2 一键释放结果

```json
{
  "ok": true,
  "freed_mb": 8000,
  "free_mb_before": 6000,
  "free_mb_after": 14000,
  "stopped": [
    {"name": "ollama", "method": "stop_models"},
    {"name": "comfyui", "method": "/free"}
  ],
  "running": [
    {"name": "fooocus", "gpu_mb": 6900, "protected": false, "pid": 1234}
  ],
  "success_count": 2,
  "total_count": 2,
  "actions": [
    {"name": "ollama", "action": "stop models", "ok": true, "output": "..."}
  ]
}
```

### 4.3 步骤动作类型

| action | 说明 | 参数 |
|--------|------|------|
| `pre_release_vram` | 条件性预释放显存 | `threshold_mb` |
| `ollama_stop_all` | 停止所有 Ollama 模型 | — |
| `docker_start` | 启动容器 | `target` |
| `docker_stop` | 停止容器 | `target` |
| `vram_release` | 释放显存（gpu_release.ps1） | — |
| `game_on` | 游戏模式优化 | — |
| `wait_ready` | 等待端口就绪 | `port`, `timeout_s`, `requires` |

---

## 5. 版本化策略

### 5.1 当前版本

- **API 版本**：v1（未在路径中体现，所有端点在 `/api/` 下）
- **契约版本**：v1.0（本文档）

### 5.2 兼容性规则

1. **新增字段**：允许，不影响现有客户端
2. **修改字段含义**：禁止，需新增字段
3. **删除字段**：禁止，需标记 `@deprecated` 并保留至少一个大版本
4. **新增端点**：允许，需在本文档登记
5. **修改端点行为**：需经评审，必要时新增 v2 端点

### 5.3 未来 v2 规划

- 路径中体现版本：`/api/v2/...`
- 统一响应格式：`{ok, data, error, meta}`
- 分页参数标准化：`?page=1&page_size=20`
- 排序参数标准化：`?sort=field:asc`
- WebSocket 实时推送：`/ws/status`

---

## 6. 测试

### 6.1 自动化测试

```bash
# 运行全量 API 测试（需服务已启动）
python tests/api_test.py

# 指定地址和 token
python tests/api_test.py --base-url http://127.0.0.1:8787 --token <token>
```

### 6.2 测试覆盖

- 22 个测试模块，55 个断言
- 覆盖所有 GET 端点和关键 POST 端点
- 包含参数校验、错误处理、认证测试
- 耗时约 30 秒

### 6.3 测试通过标准

- 所有断言通过（fail=0）
- 服务进程无崩溃
- 关键操作（场景切换、释放显存）有实际效果

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-09-01 | 初始版本，冻结现有 38 个端点契约 |

---

*本文档是前后端开发的共同约定。修改本文档需经项目负责人批准。*
