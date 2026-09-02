# 16GAS 重构执行规范（Execution Guide）

> **文档性质**：执行规范（强制执行，防止认知偏移和范围蔓延）
> **创建日期**：2026-09-01
> **适用范围**：S1-S6 重构全过程
> **规则**：每个阶段开始前必须重读本文档对应章节，每个阶段完成后必须执行自检清单。违反本文档的代码变更必须回滚或经主公同意。

---

## 一、文件与目录规范

### 1.1 目录结构（冻结，不得随意调整）

```
vram-console/
├── server.py                  # 服务入口（只做启动/停止，不含业务逻辑）
├── api/
│   ├── routes.py              # 路由 Handler（适配层 + 静态文件 + 基础方法）
│   ├── route_helpers.py       # 路由辅助（HTML 读取/静态文件/认证辅助）
│   ├── request.py             # Request 封装
│   ├── router.py              # 路由注册器（全局单例 router）
│   ├── response.py            # Response 封装
│   ├── middleware.py          # 中间件链
│   └── endpoints/             # API 端点模块（每个资源一个文件）
│       ├── __init__.py        # 总装（导入所有端点模块）
│       ├── status.py          # /api/status, /api/health, /api/hardware
│       ├── logs.py            # /api/logs
│       ├── registry.py        # /api/registry, /api/scan
│       ├── scene.py           # /api/scene, /api/combo
│       ├── vram.py            # /api/free, /api/budget, /api/advice, /api/desktop_*
│       ├── guard.py           # /api/guard
│       ├── queue.py           # /api/queue, /api/queue/cancel
│       ├── qos.py             # /api/qos/*, /api/auto-protect/*
│       ├── service.py         # /api/service, /api/model, /api/container/stop
│       ├── auth_endpoints.py  # /api/auth/*
│       ├── observability.py   # /api/comfy_events, /api/v1/*
│       ├── admission.py       # /api/admission
│       ├── events.py          # S2 新增：/api/events/timeline, /api/events/stats
│       ├── diagnose.py        # S2 新增：/api/diagnose, /api/diagnose/rules
│       └── alerts.py          # S3 新增：/api/alerts/*
├── core/                      # 基础设施层（无业务逻辑，可被任何模块导入）
│   ├── status_cache.py        # S1 新增：状态缓存
│   └── docker_events.py       # S1 新增：Docker 事件监听
├── engine/                    # 业务引擎层（核心业务逻辑）
│   ├── watchdog.py            # 看门狗
│   ├── qos.py                 # QoS 状态机
│   ├── event_bus.py           # S2 新增：事件总线
│   ├── diagnose.py            # S2 新增：根因规则引擎
│   └── alert_manager.py       # S3 新增：告警管理器
├── services/                  # 外部服务适配层（Docker/Ollama/ComfyUI/Helper）
├── tests/                     # 单元测试
│   ├── run_tests.py           # 测试运行入口
│   ├── test_status_cache.py   # S1 新增
│   ├── test_event_bus.py      # S2 新增
│   ├── test_diagnose.py       # S2 新增
│   └── test_alert_manager.py  # S3 新增
├── web/                       # S4 前端（重做）
├── legacy/                    # 存档（旧前端/备份文件）
├── logs/                      # 日志（vram-console.log, watchdog.log, events.jsonl）
├── data/                      # 运行时数据（alerts_silenced.json 等）
└── resources/                 # 静态资源（registry.json 等）
```

### 1.2 文件命名规范

| 类型 | 命名规则 | 示例 |
|------|---------|------|
| Python 模块 | snake_case.py | `status_cache.py`、`event_bus.py` |
| Python 类 | PascalCase | `StatusCache`、`EventBus`、`RuleEngine` |
| API 端点模块 | 资源名.py | `events.py`、`diagnose.py`、`alerts.py` |
| 测试文件 | test_<模块名>.py | `test_status_cache.py` |
| JS 模块 | kebab-case.js 或 PascalCase.js | `event-timeline.js`、`VramBar.js` |
| CSS 文件 | kebab-case.css | `event-timeline.css` |
| 文档 | 中文描述_英文标识.md | `重构接口契约_API_Contract.md` |

### 1.3 模块分层与导入规则（强制执行）

**分层依赖方向**（只能向下依赖，禁止向上/横向跨层）：

```
api/endpoints/  →  engine/  →  core/  →  services/
（端点层）      （引擎层）  （基础设施）  （外部适配）
```

**规则**：
1. `api/endpoints/` 可以导入 `engine/`、`core/`、`services/`、`api/`（request/router/response）
2. `engine/` 可以导入 `core/`、`services/`，**禁止**导入 `api/`（引擎不依赖 HTTP 层）
3. `core/` 可以导入 `services/`，**禁止**导入 `engine/` 和 `api/`
4. `services/` 是最底层，**禁止**导入任何上层模块
5. **禁止循环导入**：A 导入 B，B 不能导入 A
6. 全局单例在模块底部定义（如 `status_cache = StatusCache()`），其他模块导入单例而非类

**导入顺序**（每个文件顶部）：
```python
# 1. 标准库
import json
import time
from typing import Optional

# 2. 第三方库（无，保持零依赖）

# 3. 项目内部（按层从底到上）
from core.status_cache import status_cache
from engine.event_bus import event_bus
from api.request import Request
from api.response import Response
from api.router import router
```

---

## 二、每阶段开始前必读清单（认知锚点恢复）

> **规则**：每个阶段开始前，必须重读以下文档，不得凭记忆执行。读完后在回复中确认"已重读认知锚点"。

### 2.1 通用必读（每个阶段都要读）

| 序号 | 文档 | 位置 | 目的 |
|------|------|------|------|
| 1 | AGENTS.md | 工作区根目录 | 项目总入口、禁令、操作规范 |
| 2 | 工作交接.md | 工作区根目录 | 当前状态、未完成任务、注意事项 |
| 3 | 重构接口契约 | `16gb-ai-studio/docs/重构接口契约_API_Contract.md` | API 请求/响应格式（冻结） |
| 4 | 重构数据结构定义 | `16gb-ai-studio/docs/重构数据结构定义_Data_Schema.md` | 共享数据结构字段（冻结） |
| 5 | 重构执行规范 | 本文档 | 命名/导入/自检/偏差检测规则 |
| 6 | 16GAS系统重构计划 | `16gb-ai-studio/docs/16GAS系统重构计划_v1.1_开发指导手册.md` | 本阶段的具体任务/DoD/代码模板 |

### 2.2 各阶段专项必读

| 阶段 | 额外必读 |
|------|---------|
| S1 | `docs/显存管理最高指南.md`（显存安全）、`api/endpoints/status.py`（现有实现） |
| S2 | `engine/event_bus.py`（如已创建）、`api/endpoints/events.py`（如已创建）、现有日志格式 |
| S3 | `engine/alert_manager.py`（如已创建）、`docs/故障场景库.md`（S3.1 产出） |
| S4 | `16GAS前端设计规范与版面设计_S4补充.md`（设计规范）、`web/`（现有前端结构） |
| S5 | S1 的 status_cache 实现、S4 的 Dashboard 组件 |
| S6 | S2/S3/S4 的全部产出、大赛材料清单 |

### 2.3 环境确认（每个阶段开始前）

执行以下命令确认环境状态，记录结果：

```powershell
# 1. 服务状态
curl http://127.0.0.1:8787/api/health

# 2. 当前工作目录
cd D:\Users\Danny\Documents\GMae_Amanda\16gb-ai-studio\vram-console
pwd

# 3. Python 路径
python --version

# 4. Git 状态（确认没有未提交的变更）
git status
```

---

## 三、每阶段完成后自检清单（偏差检测）

> **规则**：每个阶段完成后，必须逐项执行以下自检，全部通过才能标记阶段完成。任何一项不通过必须修复或明确记录偏差。

### 3.1 通用自检（每个阶段都要执行）

| # | 检查项 | 验证方法 | 通过标准 |
|---|--------|---------|---------|
| 1 | **接口契约一致性** | 对照《重构接口契约》检查所有新增/修改的 API | 请求参数/响应字段/状态码完全匹配 |
| 2 | **数据结构一致性** | 对照《重构数据结构定义》检查所有共享对象 | 字段名/类型/枚举值完全匹配 |
| 3 | **文件命名规范** | 检查新建文件的命名和位置 | 符合 §1.1 目录结构和 §1.2 命名规范 |
| 4 | **导入规范** | 检查所有 import 语句 | 符合 §1.3 分层依赖，无循环导入 |
| 5 | **单元测试** | 运行 `python tests/run_tests.py <模块名>` | 新增模块的测试全部通过 |
| 6 | **回归测试** | 运行 `python tests/run_tests.py`（全量） | 现有 98 个测试无新增失败 |
| 7 | **语法检查** | Python: `python -m py_compile <文件>`；JS: 复制为 .mjs 后 `node --check` | 无语法错误 |
| 8 | **服务稳定性** | 重启服务后运行 5 分钟，watchdog 无重启 | 服务稳定，watchdog.log 无错误 |
| 9 | **文档同步** | 检查工作交接/开发日志/项目进度跟踪 | 本阶段变更已记录 |
| 10 | **范围控制** | 对照本阶段任务清单 | 没有实现计划外的功能 |

### 3.2 各阶段专项自检

#### S1 专项

| # | 检查项 | 验证方法 |
|---|--------|---------|
| 1 | 缓存命中 | 连续调用 /api/status 5 次，第 2-5 次响应 <500ms |
| 2 | 缓存失效 | 调用 /api/free 后立即调用 /api/status，meta.cached=false |
| 3 | 写操作失效 | 检查 9 个写操作端点是否都调用了 status_cache.invalidate() |
| 4 | Docker events | 启停一个容器，/api/status 中状态 5 秒内更新 |
| 5 | 危险状态短 TTL | danger/critical 状态时缓存 TTL=2s |

#### S2 专项

| # | 检查项 | 验证方法 |
|---|--------|---------|
| 1 | 事件记录 | 执行一个写操作，/api/events/timeline 能查到对应事件 |
| 2 | 事件格式 | 事件对象含全部 7 个字段（timestamp/category/level/source/event/message/metadata） |
| 3 | 规则匹配 | 构造事件测试 9 条规则，每条至少 1 正例 + 1 反例 |
| 4 | 诊断 Top3 | POST /api/diagnose 返回最多 3 条根因候选，按 confidence 降序 |
| 5 | 无匹配默认 | 无匹配规则时返回 DEFAULT 诊断 + 最近 10 条事件 |
| 6 | 状态变化事件 | QoS 状态跃迁时记录 vram 类别事件 |

#### S3 专项

| # | 检查项 | 验证方法 |
|---|--------|---------|
| 1 | 告警聚合 | 连续提交同类型告警 3 次，/api/alerts 返回 1 条 count=3 |
| 2 | 告警静默 | 调用静默 API 后同类型告警不再推送，30 分钟后自动恢复 |
| 3 | 告警升级 | 持续 10 分钟未解决的告警自动升级 level |
| 4 | 静默持久化 | server 重启后静默配置不丢失（alerts_silenced.json） |
| 5 | 故障场景文档 | 5 个场景全部定义，含触发条件/告警模板/处置步骤/验证/预防 |
| 6 | 注入脚本 | 每个脚本支持 --dry-run/--execute/--recover，执行前检查显存 |

#### S4 专项

| # | 检查项 | 验证方法 |
|---|--------|---------|
| 1 | 设计令牌 | CSS 变量全部定义，页面使用变量而非硬编码颜色 |
| 2 | 9 页面导航 | sidebar 可切换所有 9 个页面，无 404 |
| 3 | API 封装 | 所有 API 调用通过 core/api.js，无直接 fetch |
| 4 | 状态管理 | 通过 core/state.js，无组件间直接传参 |
| 5 | ESM 语法 | 所有 JS 文件通过 .mjs 语法检查 |
| 6 | 无全局污染 | 无全局变量，所有模块通过 import/export |
| 7 | 空/错状态 | 每个页面有空状态和错误状态处理 |
| 8 | 危险确认 | 释放/驱逐/停止/取消操作有确认弹窗 |

---

## 四、范围控制规则（防蔓延）

### 4.1 什么是"范围内"

- 重构计划文档（v1.1 开发指导手册）中明确列出的任务
- 接口契约和数据结构定义中明确规定的字段/API
- 为完成计划内任务所必需的辅助代码（工具函数、常量等）

### 4.2 什么是"范围外"（禁止擅自实现）

- 计划文档中未提及的新功能
- 接口契约中未定义的新 API 端点
- 数据结构定义中未定义的新字段
- 对现有 API 的破坏性变更（删除/重命名字段、改变响应格式）
- 蓝图（调度中心架构与交互设计.md）的修改
- 底层（感知层/账本层/执行层）核心逻辑的重构

### 4.3 发现需要新增功能时的处理流程

1. **立即停止**：不要擅自实现
2. **记录到"待确认清单"**：在工作交接文档的"待确认"段落记录：功能描述、为什么需要、影响范围
3. **继续当前任务**：不阻塞当前阶段推进
4. **阶段完成后汇报**：在阶段完成汇报中列出待确认项，等主公决策
5. **主公同意后**：更新接口契约/数据结构定义/重构计划，再实现

### 4.4 发现现有代码有 bug 时的处理流程

1. **判断是否阻塞当前任务**：
   - 阻塞：必须修复，记录到开发日志
   - 不阻塞：记录到"待确认清单"，不擅自修复
2. **修复范围**：只修复阻塞当前任务的最小部分，不做额外重构
3. **修复后验证**：运行相关测试，确认不引入新问题

---

## 五、认知偏移预防机制

### 5.1 上下文丢失恢复

**问题**：多轮对话后，早期的设计决策可能被遗忘，导致实现偏差。

**预防**：
1. 每个阶段开始前执行 §2.1 必读清单，重读所有冻结文档
2. 关键决策（接口格式/数据结构/命名规范）全部固化到文件，不依赖对话记忆
3. 每个阶段完成后更新工作交接文档，记录"本阶段完成了什么/关键决策/注意事项"
4. 新会话开始时，先读工作交接文档的"当前状态"段落

### 5.2 执行偏差检测

**问题**：实现时可能偏离设计文档（字段名拼错、参数遗漏、额外功能）。

**预防**：
1. 每个子任务完成后，对照开发指导手册的 DoD 逐项验证
2. 每个阶段完成后，执行 §3 自检清单
3. API 实现后，用 curl 实际调用，对比接口契约的响应格式
4. 数据结构实现后，写单元测试验证字段完整性

### 5.3 范围蔓延预防

**问题**：实现时可能"顺手"做了计划外的功能，导致工期延误和代码复杂度增加。

**预防**：
1. 严格执行 §4 范围控制规则
2. 每个子任务开始前，明确"这个子任务的边界是什么"
3. 发现需要新增功能时，按 §4.3 流程处理，不擅自实现
4. 阶段完成后自检清单第 10 项"范围控制"必须检查

### 5.4 命名漂移预防

**问题**：不同模块对同一概念使用不同命名（如 vram_free / free_vram / free_mb）。

**预防**：
1. 数据结构定义文档（§2）冻结了所有共享对象的字段名
2. 枚举值定义文档（§3）冻结了所有枚举的取值
3. 新建字段/枚举时，先检查数据结构定义文档是否已有相同概念
4. 代码审查时重点检查命名一致性

---

## 六、服务重启与验证流程

### 6.1 何时需要重启服务

- 修改了 `server.py`、`api/` 下任何文件、`engine/` 下任何文件、`core/` 下任何文件
- 新增了 API 端点
- 修改了路由配置

### 6.2 重启流程（标准化）

```powershell
# 1. 停止现有服务（按命令行精确杀 PID）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*server.py*" -or $_.CommandLine -like "*watchdog.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 2. 确认端口释放
Start-Sleep -Seconds 2
netstat -ano | findstr :8787

# 3. 告知用户手动启动（Agent 后台进程会被沙箱清理）
# 用户双击 run_watchdog.bat

# 4. 等待服务启动
Start-Sleep -Seconds 5

# 5. 验证服务健康
curl http://127.0.0.1:8787/api/health
# 确认顶层有 services 字段

# 6. 验证 watchdog 稳定
# 查看 logs/watchdog.log，确认 "Port :8787 up, monitoring only"
```

### 6.3 重启后必做验证

1. `/api/health` 返回 200，顶层含 services 字段
2. `/api/status` 返回 200，数据正常
3. 登录页/占位页正常
4. watchdog.log 无 "port open but health failed" 错误
5. 运行本阶段新增的单元测试

---

## 七、文档更新规范

### 7.1 每个阶段完成后必须更新的文档

| 文档 | 更新内容 |
|------|---------|
| 工作交接.md（根目录） | 当前状态、本阶段完成内容、未完成任务、注意事项 |
| 开发日志.md | 本阶段的踩坑记录、技术决策、问题解决方案 |
| 项目进度跟踪.md | 本阶段任务状态标记、偏差登记（如有） |

### 7.2 更新格式

工作交接文档的"当前状态"段落必须包含：
- 本阶段完成了什么（一句话）
- 关键文件变更（新建/修改/删除的文件列表）
- 服务状态（是否需要重启、当前是否稳定）
- 下一个阶段是什么
- 待确认事项（范围外的功能需求、需要主公决策的问题）

---

## 八、紧急回滚流程

### 8.1 何时需要回滚

- 重构导致服务无法启动
- 核心 API 不兼容（现有前端/gmae-cli 无法使用）
- 单元测试大量失败且短期无法修复
- 引入了显存安全隐患

### 8.2 回滚步骤

1. **停止服务**：按 §6.2 步骤 1 停止
2. **Git 回滚**：`git revert <commit>` 或 `git reset --hard <previous_commit>`
3. **重启服务**：告知用户手动启动
4. **验证**：按 §6.3 验证服务恢复正常
5. **记录**：在开发日志中记录回滚原因和回滚点
6. **分析**：分析失败原因，更新重构计划后再重新开始

---

## 九、执行节奏建议

### 9.1 单轮对话推进量

- 每轮对话推进 **1-2 个子任务**（不是整个阶段）
- 每个子任务完成后立即验证，不堆积
- 轮次结束时汇报：完成了什么、验证结果、下一轮做什么

### 9.2 阶段完成汇报

每个阶段全部完成后，汇报：
1. 阶段目标和完成情况
2. 新建/修改/删除的文件清单
3. 自检清单执行结果（逐项）
4. 单元测试结果
5. 服务状态
6. 待确认事项（如有）
7. 下一个阶段计划

### 9.3 主公决策点

以下情况必须暂停，等主公确认后再继续：
- 需要修改接口契约或数据结构定义
- 需要实现计划外的功能
- 需要修改蓝图
- 需要执行危险操作（故障注入真实模式、删除数据）
- 阶段完成后进入下一个阶段前

---

*本文档由 2026-09-01 会话创建，作为 S1-S6 重构的执行规范。每个阶段开始前必读 §2，完成后必执行 §3 自检。违反本文档的变更必须回滚或经主公同意。*
