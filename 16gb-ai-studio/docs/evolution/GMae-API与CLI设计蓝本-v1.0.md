# GMae API 规范与 CLI 设计蓝本 v1.0

> **定位**：个人赛与企业赛的公共基础层设计。API 先行，CLI 是 API 的客户端。
> **创建**：2026-09-01
> **状态**：设计蓝本，待主公确认后实施

---

## 0. 设计原则

1. **API 先行**：所有能力先暴露为 REST API，CLI/Web/第三方都调用 API
2. **统一认证**：API Key + Session Token，CLI 和 Web 共用
3. **结构化输出**：API 返回 JSON；CLI 支持 `--json`（机器可读）和默认（人类可读）
4. **远程支持**：CLI 可连接本地或远程 GMae 实例（为虚拟机探针做准备）
5. **版本化**：所有接口使用 `/api/v1/` 前缀，新增接口不破坏旧接口
6. **幂等性**：GET 只读；POST/PUT/DELETE 有明确副作用，返回操作结果

---

## 1. 通用规范

### 1.1 Base URL

```
http://<host>:8787/api/v1
```

- 本地默认：`http://127.0.0.1:8787/api/v1`
- 远程实例：`http://<vm-ip>:8787/api/v1`（企业赛虚拟机探针场景）

### 1.2 认证

两种方式，二选一：

**方式A：API Key（推荐 CLI/脚本使用）**
```http
X-API-Key: <32字符token>
```

**方式B：Session Token（Web 控制台使用）**
```http
Cookie: session=<token>
```

API Key 文件：`.api_token`（32字符，首次启动自动生成）

### 1.3 统一响应格式

**成功响应：**
```json
{
  "ok": true,
  "data": { ... },
  "meta": {
    "timestamp": 1756789012,
    "version": "v1.0",
    "request_id": "req_abc123"
  }
}
```

**错误响应：**
```json
{
  "ok": false,
  "error": {
    "code": "INSUFFICIENT_VRAM",
    "message": "显存不足，需要 8192MB，可用 4096MB",
    "detail": {
      "required_mb": 8192,
      "available_mb": 4096,
      "suggestion": "释放 ComfyUI 模型或切换场景"
    }
  },
  "meta": { "timestamp": 1756789012 }
}
```

### 1.4 错误码体系

| HTTP状态码 | 错误码前缀 | 说明 |
|-----------|-----------|------|
| 400 | `INVALID_*` | 请求参数错误 |
| 401 | `AUTH_*` | 认证失败 |
| 403 | `PERMISSION_*` | 权限不足 |
| 404 | `NOT_FOUND_*` | 资源不存在 |
| 409 | `CONFLICT_*` | 状态冲突（如队列已满） |
| 429 | `RATE_LIMIT` | 限流 |
| 500 | `SYSTEM_*` | 系统内部错误 |
| 503 | `SERVICE_*` | 外部服务不可用 |

对应 `core/exceptions.py` 中的异常类：
- BusinessError → 4xx
- SystemError → 5xx

---

## 2. API 接口规范

### 2.1 系统状态

#### GET /api/v1/status
全局健康状态聚合。

**响应：**
```json
{
  "ok": true,
  "data": {
    "gpu": {
      "name": "NVIDIA GeForce RTX 4060 Ti",
      "vram_total_mb": 16384,
      "vram_used_mb": 8192,
      "vram_free_mb": 8192,
      "base_noise_mb": 3480,
      "utilization_pct": 45,
      "temperature_c": 68
    },
    "scene": "image",
    "containers": {
      "comfyui": "running",
      "ollama": "running",
      "fooocus": "stopped"
    },
    "models": {
      "loaded": ["sdxl", "qwen3.5:9b"],
      "registered": 21
    },
    "queue": {
      "pending": 1,
      "running": 1,
      "completed_today": 42
    },
    "qos_level": "ok",
    "health": "healthy"
  }
}
```

#### GET /api/v1/health
轻量健康检查（无需认证）。

**响应：**
```json
{ "ok": true, "status": "healthy", "uptime_s": 3600 }
```

### 2.2 显存管理

#### GET /api/v1/vram/ledger
显存台账（按进程/模型分解）。

**响应：**
```json
{
  "ok": true,
  "data": {
    "total_mb": 16384,
    "base_noise_mb": 3480,
    "entries": [
      {"type": "model", "name": "sdxl", "vram_mb": 6442, "pid": 1234},
      {"type": "model", "name": "qwen3.5:9b", "vram_mb": 5735, "pid": 5678},
      {"type": "system", "name": "vmwp", "vram_mb": 512, "note": "Windows虚拟机工作进程，不可释放"},
      {"type": "other", "name": "unknown", "vram_mb": 1024, "pid": null}
    ],
    "free_mb": 4096,
    "releasable_mb": 12177
  }
}
```

#### POST /api/v1/vram/release
释放显存。

**请求体：**
```json
{
  "target": "comfyui",          // comfyui | ollama | fooocus | all | <model_name>
  "force": false                // 是否强制释放（即使有任务运行）
}
```

**响应：**
```json
{
  "ok": true,
  "data": {
    "released_mb": 6442,
    "freed_targets": ["sdxl"],
    "before_free_mb": 4096,
    "after_free_mb": 10538
  }
}
```

#### GET /api/v1/vram/budget
显存预算引擎输出（各模型的加载/驱逐决策）。

**响应：**
```json
{
  "ok": true,
  "data": {
    "models": [
      {"id": "sdxl", "decision": "keep", "vram_mb": 6442, "note": "当前场景需要"},
      {"id": "flux", "decision": "free", "vram_mb": 12000, "note": "显存不足，建议驱逐"},
      {"id": "wan2.2", "decision": "reject", "vram_mb": 9300, "note": "峰值超过物理上限"}
    ],
    "summary": {"keep": 1, "free": 1, "reject": 1}
  }
}
```

### 2.3 任务队列

#### GET /api/v1/queue
队列状态。

**查询参数：**
- `status`: pending | running | completed | failed | all（默认 all）
- `limit`: 返回数量（默认 20）

**响应：**
```json
{
  "ok": true,
  "data": {
    "pending": [...],
    "running": {...},
    "completed": [...],
    "stats": {"total": 10, "completed_today": 42, "success_rate": 0.95}
  }
}
```

#### POST /api/v1/queue/submit
提交任务。

**请求体：**
```json
{
  "model": "sdxl",               // 模型ID
  "workflow": "sdxl_text2img.json",  // 工作流文件名
  "params": {
    "prompt": "一只猫在太空",
    "seed": 42,
    "width": 1024,
    "height": 1024
  },
  "priority": "normal",          // low | normal | high
  "callback_url": null           // 可选，完成后回调
}
```

**响应：**
```json
{
  "ok": true,
  "data": {
    "task_id": "task_20260901_001",
    "status": "pending",
    "position": 2,
    "estimated_wait_s": 30
  }
}
```

**错误（准入拒绝）：**
```json
{
  "ok": false,
  "error": {
    "code": "ADMISSION_DENIED",
    "message": "显存不足，任务被准入闸门拒绝",
    "detail": {
      "violated_rules": ["vram_budget"],
      "required_mb": 8192,
      "available_mb": 4096
    }
  }
}
```

#### GET /api/v1/queue/{task_id}
查询任务状态。

#### POST /api/v1/queue/{task_id}/cancel
取消任务。

### 2.4 模型管理

#### GET /api/v1/models
已登记模型列表。

**查询参数：**
- `modality`: image | video | audio | text | all
- `status`: loaded | available | all

#### POST /api/v1/models/register
登记新模型（手动或扫描）。

#### POST /api/v1/models/{model_id}/benchmark
触发模型评测（M-Eng）。

#### GET /api/v1/models/{model_id}/benchmark
获取评测结果。

### 2.5 场景管理

#### GET /api/v1/scene
当前场景。

#### POST /api/v1/scene/switch
切换场景。

**请求体：**
```json
{
  "scene": "image",    // image | video | audio | dialogue | game
  "force": false
}
```

### 2.6 QoS 与告警（企业赛重点）

#### GET /api/v1/qos/status
QoS 状态与降级建议。

**响应：**
```json
{
  "ok": true,
  "data": {
    "level": "warning",          // ok | warning | emergency
    "free_mb": 3000,
    "suggestions": [
      {
        "id": "sug_001",
        "type": "ollama_stop",
        "priority": "high",
        "title": "停止 qwen3.5:9b",
        "estimated_free_mb": 5735,
        "impact": "对话功能暂时不可用"
      }
    ],
    "auto_protect": {
      "enabled": true,
      "mode": "standard",
      "last_trigger": null
    }
  }
}
```

#### POST /api/v1/qos/execute
执行降级建议。

**请求体：**
```json
{ "suggestion_id": "sug_001" }
```

#### GET /api/v1/alerts
告警列表（企业赛）。

**查询参数：**
- `level`: critical | warning | info
- `status`: active | acknowledged | resolved
- `limit`: 默认 50

**响应：**
```json
{
  "ok": true,
  "data": {
    "alerts": [
      {
        "id": "alert_001",
        "level": "critical",
        "source": "gpu",
        "title": "显存即将耗尽",
        "message": "可用显存 1800MB，低于紧急阈值 2048MB",
        "timestamp": 1756789012,
        "status": "active",
        "related_resources": ["gpu:0", "container:comfyui", "model:flux"],
        "evidence_chain": [
          {"layer": "gpu", "event": "vram_low", "value": "1800MB"},
          {"layer": "container", "event": "comfyui_loading", "value": "flux"},
          {"layer": "model", "event": "vram_peak", "value": "12000MB"}
        ]
      }
    ],
    "summary": {"critical": 1, "warning": 2, "info": 0}
  }
}
```

#### POST /api/v1/alerts/{alert_id}/acknowledge
确认告警。

#### POST /api/v1/alerts/{alert_id}/resolve
解决告警。

### 2.7 诊断（企业赛重点）

#### POST /api/v1/diagnose
故障诊断（根因分析 + 影响范围 + 处置建议）。

**请求体：**
```json
{
  "target": "task_001",          // task_id | container | alert_id | 自动
  "depth": "standard"            // quick | standard | deep
}
```

**响应：**
```json
{
  "ok": true,
  "data": {
    "root_cause": {
      "layer": "gpu",
      "cause": "显存不足导致 OOM",
      "confidence": 0.92,
      "evidence": [
        "ComfyUI 日志: CUDA out of memory",
        "GPU 显存峰值: 15.8GB / 16GB",
        "同时加载模型: sdxl + flux"
      ]
    },
    "impact_scope": {
      "affected_tasks": ["task_001", "task_002"],
      "affected_services": ["comfyui"],
      "affected_models": ["flux"],
      "user_impact": "图像生成任务失败，对话正常"
    },
    "recommendations": [
      {
        "priority": 1,
        "action": "释放 flux 模型",
        "command": "gmae vram release --target flux",
        "expected_result": "释放 12GB 显存",
        "side_effect": "Flux 生成需重新加载"
      },
      {
        "priority": 2,
        "action": "切换到 dialogue 场景",
        "command": "gmae scene switch dialogue",
        "expected_result": "自动释放图像模型",
        "side_effect": "图像生成暂停"
      }
    ],
    "evidence_chain": [
      {"timestamp": 1756789000, "layer": "model", "event": "flux_loading_started"},
      {"timestamp": 1756789005, "layer": "gpu", "event": "vram_warning", "value": "free=3000MB"},
      {"timestamp": 1756789010, "layer": "gpu", "event": "vram_emergency", "value": "free=1800MB"},
      {"timestamp": 1756789012, "layer": "container", "event": "comfyui_oom"},
      {"timestamp": 1756789012, "layer": "task", "event": "task_001_failed"}
    ]
  }
}
```

### 2.8 观测（企业赛重点）

#### GET /api/v1/observe/workloads
虚拟机内工作负载列表。

**响应：**
```json
{
  "ok": true,
  "data": {
    "workloads": [
      {
        "id": "wl_001",
        "type": "model_service",
        "name": "comfyui",
        "container": "comfyui",
        "status": "running",
        "vram_mb": 6442,
        "cpu_pct": 15,
        "ram_mb": 2048,
        "last_activity": 1756789012,
        "busy": true
      }
    ]
  }
}
```

#### GET /api/v1/observe/topology
资源拓扑（宿主机 → GPU → 虚拟机 → 容器 → 模型）。

### 2.9 配置与日志

#### GET /api/v1/config
当前配置。

#### PUT /api/v1/config
更新配置。

#### GET /api/v1/logs
日志查询。

**查询参数：**
- `lines`: 返回行数（默认 100）
- `level`: error | warning | info | all
- `source`: 模块名过滤

---

## 3. CLI 设计

### 3.1 安装与配置

```bash
# 安装（pip 或单文件二进制）
pip install gmae-cli

# 配置连接
gmae config set host http://127.0.0.1:8787
gmae config set api-key <token>

# 查看配置
gmae config show
```

配置文件：`~/.gmae/config.json`
```json
{
  "host": "http://127.0.0.1:8787",
  "api_key": "xxx",
  "output": "human"  // human | json
}
```

### 3.2 全局参数

| 参数 | 说明 |
|------|------|
| `--host <url>` | 指定 GMae 实例地址（覆盖配置） |
| `--api-key <key>` | 指定 API Key（覆盖配置） |
| `--json` | 输出 JSON 格式（机器可读） |
| `--verbose` | 详细输出 |
| `--help` | 帮助 |

### 3.3 命令清单

#### 状态类

```bash
gmae status                    # 全局健康状态
gmae status --json             # JSON 输出
gmae vram                      # 显存台账
gmae vram --tree               # 树形显示
gmae queue                     # 队列状态
gmae queue --watch             # 实时刷新
```

**输出示例（gmae status）：**
```
GMae 状态 ────────────────────────────────────
  GPU:    RTX 4060 Ti  |  显存 8.0/16.0 GB (50%)
  场景:   image        |  QoS: ok
  容器:   comfyui ●  ollama ●  fooocus ○
  模型:   已加载 2 / 已登记 21
  队列:   运行 1  等待 2  今日完成 42
  健康:   healthy ✓
```

#### 操作类

```bash
gmae vram release --target comfyui     # 释放 ComfyUI 显存
gmae vram release --all                # 释放所有可释放显存
gmae queue submit --model sdxl --prompt "一只猫" --seed 42
gmae queue cancel <task_id>
gmae scene switch dialogue             # 切换场景
gmae models list                       # 模型列表
gmae models benchmark <model_id>       # 触发评测
```

#### QoS 与告警（企业赛）

```bash
gmae qos status                # QoS 状态与降级建议
gmae qos execute <suggestion_id>  # 执行降级建议
gmae alerts list               # 告警列表
gmae alerts list --level critical
gmae alerts ack <alert_id>     # 确认告警
gmae alerts resolve <alert_id> # 解决告警
```

#### 诊断（企业赛）

```bash
gmae diagnose <task_id>        # 诊断指定任务
gmae diagnose --auto           # 自动诊断当前异常
gmae diagnose --deep           # 深度诊断
```

**输出示例（gmae diagnose）：**
```
诊断结果 ────────────────────────────────────
  根因:   显存不足导致 OOM (置信度 92%)
  证据:
    ✓ ComfyUI 日志: CUDA out of memory
    ✓ GPU 显存峰值: 15.8GB / 16GB
    ✓ 同时加载: sdxl + flux

  影响范围:
    任务: task_001, task_002
    服务: comfyui
    用户: 图像生成失败，对话正常

  建议:
    1. [立即] 释放 flux模型 → gmae vram release --target flux
       预计释放 12GB，副作用: Flux需重新加载
    2. [备选] 切换到 dialogue 场景 → gmae scene switch dialogue
```

#### 观测（企业赛）

```bash
gmae observe workloads         # 工作负载列表
gmae observe topology          # 资源拓扑
gmae observe --watch           # 实时观测
```

#### 配置与日志

```bash
gmae config show
gmae config set <key> <value>
gmae logs --lines 50
gmae logs --level error
```

### 3.4 输出格式

**人类可读（默认）：**
- 表格、进度条、颜色标记
- 关键指标高亮
- 操作结果明确

**JSON 模式（--json）：**
- 直接透传 API 响应
- 适合脚本解析和管道操作

```bash
# 脚本示例：显存低于 4GB 时自动释放
if [ $(gmae vram --json | jq '.data.free_mb') -lt 4096 ]; then
  gmae vram release --all
fi
```

---

## 4. 实施路线

### 阶段1：个人赛（当前）
- [ ] API 统一到 `/api/v1/` 前缀（兼容旧 `/api/`）
- [ ] 统一响应格式（ok/data/error/meta）
- [ ] 统一错误码体系
- [ ] CLI 骨架 + 5个核心命令（status/vram/queue/models/config）
- [ ] 认证机制统一

### 阶段2：Linux 拓展 + 企业赛
- [ ] 虚拟机内探针（Agent）
- [ ] 告警 API（alerts）
- [ ] 诊断 API（diagnose）
- [ ] 观测 API（observe）
- [ ] CLI 扩展命令（alerts/diagnose/observe）
- [ ] ZSvirt API 集成

### 阶段3：完善
- [ ] 分布式链路追踪（OpenTelemetry）
- [ ] 多实例管理（CLI 管理多个 GMae 节点）
- [ ] Webhook 回调

---

## 5. 与现有代码的映射

| 现有模块 | API 对应 | CLI 对应 |
|---------|---------|---------|
| services/status.py | GET /status | gmae status |
| services/vram_helper.py | GET /vram/*, POST /vram/release | gmae vram |
| engine/budget.py | GET /vram/budget | gmae vram budget |
| engine/queue.py | GET/POST /queue/* | gmae queue |
| engine/admission_gate.py | POST /queue/submit（准入逻辑） | — |
| engine/qos.py | GET /qos/*, POST /qos/execute | gmae qos |
| services/scene.py | GET/POST /scene | gmae scene |
| engine/scanner.py | GET/POST /models | gmae models |
| core/logger.py | GET /logs | gmae logs |
| （新增）engine/diagnose.py | POST /diagnose | gmae diagnose |
| （新增）engine/alert_manager.py | GET/POST /alerts | gmae alerts |
| （新增）services/observer.py | GET /observe/* | gmae observe |

---

## 6. 待决策问题

1. **旧 API 兼容期**：`/api/` 旧接口保留多久？建议保留到 v2.0 大赛提交后
2. **CLI 实现语言**：Python（click/typer）还是 Go（单文件二进制）？建议 Python，与主项目同语言
3. **API 限流**：是否需要？个人赛单用户不需要，企业赛多租户需要
4. **WebSocket 支持**：实时状态推送是否需要？建议阶段2再加

---

*本文档是设计蓝本，主公确认后进入实施阶段。*
