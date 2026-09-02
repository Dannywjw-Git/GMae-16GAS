# GMae v2.0 前端重构 + 观测层后端 执行计划

> **版本**：v1.0
> **创建日期**：2026-09-01
> **分支**：refactor/v2
> **预计工期**：6天
> **前置条件**：后端API格式已统一迁移到 v1 {ok, data, error, meta}

---

## 一、目标

1. **前端信息架构重构**：从9个页面精简到5个页面，按"观测→诊断→调度"分层
2. **观测层后端支撑**：动态服务健康探测 + 结构化事件系统
3. **诊断中心**：故障时间机器（时间点四层指标快照）
4. **组件库**：统一UI组件，提升一致性和开发效率

---

## 二、6天执行计划

### D1：基础 + 总览页

| 工作项 | 内容 | 产出 |
|--------|------|------|
| 组件库 | StatusCard / DataTable / TrendChart / TabNav / Modal / Toast / Confirm / ProgressBar | `web/js/components/` |
| 动态服务清单 | registry.json 新增 monitored_services 配置 + 服务注册/发现 | `core/service_registry.py` |
| 总览页 | 健康四卡片 + 告警面板 + 关键指标趋势 + 快速操作 | `web/js/pages/dashboard.js` |
| 导航重构 | 左侧导航从9项减到5项 | `web/js/core/router.js` |

**验证**：总览页数据准确，告警实时刷新，快速操作可用

---

### D2：观测中心-后端

| 工作项 | 内容 | 产出 |
|--------|------|------|
| 服务健康探测引擎 | 后台线程，按配置动态探测，记录状态/延迟/错误率 | `observability/health_probe.py` |
| 结构化事件系统 | log_event 升级，增加 level/service/metadata/related_metrics | `core/events.py` |
| 事件存储 | 内存环形缓冲500条 + 持久化 events.jsonl | `core/events.py` |
| 后端API | `GET /api/v1/health/services` + `GET /api/v1/events` | `api/routes.py` |

**验证**：服务健康延迟数据真实，事件可按服务/级别/时间筛选

---

### D3：观测中心-前端

| Tab | 内容 |
|-----|------|
| 显存账本 | 显存分布堆叠条 + 进程明细表格 + 历史趋势 + 强制驱逐 |
| 服务健康 | 服务状态列表（状态/延迟/错误率）+ 服务详情（CPU/内存/GPU/最近错误） |
| 事件日志 | 结构化事件流 + 筛选（级别/服务/时间/关键词）+ 事件详情（关联指标） |

**验证**：三个Tab数据准确，交互流畅

---

### D4：诊断中心

| 工作项 | 内容 |
|--------|------|
| 指标历史缓冲 | 各层指标（GPU/容器/服务/网络）定时采样，保留最近1小时 |
| 故障时间线 | 时间轴视图，标注异常事件，跨层指标叠加 |
| 四层快照 | 选时间点，展示应用/容器/GPU/宿主机四层指标全量 |
| 一键健康检查 | 检查GPU/容器/网络/磁盘/模型，生成报告 |
| 后端API | `GET /api/v1/diagnose/timeline?timestamp=` + `GET /api/v1/diagnose/health-check` |

**验证**：能回答"昨天22:17那次失败时，GPU显存多少？容器CPU多少？网络通不通？"

---

### D5：工作负载

| Tab | 内容 |
|-----|------|
| 模型登记台 | 已安装/已加载模型 + 性能基准（延迟/吞吐量）+ 加载/卸载 |
| 任务队列 | 队列概览 + 任务列表 + 失败详情（错误分类+重试建议） |
| 场景切换 | 场景列表 + 切换进度 + 预算预检 + 切换历史 |

**验证**：三个Tab功能完整，与后端API正确对接

---

### D6：设置 + 全量回归

| 工作项 | 内容 |
|--------|------|
| 设置页 | 通用/阈值/用户/API 四个Tab |
| 服务监控管理 | 添加/删除/编辑监控服务，导入/导出配置 |
| 全量UI走查 | 5个页面每个功能点验证 |
| 端到端测试 | 场景切换 → 生成任务 → 显存释放 全流程 |
| 性能优化 | 首屏加载 < 2秒，轮询不卡 |

**验证**：全量测试通过，无明显bug

---

## 三、动态服务清单设计

### 配置格式（registry.json）

```json
{
  "monitored_services": [
    {
      "id": "comfyui",
      "name": "ComfyUI",
      "type": "docker",
      "container": "comfyui",
      "url": "http://127.0.0.1:8188/system_stats",
      "port": 8188,
      "probe_interval": 10,
      "timeout": 5,
      "category": "generation"
    }
  ]
}
```

### 探测方式

| type | 探测方法 | 成功标准 |
|------|---------|---------|
| `docker` | docker inspect + 端口探测 | 容器运行中 + 端口可达 |
| `http` | HTTP GET | 状态码 200/301/302 |
| `tcp` | TCP 连接 | 端口可达 |
| `custom` | 自定义脚本 | 退出码 0 |

### 采集指标

- `status`: running / stopped / unreachable / timeout
- `latency_ms`: 最近一次探测延迟
- `error_rate`: 最近10次探测失败率
- `last_check`: 最后探测时间
- `last_error`: 最后错误信息
- `history`: 最近1小时状态变化

### 用户管理

设置页 → 服务监控 → 添加/删除/编辑 + 导入/导出

**自动发现**：启动时扫描 Docker 容器，自动建议添加（用户确认）

---

## 四、结构化事件系统

### 事件格式

```python
log_event(
    event_type="scene_switch",
    level="info",              # info / warning / error / critical
    service="scene",
    message="切换到 comfy 场景",
    metadata={"scene": "comfy", "duration_ms": 8500},
    related_metrics={
        "gpu_free_mb": 6000,
        "comfyui_status": "running"
    }
)
```

### 存储

- 内存环形缓冲：500条
- 持久化：`logs/events.jsonl`（最近10000条）

### 查询API

`GET /api/v1/events?service=&level=&from=&to=&keyword=`

---

## 五、组件库清单

| 组件 | 用途 | 来源 |
|------|------|------|
| `StatusCard` | 状态卡片（带状态点/趋势） | 新建 |
| `DataTable` | 数据表格（排序/筛选/分页） | 新建 |
| `TrendChart` | 趋势图（轻量canvas） | 新建 |
| `TabNav` | Tab导航 | 新建 |
| `Modal` | 弹窗 | 复用 |
| `Toast` | 提示 | 复用 |
| `Confirm` | 确认框 | 复用 |
| `ProgressBar` | 进度条 | 复用 |

**不引入第三方UI库**，保持原生JS架构

---

## 六、5个页面信息架构

### 1. 总览 Dashboard
- 健康四卡片（GPU/容器/模型/队列）
- 告警面板（最近异常，按严重程度排序）
- 关键指标趋势（显存/延迟/队列长度）
- 快速操作（一键释放/场景切换）

### 2. 观测中心 Observability
- Tab1：显存账本（进程明细+趋势+驱逐）
- Tab2：服务健康（状态/延迟/错误率+详情）
- Tab3：事件日志（结构化事件+筛选+详情）

### 3. 诊断中心 Diagnostics
- Tab1：故障时间线（跨层指标叠加+异常标注）
- Tab2：四层快照（应用/容器/GPU/宿主机）
- Tab3：健康检查（一键全栈检查+报告）

### 4. 工作负载 Workloads
- Tab1：模型登记台（已安装/已加载+性能基准）
- Tab2：任务队列（概览+列表+失败详情）
- Tab3：场景切换（列表+进度+预算+历史）

### 5. 设置 Settings
- 通用（端口/日志级别/缓存）
- 阈值（显存告警/QoS/准入控制）
- 用户（管理员/会话）
- API（Token/服务监控管理）

---

## 七、验证标准

1. **API测试**：`python tests/api_test.py` 55/55 通过
2. **UI走查**：5个页面每个功能点手动验证
3. **端到端**：场景切换 → 生成任务 → 显存释放 全流程
4. **性能**：首屏加载 < 2秒，轮询不卡
5. **诊断能力**：能回答"某时间点失败时，各层指标是什么"

---

## 八、风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 后端探测线程影响性能 | 探测间隔可配置，默认10秒，异步执行 |
| 事件存储增长过快 | 环形缓冲限制，持久化文件滚动 |
| 前端重构引入bug | 每个页面完成后立即验证，自动化测试兜底 |
| 诊断数据不足 | 第一版只做最近1小时，后续扩展 |

---

*本计划是阶段2的执行蓝图，每天完成后更新进度。*
