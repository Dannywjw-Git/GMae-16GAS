# 16GAS 重构接口契约（API Contract）

> **文档性质**：接口契约（冻结，前后端共同遵守，修改需经主公同意）
> **创建日期**：2026-09-01
> **适用范围**：S1-S6 重构期间所有新增/修改的 API
> **规则**：本文档定义的请求/响应格式是唯一事实来源。后端实现必须严格匹配，前端必须按此消费。任何偏差必须先修改本文档，再改代码。

---

## 一、通用约定

### 1.1 统一响应格式（v1 格式，所有 API 必须遵守）

```json
{
  "ok": true,
  "data": { ... },
  "error": null,
  "meta": {
    "timestamp": "2026-09-01T12:00:00.000Z",
    "cached": false,
    "cached_at": null,
    "stale": false
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| ok | boolean | 请求是否成功 |
| data | object/null | 成功时的返回数据，失败时为 null |
| error | string/null | 失败时的错误信息，成功时为 null |
| meta.timestamp | string | 服务器处理时间（ISO 8601 UTC） |
| meta.cached | boolean | 是否来自缓存（S1 缓存层，默认 false） |
| meta.cached_at | string/null | 缓存时间（ISO 8601，未缓存为 null） |
| meta.stale | boolean | 是否是过期缓存（后台刷新中返回旧数据） |

**错误响应示例**：
```json
{
  "ok": false,
  "data": null,
  "error": "alert_type is required",
  "meta": { "timestamp": "...", "cached": false, "cached_at": null, "stale": false }
}
```

### 1.2 认证

- **方式**：Session Cookie（浏览器登录后自动携带）或 `X-API-Key` 请求头（脚本/自动化）
- **公开路径**（免认证）：`/api/health`、`/api/auth/status`、`/api/auth/setup`、`/api/auth/login`、`/api/auth/forgot`、`/api/auth/reset`
- **所有其他路径**：必须认证，未认证返回 `401 Unauthorized`
- **401 响应格式**：
```json
{ "ok": false, "data": null, "error": "authentication required", "meta": {...} }
```

### 1.3 HTTP 状态码

| 状态码 | 含义 | 使用场景 |
|--------|------|---------|
| 200 | 成功 | 所有成功响应 |
| 400 | 请求参数错误 | 缺少必填参数、参数格式错误 |
| 401 | 未认证 | 未登录或 Token 无效 |
| 403 | 无权限 | 认证通过但无权操作（如保护进程驱逐） |
| 404 | 资源不存在 | 告警类型不存在、任务不存在等 |
| 409 | 冲突 | 重复提交、状态冲突 |
| 500 | 服务器内部错误 | 未捕获异常 |

### 1.4 参数规范

- **Query 参数**：GET 请求的过滤/分页参数，全部用 snake_case
- **Body 参数**：POST/PUT 请求的 JSON body，全部用 snake_case
- **时间格式**：ISO 8601 UTC（`2026-09-01T12:00:00.000Z`）
- **分页**：`limit`（默认 50，最大 500）+ `offset`（默认 0），或 `cursor`（游标分页，二选一）
- **布尔参数**：`true`/`false` 字符串或 `1`/`0`

---

## 二、S1 轻量采集优化（无新增 API，改造现有 API）

### 2.1 GET /api/status（改造）

**变更点**：响应 meta 增加缓存相关字段。

**响应 data 结构**（保持不变，仅 meta 增加字段）：
```json
{
  "ok": true,
  "data": {
    "scene": "dialogue",
    "gpu": {
      "total_mb": 16380,
      "used_mb": 5734,
      "free_mb": 10646,
      "utilization_pct": 35
    },
    "vram_ledger": {
      "danger_level": "safe",
      "free_mb": 10646,
      "breakdown": {
        "base_noise_mb": 3584,
        "ollama_mb": 4300,
        "comfyui_mb": 2150,
        "desktop_mb": 800,
        "other_mb": 0,
        "free_mb": 10646
      }
    },
    "services": {
      "ollama": { "ok": true, "container": "ollama", "loaded_models": ["qwen3.5:9b"] },
      "comfyui": { "ok": false, "container": "comfyui" },
      "fooocus": { "ok": false, "container": "fooocus" },
      "owui": { "ok": true, "container": "open-webui-open-webui-1" }
    },
    "qos": { "level": "GREEN", "message": "显存充足" },
    "desktop_vram": { "total_mb": 800, "processes": [...] },
    "queue": { "running": 0, "pending": 0, "completed": 12 }
  },
  "meta": {
    "timestamp": "2026-09-01T12:00:00.000Z",
    "cached": true,
    "cached_at": "2026-09-01T11:59:55.000Z",
    "stale": false
  }
}
```

**meta.cached 语义**：
- `cached: true, stale: false`：正常缓存命中（10 秒 TTL 内）
- `cached: true, stale: true`：缓存已过期，后台正在刷新，返回的是旧数据
- `cached: false`：实时数据（缓存失效后首次请求或写操作后）

**前端处理建议**：
- `stale: true` 时，页面显示"数据更新中..."轻微提示，不阻塞
- `cached_at` 可显示"数据更新于 X 秒前"

---

## 三、S2 事件关联引擎（新增 4 个 API）

### 3.1 GET /api/events/timeline

**用途**：获取事件时间线，支持多维度过滤。

**认证**：需要

**Query 参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| start_time | string | 否 | null | ISO 8601 起始时间 |
| end_time | string | 否 | null | ISO 8601 结束时间 |
| category | string | 否 | null | 事件类别过滤（vram/container/model/task/user_action/system/guard） |
| level | string | 否 | null | 事件级别过滤（debug/info/warning/error/critical） |
| source | string | 否 | null | 事件来源模块名 |
| event | string | 否 | null | 事件类型名（精确匹配） |
| limit | integer | 否 | 100 | 返回数量，最大 500 |

**响应 data**：
```json
{
  "events": [
    {
      "timestamp": "2026-09-01T12:05:23.000Z",
      "category": "task",
      "level": "info",
      "source": "queue_worker",
      "event": "task_submit",
      "message": "任务提交：flux 高分辨率生成",
      "metadata": {
        "task_id": "001",
        "model": "flux",
        "workflow": "flux_q5",
        "params": { "width": 2048, "height": 2048 }
      }
    }
  ],
  "count": 1
}
```

**事件对象字段定义**（详见《数据结构定义文档》§2.1）：
- `timestamp`：ISO 8601 UTC，事件发生时间
- `category`：7 类枚举，事件大类
- `level`：5 级枚举，事件严重程度
- `source`：产生事件的模块名（字符串，自由文本）
- `event`：事件类型名（snake_case，如 `task_submit`、`vram_state_change`）
- `message`：人类可读描述（中文，1 句话）
- `metadata`：附加数据（任意 JSON object，可为空对象 `{}`）

### 3.2 GET /api/events/stats

**用途**：获取事件统计（最近时间窗内各类别数量）。

**认证**：需要

**Query 参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| seconds | integer | 否 | 300 | 统计时间窗（秒） |

**响应 data**：
```json
{
  "stats": {
    "vram": 3,
    "container": 1,
    "model": 2,
    "task": 5,
    "user_action": 2,
    "system": 0,
    "guard": 1
  },
  "window_seconds": 300,
  "total": 14
}
```

### 3.3 POST /api/diagnose

**用途**：执行根因诊断，返回 Top3 根因候选。

**认证**：需要

**Body 参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| alert_type | string | 是 | — | 告警类型（如 vram_critical/vram_danger/container_crash/service_down/queue_backlog/latency_high） |
| alert_time | string | 否 | 当前时间 | 告警发生时间（ISO 8601） |
| window_seconds | integer | 否 | 300 | 回溯事件时间窗（秒） |
| current_status | object | 否 | null | 当前系统状态（/api/status 的 data，不传则后端自行获取） |

**请求示例**：
```json
{
  "alert_type": "vram_critical",
  "window_seconds": 300
}
```

**响应 data**：
```json
{
  "alert_type": "vram_critical",
  "window_seconds": 300,
  "total_events": 12,
  "count": 3,
  "root_causes": [
    {
      "rule_id": "RC-001",
      "rule_name": "ComfyUI 生成任务显存溢出",
      "root_cause": "ComfyUI 生成任务显存溢出，高分辨率或大批量生成导致显存占用超出预期",
      "confidence": 85,
      "suggested_action": "1. 暂停 ComfyUI 队列任务\n2. 降低生成分辨率或批量大小\n3. 执行 /api/free 释放显存",
      "related_events": [
        {
          "timestamp": "2026-09-01T12:05:23.000Z",
          "category": "task",
          "event": "task_submit",
          "message": "任务提交：flux 高分辨率生成"
        }
      ],
      "related_events_count": 3
    },
    {
      "rule_id": "RC-002",
      "rule_name": "大模型加载导致显存不足",
      "root_cause": "大参数模型（>7B）加载占用大量显存，与其他服务并发导致显存不足",
      "confidence": 80,
      "suggested_action": "1. 卸载大模型\n2. 切换到小模型（如 qwen3:0.6b）\n3. 降低 context 长度",
      "related_events": [...],
      "related_events_count": 2
    },
    {
      "rule_id": "RC-005",
      "rule_name": "桌面应用占用显存",
      "root_cause": "桌面 GPU 应用占用大量显存，与 AI 服务竞争显存资源",
      "confidence": 75,
      "suggested_action": "1. 关闭桌面 GPU 应用\n2. 检查是否误开游戏\n3. 在 /api/desktop_vram 中查看具体进程",
      "related_events": [...],
      "related_events_count": 1
    }
  ]
}
```

**无匹配时的响应**：
```json
{
  "alert_type": "vram_critical",
  "window_seconds": 300,
  "total_events": 2,
  "count": 1,
  "root_causes": [
    {
      "rule_id": "DEFAULT",
      "rule_name": "默认诊断",
      "root_cause": "未识别到明确根因，建议检查事件时间线。最近 10 条事件已附带。",
      "confidence": 0,
      "suggested_action": "查看事件时间线，手动排查",
      "related_events": [/* 最近 10 条事件 */],
      "related_events_count": 10
    }
  ]
}
```

**根因候选对象字段定义**（详见《数据结构定义文档》§2.3）：
- `rule_id`：规则 ID（RC-001 ~ RC-009，或 DEFAULT）
- `rule_name`：规则名称
- `root_cause`：根因描述（中文，1-2 句话）
- `confidence`：置信度（0-100 整数）
- `suggested_action`：处置建议（中文，编号步骤，用 `\n` 分隔）
- `related_events`：关联事件列表（事件对象的精简版，只含 timestamp/category/event/message）
- `related_events_count`：关联事件总数

### 3.4 GET /api/diagnose/rules

**用途**：获取所有诊断规则的元信息（用于前端展示规则列表/调试）。

**认证**：需要

**响应 data**：
```json
{
  "rules": [
    {
      "id": "RC-001",
      "name": "ComfyUI 生成任务显存溢出",
      "description": "ComfyUI 正在运行且最近有任务提交，显存进入危险状态",
      "root_cause": "ComfyUI 生成任务显存溢出...",
      "confidence": 85,
      "suggested_action": "1. 暂停 ComfyUI 队列任务..."
    }
  ],
  "count": 9
}
```

---

## 四、S3 故障场景库 + 告警降噪（新增 5 个 API）

### 4.1 GET /api/alerts

**用途**：获取活跃告警列表。

**认证**：需要

**响应 data**：
```json
{
  "alerts": [
    {
      "alert_type": "vram_critical",
      "level": "critical",
      "message": "显存剩余 0.8GB，存在 OOM 死机风险",
      "metadata": { "vram_free_mb": 800, "danger_level": "critical" },
      "first_triggered": "2026-09-01T12:00:15.000Z",
      "last_triggered": "2026-09-01T12:05:23.000Z",
      "count": 3,
      "status": "active",
      "duration_seconds": 308,
      "escalated": false
    }
  ],
  "count": 1
}
```

**告警对象字段定义**（详见《数据结构定义文档》§2.4）：
- `alert_type`：告警类型（snake_case，如 `vram_critical`）
- `level`：级别（info/warning/danger/critical）
- `message`：告警消息（中文）
- `metadata`：附加数据（任意 object）
- `first_triggered`：首次触发时间（ISO 8601）
- `last_triggered`：最近触发时间（ISO 8601）
- `count`：触发次数（聚合计数）
- `status`：状态（active/resolved/silenced）
- `duration_seconds`：持续时长（秒，仅 active 时有意义）
- `escalated`：是否已升级（boolean）

### 4.2 GET /api/alerts/history

**用途**：获取告警历史记录。

**认证**：需要

**Query 参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| limit | integer | 否 | 50 | 返回数量，最大 100 |
| level | string | 否 | null | 级别过滤 |
| action | string | 否 | null | 动作过滤（new/aggregated/resolved/silenced/escalated） |

**响应 data**：
```json
{
  "history": [
    {
      "timestamp": "2026-09-01T12:05:23.000Z",
      "action": "aggregated",
      "alert_type": "vram_critical",
      "level": "critical",
      "message": "显存剩余 0.8GB，存在 OOM 死机风险",
      "count": 3
    }
  ],
  "count": 1
}
```

**历史记录对象字段**：
- `timestamp`：记录时间
- `action`：动作类型（new 新建/aggregated 聚合/resolved 解决/silenced 静默/escalated 升级）
- `alert_type`：告警类型
- `level`：级别
- `message`：消息
- `count`：当时的触发次数

### 4.3 POST /api/alerts/{alert_type}/silence

**用途**：静默某类告警一段时间。

**认证**：需要

**路径参数**：
- `alert_type`：告警类型（URL 编码）

**Body 参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| duration_minutes | integer | 否 | 30 | 静默时长（分钟） |

**请求示例**：
```json
{ "duration_minutes": 30 }
```

**响应 data**：
```json
{
  "alert_type": "vram_critical",
  "silenced_until": "2026-09-01T12:35:00.000Z",
  "duration_minutes": 30
}
```

### 4.4 POST /api/alerts/{alert_type}/resolve

**用途**：手动解决（移除）一个活跃告警。

**认证**：需要

**路径参数**：
- `alert_type`：告警类型

**响应 data**：
```json
{
  "alert_type": "vram_critical",
  "resolved": true
}
```

**告警不存在时**：返回 404，`resolved: false`。

### 4.5 GET /api/alerts/silenced

**用途**：获取当前静默中的告警列表。

**认证**：需要

**响应 data**：
```json
{
  "silenced": [
    {
      "alert_type": "vram_warning",
      "silenced_until": "2026-09-01T12:30:00.000Z",
      "remaining_seconds": 1520
    }
  ],
  "count": 1
}
```

---

## 五、S5 拓扑图 + 健康度（可选，新增 1 个 API）

### 5.1 GET /api/health/scores（可选，S5 时实现）

**用途**：获取各服务的健康度评分。

**认证**：需要

**响应 data**：
```json
{
  "scores": [
    {
      "service": "ollama",
      "score": 85,
      "level": "good",
      "dimensions": {
        "availability": 100,
        "response_speed": 70,
        "stability": 100,
        "resource_health": 70
      }
    }
  ],
  "count": 6
}
```

**健康度对象字段**：
- `service`：服务名
- `score`：总分（0-100）
- `level`：等级（good ≥80 / warning 50-79 / critical <50 / offline =0）
- `dimensions.availability`：可用性（40% 权重）
- `dimensions.response_speed`：响应速度（30% 权重）
- `dimensions.stability`：稳定性（20% 权重）
- `dimensions.resource_health`：资源健康（10% 权重）

---

## 六、现有 API 变更登记

以下现有 API 在重构中发生变更，必须保持向后兼容：

| API | 变更类型 | 变更内容 | 兼容性 |
|-----|---------|---------|--------|
| GET /api/status | meta 扩展 | meta 增加 cached/cached_at/stale 字段 | ✅ 向后兼容（新增字段，旧字段不变） |
| GET /api/health | 无变更 | 保持直接返回 health_check() 原始 dict（顶层含 services，watchdog 兼容） | ✅ 不变 |
| 所有写操作 | 副作用 | 执行后失效 S1 状态缓存 | ✅ 不影响响应格式 |

---

## 七、接口变更管理规则

1. **本文档是唯一契约来源**：后端实现和前端消费都必须严格匹配本文档
2. **变更流程**：发现需要变更接口时，先修改本文档（标注变更日期和原因），再改代码。禁止先改代码再补文档
3. **向后兼容**：新增字段必须有默认值，不得删除或重命名现有字段（除非主公明确同意破坏性变更）
4. **每阶段自检**：每个阶段完成后，对照本文档检查所有新增/修改的 API 是否匹配
5. **蓝图偏差**：新增 API 如与蓝图不一致，登记到《项目进度跟踪》第八章偏差登记表，不擅自改蓝图

---

*本文档由 2026-09-01 会话创建，作为 S1-S6 重构的接口契约。任何 API 格式变更必须先更新本文档。*
