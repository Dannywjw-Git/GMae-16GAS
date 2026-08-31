# GMae v0.3.1 开发日志

> **用途**：日常开发随手记——做了什么、遇到什么坑、怎么解决的。自由格式，不要求结构化。
> 结构化状态见《GMae0.3.1-开发进度&交接表.md》。
> 设计权威见《GMae指挥家显存调度系统-LLM进化指南-v0.3.1》。
> 创建：2026-09-01

---

## 2026-08-31 P-Eng 模块化改造 + 代码质量优化（v2.0 大赛提交准备）

### 完成工作
1. **模块化改造完成**：server.py 从 3087 行单体文件拆分为 23 个模块，最终 server.py 仅 86 行（减少 97.2%）
   - core/：logger、config、utils、registry（全局状态注册表）
   - clients/：nvidia_smi、ollama_client、comfyui_client、docker_client（外部服务客户端层）
   - services/：helper、ollama、comfy、docker、comfy_ws、scene、status
   - gpu/：monitor、guard
   - engine/：reaper、qos、budget、guard、scanner、queue
   - api/：routes
2. **P0 优化**：建立 clients 层（4个Client模块），修正 core 依赖方向（core/status → services/status）
3. **P1 优化**：全模块类型注解覆盖；拆分超长函数（vram_advice 166→42行，current_status 144→21行）
4. **P2 优化**：消除 7 个魔法数字（定义在 core/config.py）；补充 20 个单元测试全部通过
5. **全局变量收敛**：创建 core/registry.py（线程安全单例），迁移 7 个模块 15+ 个全局变量到 registry
6. **代码质量评分**：从初始 61 分（C级）提升到 79 分（A-级），+18 分

### 关键架构决策
- **clients 层**：所有外部服务调用（nvidia-smi/Ollama/ComfyUI/Docker）统一封装，便于 mock 和测试
- **registry 全局状态**：所有跨模块共享状态集中管理，自动加锁消除竞态条件；采用"引用保持"和"状态包装"两种迁移策略，最小化修改面
- **依赖方向**：core 层无反向依赖，clients → core → services/gpu → engine → api，层次清晰

### 验证结果
- 语法检查：全部通过
- API 测试：10/10 通过（health/status/budget/advice/queue/registry/logs/comfy_events/hardware/auto-protect）
- 单元测试：20/20 通过（模型名校验8 + 场景推断5 + 常量5 + 配置2）
- 服务启动正常，所有子系统线程正常运行

### 新增文件
- vram-console/core/registry.py（全局状态注册表）
- vram-console/clients/nvidia_smi.py
- vram-console/clients/ollama_client.py
- vram-console/clients/comfyui_client.py
- vram-console/clients/docker_client.py
- vram-console/tests/test_core_logic.py（20个单元测试）

### 修改文件
- vram-console/server.py（3087→86行）
- vram-console/core/config.py（新增7个显存常量）
- vram-console/core/logger.py（toast状态迁移到registry）
- vram-console/services/status.py（拆分current_status为4子函数，状态缓存迁移）
- vram-console/services/scene.py（LAST_SCENE迁移）
- vram-console/engine/reaper.py（_LAST_BUSY迁移）
- vram-console/engine/qos.py（_qos_state/_AUTO_PROTECT_STATE迁移）
- vram-console/engine/budget.py（拆分vram_advice为3子函数）
- vram-console/engine/queue.py（任务队列状态迁移）
- vram-console/gpu/monitor.py（进程生命周期状态迁移）

### 备份
- server.py.bak.modular（原始3087行备份，可用于恢复）

### 与LLM进化指南的差异
- 进化指南中C-Eng端口写的是8788，实际是8789
- 进化指南未提及registry/clients层等P-Eng内部架构细节（本次新增）
- 进化指南描述的是三引擎整体架构，本次工作是P-Eng内部工程化优化，不冲突

---

## 2026-09-01 W3 完成（C-Eng 前端 + M-Eng P0 评测引擎）

### 完成工作
1. **C-Eng 前端对话页** chat.js（~300行）：消息列表+用户/助手气泡+规划可见（步骤卡片+准入状态色标）+确认执行/取消按钮+后端选择（自动/快道/深道）+示例快捷输入+思考中状态
2. **对话页样式** chat.css：气泡布局+规划步骤卡片（左侧色条区分通过/拒绝）+操作按钮+响应式
3. **Sidebar 新增"指挥家"导航**：总览之后第二个位置，icon 🎼
4. **main.js 注册 chat 路由**：动态 import pages/chat.js
5. **C-Eng CORS 支持**：cognitive_server.py 添加 do_OPTIONS + Access-Control-Allow-Origin:*（前端8787跨域调用8789）
6. **M-Eng 模型扫描器** model_scanner.py：Ollama /api/tags 扫描 vs registry.json 对比，自动跳过嵌入/reranker模型
7. **M-Eng P0 评测** p0_benchmark.py：加载前/后显存实测+prefill/generation tok/s+中文能力冒烟+自动卸载模型
8. **M-Eng 调度引擎** benchmark_engine.py：系统空闲检测（显存>50%+无队列+无Ollama模型）+自动评测+写入registry+JSONL日志+暂停/恢复（用户任务触发时暂停）
9. **M-Eng 单元测试**：9个测试（扫描器3+评测1+引擎5）
10. **全量测试 164 个全过**（原155+M-Eng新9）

### 关键发现
- 当前所有 Ollama 模型都已登记（21个），M-Eng 扫描器 pending=0；新安装模型时会自动发现
- 系统空闲检测正常工作：当前显存空闲>50%且无队列任务，判定为"系统空闲"
- 前端跨域调用需要 C-Eng 支持 CORS，已添加 do_OPTIONS 处理
- chat.js 中 cengRequest 直接 fetch 8789 端口，不经过 P-Eng 代理（简单直接，后续可改为代理）

### 踩坑
- PowerShell python -c 引号转义持续踩坑，所有测试都写成独立 .py 文件
- chat.js 欢迎消息最初用假 decision 渲染，改为独立 welcome 分支+示例点击事件
- C-Eng 重启后 CORS 才生效，修改 cognitive_server.py 必须重启服务

### 新增文件
- vram-console/web/js/pages/chat.js
- vram-console/web/css/pages/chat.css
- vram-console/meng/__init__.py
- vram-console/meng/model_scanner.py
- vram-console/meng/p0_benchmark.py
- vram-console/meng/benchmark_engine.py
- vram-console/tests/test_meng.py

### 修改文件
- vram-console/web/js/components/sidebar.js（新增指挥家导航）
- vram-console/web/js/main.js（注册chat路由）
- vram-console/web/css/main.css（导入chat.css）
- vram-console/cognitive_server.py（添加CORS）

### W3剩余项（移至W4）
- 深道云端API配置页 + API Key加密存储
- M-Eng P1/P2 深度评测
- API 性能基线记录
- 首次启动配置向导

---

## 2026-09-01 W2 完成（C-Eng 核心 + 三引擎联调）

### 完成工作
1. **C-Eng 面向对象模块结构**：`ceng/` 包，含 providers/、tools/ 子包，完全模块化
2. **Provider 层**（4个文件）：LLMProvider 抽象基类 + OllamaProvider（think:false 关键修复）+ OpenAICompatProvider（云端API）+ ProviderManager（快道/深道管理+探活）
3. **决策核心** decision_engine.py：单阶段决策流程（上下文构建→LLM调用→JSON解析→深道判断→准入校验→执行），健壮JSON解析（处理0.8b末尾多引号等偏差）
4. **上下文构建** context_builder.py：System Prompt 模板（含硬件状态+铁律+10个工具描述），状态快照精简（控制上下文大小），few-shot 示例
5. **Tool 层**（10个Tool）：get_system_status/get_model_budget/list_models/switch_scene/submit_task/cancel_task/get_task_status/free_vram/evict_process/get_advice，写操作自动过准入闸门
6. **P-Eng API Client** peng_client.py：自动发现 token（环境变量→.api_token文件），所有P-Eng API封装
7. **隐私过滤器** privacy_filter.py：三级过滤（🟢系统状态保留/🟡用户内容可选/🔴敏感信息永不发），任务类型分类
8. **决策日志** decision_logger.py：按天轮转，turn_id追踪完整决策链，保留7天
9. **C-Eng HTTP 服务** cognitive_server.py：端口8789，/api/chat（核心）、/api/execute、/api/decision/{id}、/api/providers、/api/health
10. **E2E 三场景验证**：查询类（0.8b快道2.4s）、文生图（自动升级9b深道10.6s，智能识别显存critical→规划释放→切场景→提交，准入闸门正确拦截）、显存释放（0.8b快道2.3s）
11. **单元测试**：新增28个C-Eng测试，总计155个测试全过

### 关键发现
- **0.8b 不传 tools 参数**：传入 tools 时 Ollama 走 function calling 模式，0.8b 返回空 content。改为 System Prompt 中描述工具，纯文本 JSON 输出更稳定
- **0.8b JSON 输出有偏差**：末尾常多一个引号 `{"intent":"query"}"`，需健壮解析（提取{...}块+逐字符缩短重试）
- **深道自动升级有效**：文生图场景（多步骤+显存紧张）自动从0.8b升级到9b，规划质量明显提升（正确识别critical状态并规划释放步骤）
- **P-Eng 需重启加载新端点**：W1新增的 /api/admission 端点，P-Eng 服务是W1之前启动的，必须重启才能加载
- **PengClient token 路径坑**：`__file__` 在 `ceng/tools/` 下，需要 dirname x3 才到 `vram-console/`，最初算错导致 token 加载失败

### 踩坑
- PowerShell python -c 引号转义地狱，所有诊断都写成独立 .py 文件
- C-Eng 首次 E2E 全失败，排查链路：JSON解析失败→发现0.8b多引号→修复后仍失败→发现带tools返回空content→改为不传tools→仍失败→发现P-Eng 401→PengClient token路径错→修复后P-Eng 404→P-Eng运行旧代码需重启→最终全通
- 测试3多模态请求触发深道9b，推理超60秒超时，E2E测试超时增加到120秒

### 新增文件
- vram-console/ceng/\_\_init\_\_.py
- vram-console/ceng/providers/\_\_init\_\_.py, base.py, ollama_provider.py, openai_compat.py, manager.py
- vram-console/ceng/tools/\_\_init\_\_.py, base.py, peng_client.py, peng_tools.py
- vram-console/ceng/context_builder.py, decision_engine.py, privacy_filter.py, decision_logger.py
- vram-console/cognitive_server.py
- vram-console/test_ceng_e2e.py
- vram-console/tests/test_ceng.py

### W2剩余项（移至W3）
- M-Eng P0自动评测
- API性能基线记录
- C-Eng前端对话框
- 云端API配置页

---

## 2026-09-01 W3.5 准入闸门Bug修复 + C-Eng决策鲁棒性7项改进

### Bug修复：深道自指显存占用
- **现象**：前端发"出一张草地上的猫咪的图"，C-Eng决策正确（SDXL已加载直接提交，估计7.5GB），但准入闸门拒绝"预计峰值19.9GB超危险线14.7GB"
- **根因**：C-Eng用深道9b做决策后，9b模型还占着9.3GB显存，导致决策时看到的状态（空闲14GB）和执行时的实际状态（空闲2.3GB）不一致
- **修复**：decision_engine.py中深道调用完成后、准入校验前，自动调用provider.unload()卸载本地深道模型，等待2秒显存回吐
- **验证**：修复后决策后显存从13.4GB降到2.9GB（释放10.5GB），准入校验全部通过

### 7项决策鲁棒性改进（用户要求"全面推演各种情况+先后次序引导"）
1. **增强状态快照**：build_state_snapshot新增队列详情（running/pending数量+任务ID）、已加载模型详情（名称+大小+来源，最多8个）、可释放项列表（从get_advice获取）
2. **System Prompt决策模式引导**：新增局面A-G标准处理流程（显存充足直接执行/显存不足先释放/模型未加载先切场景/队列忙提示等待/多步骤保守估计/模糊请求clarify/不可行请求reject）
3. **对话历史**：ContextBuilder新增_conversation_history，最近3轮对话摘要注入上下文，支持"再来一张"等指代理解
4. **逐步重评估执行**：execute方法中每步写操作执行前重新过准入闸门（状态可能已变化），每步后等待2秒状态稳定
5. **扩充few-shot示例**：从2个增至7个（查询/显存充足文生图/显存不足文生图/多模态创作/系统管理/模糊请求/不可行请求）
6. **准入拒绝后自动重规划**：规划被准入闸门拒绝后，注入拒绝原因用深道重规划1次（考虑释放显存/换小模型/降分辨率）
7. **clarify/reject意图+load_model Tool**：新增clarify（反问用户）和reject（不可行+建议替代）意图处理；新增LoadModelTool（预热指定Ollama模型）

### 关键设计决策
- clarify/reject意图不需要准入校验，直接返回
- 快道0.8b（仅1GB）保持加载提高响应速度，深道9b（9GB+）决策后必须释放
- 重规划只用1次，避免无限循环
- 逐步重评估只对写操作做，只读操作跳过

### 踩坑
- 新增LoadModelTool后测试期望值从10改为11（test_create_all_tools和test_tool_schemas）
- context_builder的add_to_history接口从add_to_history(decision)改为add_to_history(user_input, decision)，decision_engine需同步修改

### 修改文件
- vram-console/ceng/context_builder.py（重写：状态快照+决策模式+对话历史+7示例）
- vram-console/ceng/decision_engine.py（重写：逐步重评估+重规划+clarify/reject+接口适配）
- vram-console/ceng/providers/ollama_provider.py（新增unload方法）
- vram-console/ceng/tools/peng_tools.py（新增LoadModelTool）
- vram-console/web/js/pages/chat.js（clarify/reject意图显示+标签）
- vram-console/tests/test_ceng.py（工具数量10→11）

### 测试
- 全量164个测试全过
- E2E验证4场景：查询（快道）、模糊请求（clarify）、文生图（深道+9b自动释放）、连续对话（历史上下文）

## 2026-09-01 蓝本定稿

### 完成工作
- 三引擎架构（M-Eng/C-Eng/P-Eng）讨论定稿
- 28条决策全部确认
- 四文档体系创建：进化指南主文档 + 技术细节 + 交接表 + 本开发日志
- 进化指南主文档 18KB，13章完整覆盖
- 技术细节文档建框架（9章，待开发时填充）
- 交接表建初始状态（0%完成度，W1待办清单）

### 关键决策回顾
- LLM快道：qwen3.5:0.8b（64K, 3.5G），不是0.6b（实测0.8b全面超越）
- 意图理解与调度决策合并（0.8b一条龙，复杂任务升级深道）
- C-Eng与P-Eng独立进程（8788/8787，HTTP通信）
- 目标用户：所有消费级AI服务器使用者（不是本机，不是个人）
- 云端API引入（OpenAICompatProvider，解决自指问题）
- M-Eng模型自动评测（类似Immich后台人脸/OCR）

### 下一步
- W1启动：硬件探测 + 动态阈值 + 队列E2E验证

---

（后续开发记录在此追加，最新的在最上面）

---

## 2026-09-01 W1 完成（P-Eng 强化 + 模块化改造）

### 完成工作
1. **hardware_probe.py**（独立模块，~200行）：GPU探测、底噪测量、RAM/OS/Docker探测，生成hardware_profile.json。实测：RTX 4060 Ti 16GB，底噪3.5GB（WSL2桌面进程占用）
2. **thresholds.py**（独立模块，~150行）：动态阈值计算，替换硬编码16GB/14GB/4GB。支持8G/16G/24G/48G卡，阈值按百分比计算（critical 97%/danger 92%/warning 85%）
3. **admission_gate.py**（独立模块，~280行）：准入闸门，三道防线（格式/铁律R1-R8/预算），C-Eng和手动操作共用
4. **server.py 集成**：导入三模块，替换5处硬编码（QOS阈值/防死机水位/危险等级/场景切换释放线/模型加载拒绝线），新增/api/hardware和/api/admission端点
5. **队列E2E验证**：SDXL完整链路60秒完成（提交→预检→释放→ComfyUI→进度→完成→归档），6/6测试通过
6. **单元测试**：新增29个测试（thresholds 13个 + admission_gate 16个），总计127个测试全过

### 关键发现
- 底噪实测3.5GB（比v0.3假设的1.2GB高），WSL2桌面进程（DWM等）占用较多
- 预算引擎仍从registry.json读底噪（1.0GB），与hardware_profile的3.5GB不一致，待统一（W2）
- Helper已占用8788端口，C-Eng需改用8789（待更新进化指南）
- Fooocus容器在运行时会占用显存，E2E测试前需注意

### 踩坑
- PowerShell curl是Invoke-WebRequest别名，不支持-m参数，需用curl.exe
- python -c在PowerShell中引号转义复杂，E2E测试写成独立脚本文件
- 8GB卡critical阈值计算：8192×0.97=7.76GB（测试期望值 initially写错为7.9）

### 新增文件
- vram-console/hardware_probe.py
- vram-console/thresholds.py
- vram-console/admission_gate.py
- vram-console/test_queue_e2e.py
- vram-console/tests/test_thresholds.py
- vram-console/tests/test_admission_gate.py
- vram-console/resources/hardware_profile.json（自动生成）

### W1剩余项（可W2继续）
- M-Eng P0自动评测（新模型发现→评测→写入registry）
- API性能基线记录（p50/p95/p99）
- 预算引擎底噪统一（从hardware_profile读取）
- C-Eng端口从8788改为8789（更新进化指南）
