# GMae 可观测能力增强方案 — 借鉴 ZSvirt 命题思路

> **文档性质**：开发计划（待执行）
> **创建日期**：2026-09-01
> **来源**：2026 上海开源软件应用创新大赛·智算云赛道 — ZSvirt 企业命题《面向虚拟机内部容器与智能体工作负载的全栈可观测平台》思路拆解吸收
> **决策**：不单独参加 ZSvirt 命题（大赛规则允许一人多项目，但 GMae 核心定位为显存调度，转向可观测命题会稀释差异化），将命题中有价值的理念拆解吸收进 GMae 现有产品，增强自由选题方向的竞争力
> **适用范围**：16G-AI-Studio（16GAS）调度中心 vram-console

---

## 一、背景与策略

### 1.1 为什么做这件事

GMae 当前以"16GB 消费级单卡显存编排"为核心定位，在智算云赛道自由选题方向参赛。ZSvirt 命题虽然不单独参加，但其提出的"全栈可观测+根因诊断"理念恰好命中 GMae 的能力短板：

- GMae 有显存监控和告警，但**告警只说"显存危险"，不说"为什么"**
- GMae 有结构化日志，但**事件之间没有关联**，无法回溯故障因果链
- GMae 的 `/api/status` 响应 13-17 秒偏慢，**采集方式重**，命题评审看重"低侵入采集"
- 大赛演示需要**故障注入→告警→根因展示**的完整闭环，GMae 目前只有告警没有根因

### 1.2 核心策略

**借鉴思路，不转向命题。** 从 ZSvirt 命题的 5 个目标要点中，提取 GMae 可落地的 6 个增强项，保持 GMae "显存调度"核心定位不变，在其上叠加"可观测+诊断"能力层。

**明确不做的边界**：
- 不集成 ZSvirt 虚拟化平台（GMae 是裸机 Windows + Docker Desktop 架构）
- 不引入虚拟机层和 VM 内探针（没有 VM）
- 不全盘转向 OpenTelemetry/Prometheus/Grafana 生态（保持自研轻量架构，只借鉴理念）
- 不做 Agent 任务轨迹追踪（GMae 没有 Agent 编排层）

### 1.3 能力提升预期

| 能力维度 | 增强前 | 增强后 | 关键增强项 |
|---------|-------|-------|-----------|
| 资源关联模型 | 3/10 | 6/10 | F 拓扑图 |
| 多信号采集 | 6/10 | 7/10 | E 轻量采集 |
| 工作负载识别 | 7/10 | 8/10 | C 健康度 |
| 事件关联与根因诊断 | 2/10 | 7/10 | A 事件关联引擎 + D 故障场景库 |
| 告警降噪与处置 | 5/10 | 8/10 | B 告警降噪 + D 处置闭环 |
| 虚拟机内探针 | 0/10 | 0/10 | 不做 |
| 标准可观测技术栈 | 1/10 | 3/10 | 部分借鉴理念 |
| ZSvirt 平台集成 | 0/10 | 0/10 | 不做 |

---

## 二、6 个增强项总览

| 编号 | 名称 | 优先级 | 估算工作量 | 大赛价值 | 实现难度 | 依赖 |
|------|------|-------|-----------|---------|---------|------|
| E | 轻量采集优化 | P0 | 4 人天 | 8/10 | 中 | 无（基础层） |
| A | 事件关联引擎 | P0 | 6 人天 | 9/10 | 高 | E（数据基础） |
| D | 故障场景库 | P1 | 3 人天 | 7/10 | 低 | A（规则消费方） |
| B | 告警降噪 | P1 | 2 人天 | 5/10 | 低 | 无 |
| F | 资源拓扑图 | P2 | 5 人天 | 6/10 | 中 | E（实时数据） |
| C | 健康度评分 | P2 | 1.5 人天 | 4/10 | 低 | E（指标基础） |

**合计**：P0 约 10 人天，P1 约 5 人天，P2 约 6.5 人天，总计约 21.5 人天。

**建议实施顺序**：E → A → D → B（可与 D 并行）→ F/C（视进度可选）

---

## 三、P0 增强项详解

### 3.1 E — 轻量采集优化

**对应命题要点**：低侵入采集（命题创新性评审维度 15%）

**现状问题**：
- `/api/status` 响应 13-17 秒，根因是 docker exec 串行调用（每次调用约 1-2 秒，累计 10+ 次）
- `_helper_health` 在 Windows 下未运行端口连接会挂起 10035 错误（已优化 timeout 2s→0.5s，冷路径 2007ms→681ms，但热路径仍慢）
- 命题评审看重"低侵入采集"创新点，GMae 当前的 docker exec 轮询方式偏重

**增强目标**：
- `/api/status` 热路径响应从 13-17 秒降至 <3 秒
- 在方案文档和演示中体现"低侵入采集"设计理念

**具体实施**：

#### E1. 指标缓存层（核心）
- 在 `server.py` 中新增 `StatusCache` 类，TTL 10 秒
- 缓存键：完整 status 响应 JSON
- 缓存命中时直接返回，跳过所有 docker exec
- 缓存失效时后台刷新（不阻塞请求，返回旧数据+stale标记）
- 关键 API（`/api/free`、`/api/scene`、`/api/guard/kick` 等写操作）后主动失效缓存

#### E2. Docker Events API（替代部分轮询）
- 用 Docker SDK 的 `events()` 方法（WebSocket 流式）监听容器状态变化
- 维护内存中的容器状态表（running/stopped/exited），状态变化时实时更新
- `/api/status` 中容器状态直接读内存表，不再 docker exec ps
- 注意：Docker Python SDK 可能未安装，优先用 `docker events` 命令的 subprocess 流式读取，或用 Docker REST API `http://localhost:2375/events`（需确认 Docker Desktop 是否开启 TCP API；默认用 named pipe `npipe:////./pipe/docker_engine`）

#### E3. nvidia-smi 批量查询 + 缓存
- 当前已用 `nvidia-smi --query-gpu=...` 单次批量查询，保持
- 新增 5 秒 TTL 缓存（显存变化不需要毫秒级实时）
- 显存水位危险状态（danger/critical）时缓存 TTL 缩短为 2 秒（提高灵敏度）

#### E4. 并行化 docker exec 调用
- 对无法缓存的调用（如模型加载状态 `ollama ps`），用 `concurrent.futures.ThreadPoolExecutor` 并行执行
- 当前是串行：先查 ollama，再查 comfyui，再查容器状态 → 改为并行 3 个 future
- 预期并行后这部分从 3-5 秒降至 1-2 秒

**涉及文件**：
- `16gb-ai-studio/vram-console/server.py`（核心改动：StatusCache、并行化、缓存失效）
- `16gb-ai-studio/vram-console/tests/test_api_contract.py`（新增缓存测试）

**验证方式**：
1. 连续调用 `/api/status` 5 次，第 2-5 次响应时间应 <500ms（缓存命中）
2. 调用 `/api/free` 后立即调用 `/api/status`，应返回最新数据（缓存失效生效）
3. 启动/停止一个 Docker 容器，`/api/status` 中容器状态应在 5 秒内更新（Docker events 生效）
4. 98 个现有测试全部通过（`python run_tests.py`）

**风险与注意**：
- 缓存可能导致用户看到旧数据，必须在 API 响应中加 `cached: true` 和 `cached_at` 时间戳，前端可显示"数据更新于 X 秒前"
- Docker events 流式读取需要后台线程，注意线程安全和服务停止时的优雅退出
- Windows 下 Docker REST API 默认不开启 TCP，用 named pipe 或 `docker events` 命令

---

### 3.2 A — 事件关联引擎（核心增量）

**对应命题要点**：事件关联与诊断（命题最高权重 25%）

**现状问题**：
- GMae 有结构化日志（`/api/logs` 读 `vram-console.log` 尾部），但事件孤立
- 显存危险告警只说"显存剩余 <1GB"，不解释原因
- 用户需要自己翻日志找原因，体验差，演示时缺乏"一键诊断"的冲击力

**增强目标**：
- 告警触发时自动回溯最近 5 分钟事件流，按相关性排序输出"根因候选 Top3"
- 每个根因候选含：描述、置信度、关联事件列表、处置建议
- 前端提供"事件时间线"视图和"查看根因分析"入口

**具体实施**：

#### A1. 后端：事件标准化 + 时间线 API
- 新增 `/api/events/timeline` API，参数：`start_time`、`end_time`、`limit`、`category`（可选过滤）
- 事件来源：
  - `vram-console.log` 结构化日志（已有，含 timestamp/level/event/message）
  - Docker events（E2 实施后可用，容器 start/stop/die/oob）
  - 显存状态变化（safe→warning→danger→critical 的状态跃迁事件）
  - 用户操作（场景切换、模型加载、任务提交、门卫驱逐等写操作日志）
- 统一事件格式：`{timestamp, category, level, source, event, message, metadata}`
- category 枚举：`vram`、`container`、`model`、`task`、`user_action`、`system`、`guard`

#### A2. 后端：根因推断规则引擎
- 新增 `/api/diagnose` API，参数：`alert_type`（如 `vram_critical`）、`alert_time`、`window_seconds`（默认 300）
- 规则引擎设计：if-then 规则（非 ML，保证可解释性），每条规则含：
  - `id`、`name`、`description`
  - `condition`：事件模式匹配（如 "最近 5 分钟内有 comfyui_task_submit 事件 + 当前 comfyui 容器 running + 显存从 safe 变为 critical"）
  - `root_cause`：根因描述
  - `confidence`：置信度（0-100，基于匹配条件的数量和强度）
  - `suggested_action`：处置建议
  - `related_events_query`：用于拉取关联事件的查询条件
- 初始规则集（5 条，后续 D 故障场景库扩展）：

| 规则 ID | 触发条件 | 根因 | 置信度 | 处置建议 |
|---------|---------|------|-------|---------|
| RC-001 | vram_critical + comfyui running + 最近有 task_submit | ComfyUI 生成任务显存溢出 | 85% | 暂停队列 / 降低分辨率 / 释放 ComfyUI 显存 |
| RC-002 | vram_critical + ollama 加载了 >7B 模型 + 最近有 model_load | 大模型加载导致显存不足 | 80% | 卸载大模型 / 切换到小模型 / 降低 context |
| RC-003 | vram_critical + fooocus running + 最近有 scene_switch | Fooocus 场景切换后显存未释放 | 70% | 重启 Fooocus 容器 / 切换到其他场景 |
| RC-004 | vram_danger + 多个容器同时 running + 无新任务 | 多服务并发占用累积 | 60% | 停止非必要服务 / 切换到独占场景 |
| RC-005 | vram_critical + 桌面进程显存 >2GB + 最近无容器操作 | 桌面应用（游戏/浏览器）占用显存 | 75% | 关闭桌面 GPU 应用 / 检查是否误开游戏 |

- 规则匹配算法：拉取时间窗内所有事件 → 逐条规则检查 condition → 匹配的规则按 confidence 排序 → 返回 Top3
- 未匹配任何规则时返回默认诊断："未识别到明确根因，建议检查事件时间线" + 最近 10 条事件

#### A3. 前端：事件时间线视图
- 在现有日志页（`pages/logs.js`）基础上增强，或新增"诊断"页
- 时间线组件：垂直时间轴，事件按时间倒序，不同 category 用不同颜色标记
- 事件卡片显示：时间、category 图标、event 名称（中文翻译，已有 `eventNameMap`）、message 摘要
- 支持按 category 筛选、按级别筛选、时间范围选择
- 告警状态时，时间线自动高亮与告警相关的事件（基于 diagnose 返回的 related_events）

#### A4. 前端：根因分析弹窗
- 显存危险弹窗（已有 `dangerModal`）增加"查看根因分析"按钮
- 点击后调用 `/api/diagnose`，展示根因候选 Top3：
  - 每个候选：根因描述、置信度进度条、处置建议、"查看关联事件"按钮（展开时间线并高亮）
  - 按置信度排序，最高的默认展开
- 无匹配时显示"未识别明确根因"+ 事件时间线快捷入口

**涉及文件**：
- `16gb-ai-studio/vram-console/server.py`（新增 `/api/events/timeline`、`/api/diagnose`，事件标准化模块）
- `16gb-ai-studio/vram-console/diagnose.py`（新建：规则引擎、规则集、匹配算法）
- `16gb-ai-studio/vram-console/web/js/pages/logs.js`（增强为事件时间线）
- `16gb-ai-studio/vram-console/web/js/pages/diagnose.js`（新建：根因分析页或弹窗）
- `16gb-ai-studio/vram-console/web/js/core/api.js`（新增 eventsTimeline、diagnose API 封装）
- `16gb-ai-studio/vram-console/tests/test_diagnose.py`（新建：规则引擎单元测试）

**验证方式**：
1. 模拟显存 critical 状态（可用 `--vram` 测试模式或手动构造），调用 `/api/diagnose` 返回 Top3 根因候选
2. 每条规则用构造事件测试：RC-001 构造 comfyui task_submit + vram_critical → 应返回该规则
3. `/api/events/timeline` 返回最近事件，格式统一，category 正确
4. 前端：显存危险弹窗点"查看根因分析"→ 展示根因候选 → 点"查看关联事件"→ 时间线高亮
5. 规则引擎单元测试：5 条规则各至少 1 个正例 + 1 个反例
6. 现有 98 测试全部通过

**风险与注意**：
- 规则引擎是 if-then 不是 ML，必须在文档和 UI 中说明"基于规则的推断，非 AI 分析"，避免过度承诺
- 置信度是规则预设的固定值，不是动态计算的，后续可优化为基于匹配条件数量的动态评分
- 事件时间线依赖 `vram-console.log` 的结构化格式，必须确保所有关键操作都有日志记录（检查 server.py 中是否有遗漏的 log_info）
- 前端时间线组件性能：事件多时用虚拟滚动或分页，默认只显示最近 100 条

---

## 四、P1 增强项详解

### 4.1 D — 故障场景库

**对应命题要点**：故障场景与证据（命题交付要求，覆盖三类故障）

**现状问题**：
- GMae 有自动防死机（第三层分级释放），但处置建议比较泛（"释放显存"）
- 没有系统化的故障场景定义，演示时故障注入靠手动操作
- 根因引擎（A）的规则只有 5 条，需要扩展

**增强目标**：
- 建立 GMae 故障场景库，每类场景含：检测规则、告警模板、处置步骤（可执行）、验证方法
- 为根因引擎（A）提供扩展规则
- 为大赛演示提供标准化故障注入脚本和演示流程

**具体实施**：

#### D1. 故障场景定义文档
- 新建 `16gb-ai-studio/docs/故障场景库.md`，定义 5 个场景：

| 场景 ID | 名称 | 检测规则 | 告警级别 | 对应根因规则 |
|---------|------|---------|---------|------------|
| FC-001 | 显存耗尽/OOM 风险 | free_vram < 1GB 持续 10 秒 | critical | RC-001/002/003/005 |
| FC-002 | 容器异常退出/频繁重启 | Docker die 事件 + 5 分钟内重启 ≥3 次 | warning | 新增 RC-006 |
| FC-003 | 推理延迟升高 | 模型推理 P95 响应时间 > 阈值（LLM >30s/图生成 >120s）持续 3 次 | warning | 新增 RC-007 |
| FC-004 | 任务队列堆积 | ComfyUI 队列 pending >5 持续 30 秒 | info | 新增 RC-008 |
| FC-005 | 服务不可达 | health check 连续 3 次失败 | danger | 新增 RC-009 |

- 每个场景详细定义：
  - **触发条件**：具体的阈值和持续时间
  - **告警模板**：告警标题、内容、级别
  - **处置步骤**：分步操作，每步含具体命令或 API 调用（可执行）
  - **验证方法**：处置后如何确认问题已解决
  - **预防建议**：如何避免再次发生

#### D2. 处置步骤可执行化
- 每个场景的处置步骤不是文字描述，而是具体的 API 调用或 CLI 命令
- 示例（FC-001 显存耗尽）：
  1. 查看当前显存占用：`gmae vram free --dry-run`（预览将释放什么）
  2. 一键释放显存：`POST /api/free`（释放 ComfyUI/Ollama 未使用模型）
  3. 如仍 critical：暂停 ComfyUI 队列：`POST /api/queue/pause`
  4. 如仍 critical：停止非必要容器：`POST /api/scene {scene: "idle"}`
  5. 验证：`GET /api/status` 确认 free_vram > 4GB
- 前端根因弹窗的处置建议直接显示这些步骤，关键步骤带"执行"按钮（调用对应 API）

#### D3. 根因规则扩展
- 在 A 的规则引擎基础上，新增 4 条规则（RC-006 ~ RC-009），对应 FC-002 ~ FC-005
- 规则定义格式与 A2 一致

#### D4. 故障注入演示脚本
- 新建 `16gb-ai-studio/scripts/fault_injection/` 目录
- 每个场景一个注入脚本（Python 或 Bash），用于演示时快速触发故障：
  - `inject_vram_pressure.py`：加载大模型 + 提交高分辨率生成任务，触发显存耗尽
  - `inject_container_crash.py`：docker kill 容器模拟异常退出
  - `inject_latency.py`：提交超大 context 推理任务触发延迟升高
  - `inject_queue_backlog.py`：批量提交 10 个生成任务触发队列堆积
  - `inject_service_down.py`：停止 Ollama 容器触发服务不可达
- 每个脚本含：注入操作、等待时间、恢复操作、预期告警

**涉及文件**：
- `16gb-ai-studio/docs/故障场景库.md`（新建：场景定义文档）
- `16gb-ai-studio/vram-console/diagnose.py`（扩展：新增 RC-006~009 规则）
- `16gb-ai-studio/scripts/fault_injection/*.py`（新建：5 个注入脚本）
- `16gb-ai-studio/vram-console/tests/test_diagnose.py`（扩展：新增规则测试）

**验证方式**：
1. 5 个场景文档完整，每个场景含触发条件/告警模板/处置步骤/验证方法/预防建议
2. 4 条新规则单元测试通过
3. 故障注入脚本可运行：每个脚本执行后触发对应告警，`/api/diagnose` 返回对应根因
4. 前端根因弹窗处置步骤可点击执行（FC-001 的释放按钮调用 `/api/free`）

**风险与注意**：
- 故障注入脚本会真实操作 Docker 容器和 GPU，必须在脚本开头加确认提示和 dry-run 模式
- 注入脚本仅用于演示和测试，不能在生产环境误执行，脚本名和目录要明确标注
- FC-003 推理延迟升高需要有推理请求的响应时间数据，GMae 当前可能没有采集，需要先加简单的响应时间记录（可在 E 采集优化中一并实现）

---

### 4.2 B — 告警降噪

**对应命题要点**：告警降噪（命题目标要点 5，评审权重 10%）

**现状问题**：
- GMae 告警是即时弹出的，显存危险状态持续时会重复弹窗
- 没有聚合、静默、升级机制，用户体验差
- 命题评审明确要求"支持聚合、静默、异常检测，提供处置建议"

**增强目标**：
- 同类告警 5 分钟内聚合为 1 条（显示计数）
- 用户可"已知晓"静默同类告警 30 分钟
- 持续未解决的告警自动升级提醒级别

**具体实施**：

#### B1. 后端：告警管理器
- 在 `server.py` 中新增 `AlertManager` 类（或独立 `alert_manager.py`）
- 核心数据结构：
  - `active_alerts`：当前活跃告警字典，key = alert_type（如 `vram_critical`）
  - `silenced_alerts`：静默中的告警，key = alert_type，value = 静默截止时间
  - `alert_history`：告警历史（最近 100 条，含聚合计数）
- 告警提交流程：
  1. 调用 `alert_manager.submit(alert_type, level, message, metadata)`
  2. 检查是否在静默期 → 是则丢弃，记录到静默日志
  3. 检查是否已有同类型活跃告警 → 是则聚合（count+1，更新 last_triggered，不重复推送）
  4. 否则新建告警，推送到前端（WebSocket 或前端轮询 `/api/alerts`）
- 升级机制：告警持续超过阈值（默认 10 分钟）未解决，自动升级 level（info→warning→danger→critical），并重新推送
- 静默 API：`POST /api/alerts/{alert_type}/silence`，参数 `duration_minutes`（默认 30）
- 告警列表 API：`GET /api/alerts`，返回活跃告警（含聚合计数、首次触发时间、持续时长）

#### B2. 前端：告警通知增强
- 现有 toast/弹窗系统改造：
  - 聚合显示：`显存危险（已触发 3 次）`
  - 新增"已知晓，30 分钟内不再提醒"按钮（调用静默 API）
  - 持续告警显示持续时长：`显存危险 · 已持续 8 分钟`
  - 升级时视觉变化：颜色加深 + 闪烁动画
- 新增"告警中心"页面或抽屉：展示所有活跃告警和历史告警，可批量静默

**涉及文件**：
- `16gb-ai-studio/vram-console/alert_manager.py`（新建）
- `16gb-ai-studio/vram-console/server.py`（集成 AlertManager，新增告警 API）
- `16gb-ai-studio/vram-console/web/js/components/toast.js`（增强：聚合+静默按钮）
- `16gb-ai-studio/vram-console/web/js/pages/alerts.js`（新建：告警中心页，或在 settings 中加 section）
- `16gb-ai-studio/vram-console/web/js/core/api.js`（新增 alerts 相关 API 封装）
- `16gb-ai-studio/vram-console/tests/test_alert_manager.py`（新建）

**验证方式**：
1. 连续触发同类型告警 3 次（间隔 <5 分钟），`/api/alerts` 应返回 1 条告警，count=3
2. 调用静默 API 后，同类型告警不再推送，30 分钟后自动恢复
3. 告警持续 10 分钟未解决，level 自动升级
4. 前端 toast 显示聚合计数和"已知晓"按钮，点击后静默生效
5. 单元测试：聚合、静默、升级、过期恢复各 1 个测试

**风险与注意**：
- 告警管理器状态在内存中，server 重启后丢失。可接受（告警是实时的），但需在文档中说明
- 静默期要持久化到文件（`alerts_silenced.json`），避免重启后静默失效
- 升级机制要防止无限升级，设置最高级别上限（critical）
- 前端轮询 `/api/alerts` 的间隔建议 5 秒，不要太频繁

---

## 五、P2 增强项详解（视进度可选）

### 5.1 F — 资源拓扑图

**对应命题要点**：资源关联模型（命题目标要点 1，评审权重 20%）

**现状问题**：
- GMae 有 GPU→容器→模型的关联数据，但没有可视化展示
- 用户需要在多个页面之间切换才能了解全局资源关系
- 命题评审看重"资源拓扑"展示，演示时视觉冲击力强

**增强目标**：
- 前端 SVG 拓扑图：GPU → 容器 → 模型 → 任务，四层节点实时状态
- 节点可点击下钻，连线表示资源占用关系
- 放在 dashboard 或新增"拓扑"页

**具体实施**：
- 数据来源：`/api/status`（E 优化后响应快），含 GPU 显存、容器列表、模型加载状态、队列任务
- 拓扑布局：
  - 顶层：GPU 节点（显示型号、总显存、已用/空闲、危险等级颜色）
  - 第二层：容器节点（ComfyUI/Ollama/Fooocus/OWUI 等，显示运行状态、显存占用）
  - 第三层：模型节点（每个容器下加载的模型，显示模型名、显存占用、状态）
  - 第四层：任务节点（ComfyUI 队列中的任务，显示状态、进度）
- 交互：
  - 点击容器节点 → 展开/折叠下属模型
  - 点击模型节点 → 显示模型详情（复用现有模型登记台抽屉）
  - 悬停节点 → 显示显存占用 tooltip
  - 显存危险时相关节点红色闪烁
- 技术实现：纯 SVG + JS（GMae 前端已有 `chart.js` SVG 图表基础，可复用渲染逻辑），不引入第三方图库
- 布局算法：简单的树形分层布局（手动计算坐标，节点数 <20 不需要复杂力导向）

**涉及文件**：
- `16gb-ai-studio/vram-console/web/js/pages/topology.js`（新建）
- `16gb-ai-studio/vram-console/web/js/components/topology-graph.js`（新建：SVG 拓扑渲染组件）
- `16gb-ai-studio/vram-console/web/css/components/topology.css`（新建）
- `16gb-ai-studio/vram-console/web/js/main.js`（注册新页面和路由）
- `16gb-ai-studio/vram-console/web/js/components/sidebar.js`（添加导航入口）

**验证方式**：
1. 拓扑页渲染：GPU 节点 + 至少 2 个容器节点 + 模型节点，层级关系正确
2. 节点显存数据与 `/api/status` 一致
3. 点击容器节点展开/折叠模型正常
4. 显存危险时 GPU 节点红色闪烁
5. 无模型加载时显示空状态提示

**风险与注意**：
- SVG 拓扑图在节点多时可能拥挤，默认折叠模型层，只显示容器层
- 布局坐标手动计算，新增容器类型时需更新布局逻辑（可配置化）
- 此为 P2，如时间紧张可跳过，不影响核心功能

---

### 5.2 C — 健康度评分

**对应命题要点**：工作负载识别（命题目标要点 3）

**现状问题**：
- GMae 有服务状态（在线/离线），但没有量化的健康度
- 用户无法快速判断哪个服务"不太健康"（如响应慢、频繁重启）

**增强目标**：
- 每个服务/模型一个健康分（0-100），基于多维度指标
- dashboard 服务卡片显示健康分（绿/黄/红）

**具体实施**：
- 健康分维度（各占权重）：
  - 可用性（40%）：在线=100，离线=0，启动中=50
  - 响应速度（30%）：基于最近一次 API 调用响应时间（<1s=100，1-3s=70，3-10s=40，>10s=10）
  - 稳定性（20%）：最近 1 小时重启次数（0次=100，1次=70，2次=40，≥3次=10）
  - 资源健康（10%）：显存占用是否在安全范围（<70%=100，70-85%=70，85-95%=40，>95%=10）
- 计算时机：`/api/status` 中附带计算，或独立 `/api/health/scores` API
- 前端：dashboard 服务活跃度卡片增加健康分显示，颜色编码（≥80绿，50-79黄，<50红）

**涉及文件**：
- `16gb-ai-studio/vram-console/server.py`（新增健康分计算逻辑）
- `16gb-ai-studio/vram-console/web/js/pages/dashboard.js`（服务卡片显示健康分）
- `16gb-ai-studio/vram-console/web/css/components/card.css`（健康分样式）

**验证方式**：
1. 所有在线服务健康分 ≥50
2. 停止一个服务后其健康分变为 0
3. 响应时间数据需要有采集（可在 E 中加简单的 API 响应时间记录），如无则该维度默认满分
4. dashboard 服务卡片显示健康分和颜色

**风险与注意**：
- 响应速度维度需要历史响应时间数据，GMae 当前可能没有采集。简化方案：只在 `/api/status` 调用时记录各服务的响应时间，存内存中的最近 10 条，取平均值
- 此为 P2，工作量最小（1.5 人天），如时间紧张可最后做或跳过

---

## 六、实施依赖与顺序

```
E（轻量采集优化）─── 基础层，所有其他项依赖其性能提升
    │
    ├──→ A（事件关联引擎）── 核心增量，依赖 E 的数据采集
    │       │
    │       └──→ D（故障场景库）── 为 A 提供扩展规则和演示素材
    │
    ├──→ B（告警降噪）── 独立，可与 A/D 并行
    │
    ├──→ F（资源拓扑图）── P2，依赖 E 的实时数据
    │
    └──→ C（健康度评分）── P2，依赖 E 的指标基础
```

**建议里程碑**：

| 里程碑 | 内容 | 预计时间 | 交付物 |
|-------|------|---------|-------|
| M1 | E 完成 | 第 1 周 | /api/status <3秒，缓存层，Docker events |
| M2 | A 完成 | 第 2-3 周 | 事件时间线 API，根因引擎 5 规则，前端根因弹窗 |
| M3 | D+B 完成 | 第 4 周 | 故障场景库 5 场景，注入脚本，告警降噪 |
| M4 | F+C（可选） | 第 5 周 | 拓扑图，健康度评分 |
| M5 | 演示整合 | 第 6 周 | 故障注入→告警→根因诊断完整演示流程 |

---

## 七、与现有代码的集成注意事项

### 7.1 后端（server.py）
- 当前 server.py 是单文件，约 2000+ 行。新增功能建议拆分为独立模块：`diagnose.py`、`alert_manager.py`、`status_cache.py`，server.py 只做路由分发
- 现有测试 98 个（`tests/` 目录），新增功能必须配套测试，目标测试覆盖率不低于现有水平
- 认证：新增 API 必须走 `_check_auth`（Session Cookie 或 API Token），不能有未认证的 API
- 写操作（释放、驱逐、场景切换）后必须主动失效 E 的状态缓存

### 7.2 前端（web/）
- 遵循现有架构：ES Modules，三级架构（core/components/pages），零构建工具
- 新增页面必须在 `main.js` 的 `registerPages()` 中注册，在 `sidebar.js` 中添加导航
- API 调用必须通过 `core/api.js` 封装，禁止页面中直接 fetch
- 状态管理通过 `core/state.js`，禁止组件间直接传参
- JS 文件修改后必须用 `.mjs` 方式检查 ESM 语法（`copy file.js file.mjs && node --check file.mjs`）

### 7.3 蓝图一致性
- `调度中心架构与交互设计.md`（蓝图）是设计权威，**任何修改必须先经主公同意**
- 新增功能如与蓝图不一致，先登记到 `蓝图偏差登记表.md`，不擅自修改蓝图
- 建议：6 个增强项完成后，统一向主公申请蓝图更新，一次性补充"可观测与诊断层"设计章节

### 7.4 显存安全
- 所有新增功能不得引入新的显存占用（不加载新模型、不启动新 GPU 进程）
- 故障注入脚本（D4）执行前必须检查当前显存状态，空闲 <4GB 时拒绝注入高显存压力的场景
- 遵循 `显存管理最高指南.md` 的所有规则

---

## 八、大赛演示中的体现

这些增强项在大赛演示（5 分钟完整版 + 3 分钟展示版）中的体现方式：

1. **开场（30秒）**：展示资源拓扑图（F），一句话介绍"GMae 实时掌握 GPU→容器→模型→任务的全链路状态"
2. **故障注入（1分钟）**：用注入脚本（D）触发显存耗尽场景，屏幕显示告警
3. **根因诊断（1分钟）**：点击"查看根因分析"，展示根因候选 Top3 + 事件时间线关联（A），这是核心亮点
4. **处置执行（1分钟）**：点击处置建议中的"一键释放"，展示显存恢复，告警自动消除（B 降噪 + D 处置闭环）
5. **收尾（30秒）**：展示健康度评分（C）和告警中心，总结"GMae 不仅管显存，还能诊断故障"

---

## 九、文档维护

- 本文档是开发计划，实施过程中需同步更新：
  - `项目进度跟踪.md`：新增可观测能力增强章节，跟踪每项进度
  - `开发日志.md`：实施过程中的踩坑记录
  - `蓝图偏差登记表.md`：如新增功能与蓝图不一致，登记偏差
- 全部完成后：
  - 申请更新 `调度中心架构与交互设计.md`（蓝图），补充"可观测与诊断层"
  - 更新 `作品介绍.md` 和演示视频脚本，体现新增能力
  - 更新 `README.md`（如存在）

---

*本文档由 2026-09-01 会话生成，基于 ZSvirt 命题思路拆解。另一个会话接手时，请先读本文件，再按优先级顺序实施。*
