# 16GAS 重构数据结构定义（Data Schema）

> **文档性质**：数据结构契约（冻结，跨模块共享，修改需经主公同意）
> **创建日期**：2026-09-01
> **适用范围**：S1-S6 重构期间所有新增模块的共享数据结构
> **规则**：本文档定义的对象字段是唯一事实来源。所有模块（后端引擎/API端点/前端）必须使用相同的字段名和类型。任何偏差必须先修改本文档，再改代码。

---

## 一、通用约定

### 1.1 命名规范

- **字段名**：全部 snake_case（如 `first_triggered`、`vram_free_mb`）
- **时间字段**：ISO 8601 UTC 字符串（如 `2026-09-01T12:00:00.000Z`），字段名以 `_at` 或 `_time` 结尾
- **时长字段**：整数秒（如 `duration_seconds`），字段名以 `_seconds` 结尾
- **布尔字段**：true/false，字段名以 `is_` 或动词开头（如 `is_cached`、`escalated`）
- **ID 字段**：字符串，字段名以 `_id` 结尾（如 `rule_id`、`task_id`）
- **计数字段**：整数，字段名以 `_count` 结尾（如 `related_events_count`）

### 1.2 类型约定

| 类型 | 说明 | 示例 |
|------|------|------|
| string | 字符串 | `"vram_critical"` |
| integer | 整数 | `85` |
| number | 浮点数 | `10.6` |
| boolean | 布尔 | `true` |
| object | JSON 对象 | `{ "key": "value" }` |
| array | 数组 | `[1, 2, 3]` |
| null | 空值 | `null` |

### 1.3 枚举值约定

所有枚举字段的取值必须在本文档中明确定义，不得使用未定义的值。

---

## 二、核心数据结构

### 2.1 Event（事件对象）

**用途**：系统中所有事件的统一格式，event_bus 记录、时间线 API 返回、规则引擎匹配的基础数据。

**模块**：`engine/event_bus.py`（生产）、`api/endpoints/events.py`（消费）、`engine/diagnose.py`（消费）、前端事件时间线组件（消费）

**字段定义**：

| 字段 | 类型 | 必填 | 说明 | 枚举/约束 |
|------|------|------|------|----------|
| timestamp | string | 是 | 事件发生时间（ISO 8601 UTC） | 由 event_bus 自动生成 |
| category | string | 是 | 事件大类 | 见 §3.1 EventCategory |
| level | string | 是 | 事件严重程度 | 见 §3.2 EventLevel |
| source | string | 是 | 产生事件的模块名 | 自由文本，如 `qos_engine`、`queue_worker`、`docker_events` |
| event | string | 是 | 事件类型名 | snake_case，见 §3.3 事件类型命名规范 |
| message | string | 是 | 人类可读描述（中文，1 句话） | 不超过 200 字符 |
| metadata | object | 是 | 附加数据 | 任意 JSON object，无附加数据时为 `{}` |

**示例**：
```json
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
```

**精简版（用于根因候选的 related_events）**：
```json
{
  "timestamp": "2026-09-01T12:05:23.000Z",
  "category": "task",
  "event": "task_submit",
  "message": "任务提交：flux 高分辨率生成"
}
```
精简版只保留 4 个字段：`timestamp`、`category`、`event`、`message`。

---

### 2.2 Rule（诊断规则对象）

**用途**：根因推断规则引擎的规则定义，注册到 rule_engine，用于匹配事件并输出根因。

**模块**：`engine/diagnose.py`（定义+注册）、`api/endpoints/diagnose.py`（查询）

**字段定义**：

| 字段 | 类型 | 必填 | 说明 | 枚举/约束 |
|------|------|------|------|----------|
| id | string | 是 | 规则 ID | 格式 `RC-XXX`，如 `RC-001` |
| name | string | 是 | 规则名称 | 中文，不超过 50 字符 |
| description | string | 是 | 规则描述 | 中文，1-2 句话 |
| condition | function | 是 | 匹配函数 | Python callable，签名 `(events: list[Event], status: dict) -> bool`，不序列化 |
| root_cause | string | 是 | 根因描述 | 中文，1-2 句话 |
| confidence | integer | 是 | 置信度 | 0-100 整数 |
| suggested_action | string | 是 | 处置建议 | 中文，编号步骤，用 `\n` 分隔 |
| related_events_query | object | 是 | 关联事件查询条件 | 见下方 |

**related_events_query 字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| category | string | 否 | 按类别过滤 |
| event | string | 否 | 按事件类型过滤（精确匹配） |
| source | string | 否 | 按来源过滤 |

**示例（序列化版本，condition 不包含）**：
```json
{
  "id": "RC-001",
  "name": "ComfyUI 生成任务显存溢出",
  "description": "ComfyUI 正在运行且最近有任务提交，显存进入危险状态",
  "root_cause": "ComfyUI 生成任务显存溢出，高分辨率或大批量生成导致显存占用超出预期",
  "confidence": 85,
  "suggested_action": "1. 暂停 ComfyUI 队列任务\n2. 降低生成分辨率或批量大小\n3. 执行 /api/free 释放显存",
  "related_events_query": {
    "category": "task",
    "event": "task_submit"
  }
}
```

**初始规则清单（9 条）**：

| ID | 名称 | 置信度 | 对应场景 |
|----|------|--------|---------|
| RC-001 | ComfyUI 生成任务显存溢出 | 85 | FC-001 |
| RC-002 | 大模型加载导致显存不足 | 80 | FC-001 |
| RC-003 | Fooocus 场景切换后显存未释放 | 70 | FC-001 |
| RC-004 | 多服务并发占用累积 | 60 | FC-001 |
| RC-005 | 桌面应用占用显存 | 75 | FC-001 |
| RC-006 | 容器异常退出/频繁重启 | 75 | FC-002 |
| RC-007 | 推理延迟升高 | 65 | FC-003 |
| RC-008 | 任务队列堆积 | 55 | FC-004 |
| RC-009 | 服务不可达 | 80 | FC-005 |

---

### 2.3 RootCauseCandidate（根因候选对象）

**用途**：诊断 API 返回的根因候选结果，前端诊断中心展示。

**模块**：`engine/diagnose.py`（生产）、`api/endpoints/diagnose.py`（输出）、前端诊断中心（消费）

**字段定义**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| rule_id | string | 是 | 匹配的规则 ID（RC-001 ~ RC-009，或 DEFAULT） |
| rule_name | string | 是 | 规则名称 |
| root_cause | string | 是 | 根因描述 |
| confidence | integer | 是 | 置信度（0-100） |
| suggested_action | string | 是 | 处置建议（编号步骤，`\n` 分隔） |
| related_events | array | 是 | 关联事件列表（Event 精简版，见 §2.1） |
| related_events_count | integer | 是 | 关联事件总数 |

**示例**：
```json
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
}
```

---

### 2.4 Alert（告警对象）

**用途**：告警管理器的活跃告警，告警 API 返回，前端告警中心展示。

**模块**：`engine/alert_manager.py`（生产）、`api/endpoints/alerts.py`（输出）、前端告警中心（消费）

**字段定义**：

| 字段 | 类型 | 必填 | 说明 | 枚举/约束 |
|------|------|------|------|----------|
| alert_type | string | 是 | 告警类型 | snake_case，如 `vram_critical`、`container_restart` |
| level | string | 是 | 告警级别 | 见 §3.4 AlertLevel |
| message | string | 是 | 告警消息（中文） | 不超过 200 字符 |
| metadata | object | 是 | 附加数据 | 任意 JSON object |
| first_triggered | string | 是 | 首次触发时间（ISO 8601） | |
| last_triggered | string | 是 | 最近触发时间（ISO 8601） | |
| count | integer | 是 | 触发次数（聚合计数） | ≥1 |
| status | string | 是 | 告警状态 | 见 §3.5 AlertStatus |
| duration_seconds | integer | 否 | 持续时长（秒） | 仅 active 状态时有意义，API 输出时计算 |
| escalated | boolean | 是 | 是否已升级 | 默认 false |

**示例**：
```json
{
  "alert_type": "vram_critical",
  "level": "critical",
  "message": "显存剩余 0.8GB，存在 OOM 死机风险",
  "metadata": {
    "vram_free_mb": 800,
    "danger_level": "critical"
  },
  "first_triggered": "2026-09-01T12:00:15.000Z",
  "last_triggered": "2026-09-01T12:05:23.000Z",
  "count": 3,
  "status": "active",
  "duration_seconds": 308,
  "escalated": false
}
```

---

### 2.5 AlertHistoryRecord（告警历史记录对象）

**用途**：告警历史记录，告警历史 API 返回。

**模块**：`engine/alert_manager.py`（生产）、`api/endpoints/alerts.py`（输出）

**字段定义**：

| 字段 | 类型 | 必填 | 说明 | 枚举/约束 |
|------|------|------|------|----------|
| timestamp | string | 是 | 记录时间（ISO 8601） | |
| action | string | 是 | 动作类型 | 见 §3.6 AlertAction |
| alert_type | string | 是 | 告警类型 | |
| level | string | 是 | 告警级别 | 见 §3.4 |
| message | string | 是 | 告警消息 | |
| count | integer | 是 | 当时的触发次数 | |

**示例**：
```json
{
  "timestamp": "2026-09-01T12:05:23.000Z",
  "action": "aggregated",
  "alert_type": "vram_critical",
  "level": "critical",
  "message": "显存剩余 0.8GB，存在 OOM 死机风险",
  "count": 3
}
```

---

### 2.6 SilencedAlert（静默中告警对象）

**用途**：当前静默中的告警列表，静默 API 返回。

**模块**：`engine/alert_manager.py`（生产）、`api/endpoints/alerts.py`（输出）

**字段定义**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| alert_type | string | 是 | 告警类型 |
| silenced_until | string | 是 | 静默截止时间（ISO 8601） |
| remaining_seconds | integer | 是 | 剩余静默时间（秒） |

**示例**：
```json
{
  "alert_type": "vram_warning",
  "silenced_until": "2026-09-01T12:30:00.000Z",
  "remaining_seconds": 1520
}
```

---

### 2.7 StatusCacheEntry（状态缓存对象）

**用途**：S1 状态缓存层的内部数据结构，不直接暴露给 API（API 通过 meta.cached 等字段间接暴露）。

**模块**：`core/status_cache.py`（内部使用）

**字段定义**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| data | object | 是 | 完整的 /api/status 响应 data（深拷贝） |
| cached_at | float | 是 | 缓存时间（epoch 秒，Python time.time()） |

**注意**：
- 缓存存储在内存中，server 重启后丢失（可接受）
- TTL：默认 10 秒，危险状态（danger/critical）时 2 秒
- 写操作后调用 `invalidate()` 清空缓存
- 后台刷新时返回旧数据，标记 `stale: true`

---

### 2.8 HealthScore（健康度评分对象，S5 可选）

**用途**：各服务的健康度评分，S5 时实现。

**模块**：`api/endpoints/status.py`（生产）、前端 Dashboard（消费）

**字段定义**：

| 字段 | 类型 | 必填 | 说明 | 枚举/约束 |
|------|------|------|------|----------|
| service | string | 是 | 服务名 | 如 `ollama`、`comfyui` |
| score | integer | 是 | 总分（0-100） | |
| level | string | 是 | 等级 | `good`（≥80）/ `warning`（50-79）/ `critical`（<50）/ `offline`（=0） |
| dimensions | object | 是 | 各维度得分 | 见下方 |

**dimensions 字段**：

| 字段 | 类型 | 必填 | 权重 | 说明 |
|------|------|------|------|------|
| availability | integer | 是 | 40% | 可用性（在线=100，离线=0，启动中=50） |
| response_speed | integer | 是 | 30% | 响应速度（<1s=100，1-3s=70，3-10s=40，>10s=10） |
| stability | integer | 是 | 20% | 稳定性（最近1小时重启次数：0次=100，1次=70，2次=40，≥3次=10） |
| resource_health | integer | 是 | 10% | 资源健康（显存占用<70%=100，70-85%=70，85-95%=40，>95%=10） |

**示例**：
```json
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
```

---

## 三、枚举值定义

### 3.1 EventCategory（事件类别）

| 值 | 说明 | 典型事件 |
|----|------|---------|
| `vram` | 显存相关 | 状态变化、显存释放、危险告警 |
| `container` | 容器相关 | 启动、停止、异常退出、重启 |
| `model` | 模型相关 | 加载、卸载、扫描、登记 |
| `task` | 任务相关 | 提交、开始、完成、失败、取消 |
| `user_action` | 用户操作 | 场景切换、手动释放、驱逐、配置修改 |
| `system` | 系统相关 | 服务启动、看门狗、缓存、Helper |
| `guard` | 门卫相关 | 进程首见、驱逐、保护拒绝 |

### 3.2 EventLevel（事件级别）

| 值 | 数值 | 说明 | 颜色 |
|----|------|------|------|
| `debug` | 10 | 调试信息（默认不显示） | 灰色 |
| `info` | 20 | 正常信息 | 蓝色/默认 |
| `warning` | 30 | 警告 | 琥珀色 |
| `error` | 40 | 错误 | 红色 |
| `critical` | 50 | 致命 | 深红 |

### 3.3 事件类型命名规范

- 格式：`{对象}_{动作}`，snake_case
- 示例：`task_submit`、`model_loaded`、`vram_state_change`、`container_die`、`process_evicted`
- 状态变化：`{对象}_state_change`，metadata 中含 `old_state` 和 `new_state`
- 生命周期：`{对象}_submit` / `{对象}_start` / `{对象}_complete` / `{对象}_fail` / `{对象}_cancel`

### 3.4 AlertLevel（告警级别）

| 值 | 说明 | 颜色 | 对应 EventLevel |
|----|------|------|----------------|
| `info` | 信息 | 蓝色 | info |
| `warning` | 警告 | 琥珀色 | warning |
| `danger` | 危险 | 红色 | error |
| `critical` | 致命 | 深红 | critical |

### 3.5 AlertStatus（告警状态）

| 值 | 说明 |
|----|------|
| `active` | 活跃（未解决、未静默） |
| `resolved` | 已解决（手动或自动消除） |
| `silenced` | 静默中（用户主动静默） |

### 3.6 AlertAction（告警历史动作）

| 值 | 说明 |
|----|------|
| `new` | 新建告警 |
| `aggregated` | 聚合（同类型告警重复触发） |
| `resolved` | 解决（手动或自动） |
| `silenced` | 静默 |
| `escalated` | 升级（持续未解决自动升级级别） |

### 3.7 DangerLevel（显存危险等级）

| 值 | 说明 | 显存范围 | 颜色 |
|----|------|---------|------|
| `safe` | 安全 | >4GB | 绿色 |
| `warning` | 警告 | 2-4GB | 琥珀色 |
| `danger` | 危险 | 1-2GB | 红色 |
| `critical` | 致命 | <1GB | 深红 |

### 3.8 QoSLevel（QoS 水位）

| 值 | 说明 | 显存范围 |
|----|------|---------|
| `GREEN` | 充足 | <8GB 已用 |
| `YELLOW` | 紧张 | 8-12GB 已用 |
| `RED` | 危险 | >12GB 已用 |

---

## 四、跨模块数据流向

```
事件生产方                    事件总线                    消费方
─────────                  ─────────                  ──────
QoS 状态机 ──record()──→  engine/event_bus.py  ──query()──→  事件时间线 API
模型管理  ──record()──→  (内存环形缓冲区     ──get_recent()→  规则引擎
任务队列  ──record()──→   + logs/events.jsonl)              告警管理器
Docker events ─record()──→                                  前端时间线组件
写操作端点 ──record()──→

规则引擎                    诊断 API                    前端
─────────                  ────────                  ──────
engine/diagnose.py  ──diagnose()──→  /api/diagnose  ──→  诊断中心
(9条规则 + 匹配算法)            (Top3 根因候选)         (根因卡片 + 时间线高亮)

告警管理器                    告警 API                    前端
─────────                  ────────                  ──────
engine/alert_manager.py ──get_active()──→ /api/alerts    ──→  告警中心
(聚合/静默/升级/历史)        ──get_history()─→ /api/alerts/history
                            ──silence()────→ /api/alerts/{type}/silence
```

---

## 五、数据结构变更管理规则

1. **本文档是唯一数据结构来源**：所有模块必须使用本文档定义的字段名和类型
2. **新增字段**：必须有默认值或标记为可选，不得破坏现有数据
3. **删除/重命名字段**：必须经主公同意，属于破坏性变更
4. **新增枚举值**：必须在本文档对应枚举表中登记，不得使用未定义的值
5. **每阶段自检**：每个阶段完成后，对照本文档检查所有新增模块的数据结构是否匹配
6. **前后端对齐**：前端开发前必须重读本文档，确保消费的数据结构与后端生产的一致

---

*本文档由 2026-09-01 会话创建，作为 S1-S6 重构的数据结构契约。任何字段/枚举变更必须先更新本文档。*
