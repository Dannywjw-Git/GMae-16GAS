/**
 * GMae 指挥家 v2.0 - pages/chat.js
 * C-Eng 认知引擎对话页（v0.3.1 完整版）
 * - 自然语言输入创作意图
 * - C-Eng 规划多模态任务序列（规划可见）
 * - 用户确认后逐步执行（动画 + 每步结果）
 * - 按意图类型展示结果（查询/生成/系统管理）
 * - 快捷操作（刷新/再来一张/查看状态）
 *
 * 数据源：C-Eng 服务（端口8789）/api/chat + /api/execute
 */

import { api } from '../core/api.js';
import { el, empty, escapeHtml } from '../core/utils.js';
import toast from '../components/toast.js';

const CENG_BASE = 'http://127.0.0.1:8789';

let page = null;
let messages = [];
let backendSelect = 'auto';

/* ========== 工具函数 ========== */

async function cengRequest(path, body = null, timeout = 120000) {
  const url = CENG_BASE + path;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const opts = { method: 'GET', headers: { 'Accept': 'application/json' }, signal: controller.signal };
    if (body) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(url, opts);
    return await resp.json();
  } catch (e) {
    return { ok: false, error: `C-Eng 连接失败: ${e.message || e}（请确认 C-Eng 服务已启动，端口8789）` };
  } finally {
    clearTimeout(timer);
  }
}

function intentLabel(intent) {
  const map = {
    single_task: '🎯 单任务',
    multimodal_creation: '🎨 多模态创作',
    query: '🔍 查询',
    system_management: '⚙️ 系统管理',
    clarify: '❓ 需要澄清',
    reject: '⛔ 不可行',
  };
  return map[intent] || intent || '未知';
}

function backendLabel(decision) {
  const tier = decision.backend_tier === 'deep' ? '深道' : '快道';
  const name = decision.backend_used || '';
  return `${tier} · ${name} · ${decision.latency_ms || 0}ms`;
}

function fmtMb(mb) {
  if (!mb && mb !== 0) return '-';
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB';
  return Math.round(mb) + ' MB';
}

/* ========== 渲染消息 ========== */

function renderMessages() {
  const list = page.querySelector('[data-messages]');
  empty(list);
  for (const msg of messages) {
    if (msg.role === 'user') {
      list.appendChild(renderUserMessage(msg));
    } else {
      list.appendChild(renderAssistantMessage(msg));
    }
  }
  list.scrollTop = list.scrollHeight;
}

function renderUserMessage(msg) {
  return el(`<div class="chat-msg chat-msg--user">
    <div class="chat-msg__bubble">${escapeHtml(msg.content)}</div>
  </div>`);
}

function renderAssistantMessage(msg) {
  if (msg.welcome) return renderWelcome();

  const d = msg.decision;
  if (!d || !d.ok) {
    return el(`<div class="chat-msg chat-msg--assistant">
      <div class="chat-msg__bubble chat-msg__bubble--error">❌ ${escapeHtml(d?.error || '决策失败')}</div>
    </div>`);
  }

  // Fooocus式极简：隐藏技术细节（意图/后端/置信度/显存峰值/工具步骤）
  // 只显示：执行状态 + 结果
  const node = el(`<div class="chat-msg chat-msg--assistant">
    <div class="chat-msg__bubble">
      <div class="chat-decision">
        <div class="chat-status" data-status></div>
        <div class="chat-result mt-md" data-result></div>
      </div>
    </div>
  </div>`);

  // 渲染状态（执行中/完成/失败）
  renderStatus(node.querySelector('[data-status]'), d, msg);

  // 渲染执行结果
  if (msg.execution && msg.execution.status === 'done') {
    renderResult(node.querySelector('[data-result]'), d, msg.execution);
  }

  return node;
}

function renderWelcome() {
  return el(`<div class="chat-msg chat-msg--assistant">
    <div class="chat-msg__bubble">
      <div class="chat-welcome">
        <div class="chat-welcome__title">🎼 GMae 指挥家已就绪</div>
        <div class="chat-welcome__desc">用自然语言描述你的创作意图，我会规划多模态任务序列并管理显存资源。</div>
        <div class="chat-welcome__examples">
          <div class="chat-welcome__example" data-example="出一张日落风景的图">🖼️ 出一张日落风景的图</div>
          <div class="chat-welcome__example" data-example="当前显存状态怎么样？">📊 查询当前显存状态</div>
          <div class="chat-welcome__example" data-example="显存不够了，帮我释放一下">🧹 释放显存</div>
          <div class="chat-welcome__example" data-example="先出一张猫的图，再配一段音乐">🎵 多模态：图+音乐</div>
        </div>
      </div>
    </div>
  </div>`);
}

function renderPlanStep(step, validation, execution) {
  const valStep = (validation?.steps || []).find((s) => s.step === step.step);
  const passed = valStep ? valStep.passed : true;

  // 执行状态覆盖准入状态
  let execStatus = '';
  let execIcon = '';
  let execCls = '';
  if (execution) {
    const exStep = execution.steps?.find((s) => s.step === step.step);
    if (exStep) {
      if (exStep.status === 'running') { execStatus = '执行中'; execIcon = '🔄'; execCls = 'chat-plan__step--running'; }
      else if (exStep.status === 'done') { execStatus = '成功'; execIcon = '✅'; execCls = 'chat-plan__step--done'; }
      else if (exStep.status === 'failed') { execStatus = '失败'; execIcon = '❌'; execCls = 'chat-plan__step--failed'; }
      else if (exStep.status === 'pending') { execStatus = '待执行'; execIcon = '⏳'; execCls = 'chat-plan__step--pending'; }
    }
  }

  const statusIcon = execIcon || (passed ? '✓' : '⛔');
  const statusCls = execCls || (passed ? '' : 'chat-plan__step--rejected');
  const argsStr = JSON.stringify(step.args || {});

  return el(`<div class="chat-plan__step ${statusCls}">
    <div class="chat-plan__step-head">
      <span class="chat-plan__step-num">${step.step}</span>
      <span class="chat-plan__step-tool font-mono">${escapeHtml(step.tool || '')}</span>
      <span class="chat-plan__step-status">${statusIcon} ${execStatus}</span>
    </div>
    <div class="chat-plan__step-args text-xs font-mono text-muted">${escapeHtml(argsStr)}</div>
    <div class="chat-plan__step-reason text-sm">${escapeHtml(step.reason || '')}</div>
    ${valStep && !passed && !execStatus ? `<div class="chat-plan__step-reject text-xs text-bad">${escapeHtml(valStep.reason || '准入校验未通过')}</div>` : ''}
  </div>`);
}

function renderStatus(slot, d, msg) {
  const intent = d.intent || '';
  const val = d.validation || {};
  const steps = d.plan || [];

  // 简单对话：直接显示回复文字，不调用工具
  if (intent === 'chat' || d.reply) {
    const reply = d.reply || '你好！有什么可以帮你的？';
    slot.appendChild(el(`<div class="chat-reply">${escapeHtml(reply)}</div>`));
    return;
  }
  // 需要澄清
  if (intent === 'clarify') {
    slot.appendChild(el('<div class="chat-exec chat-exec--info">❓ 需要更多信息，请补充说明你的需求</div>'));
    return;
  }
  // 不可行
  if (intent === 'reject') {
    const rejectReason = (d.plan?.[0]?.reason) || '该请求不可行，请尝试其他方案';
    slot.appendChild(el(`<div class="chat-exec chat-exec--rejected">⛔ ${escapeHtml(rejectReason)}</div>`));
    return;
  }
  // 准入未通过
  if (val.all_passed === false) {
    const reason = val.reason || '准入校验未通过，显存不足';
    slot.appendChild(el(`<div class="chat-exec chat-exec--rejected">⛔ ${escapeHtml(reason)}</div>`));
    return;
  }
  // 执行中
  if (msg.execution) {
    if (msg.execution.status === 'running') {
      const genModel = findGenModel(d);
      slot.appendChild(el(`<div class="chat-exec chat-exec--info">🔄 ${genModel ? '正在生成...' : '正在处理...'}</div>`));
    }
    return;
  }
  // 待执行（自动执行，不显示确认按钮）
  if (steps.length > 0) {
    // 不显示任何内容，sendMessage会自动触发执行
  }
}

function findGenModel(decision) {
  const step = (decision.plan || []).find((s) => s.tool === 'submit_task');
  return step?.args?.model || '';
}

/* ========== 结果展示（按意图类型分化） ========== */

function renderResult(slot, decision, execution) {
  const intent = decision.intent || '';
  const steps = execution.steps || [];

  if (intent === 'query') {
    renderQueryResult(slot, steps);
  } else if (intent === 'single_task' || intent === 'multimodal_creation') {
    renderGenerationResult(slot, steps, decision);
  } else if (intent === 'system_management') {
    renderSystemResult(slot, steps);
  } else {
    // 默认：展示每步的简要结果
    renderDefaultResult(slot, steps);
  }
}

function renderQueryResult(slot, steps) {
  const wrap = el('<div class="chat-result__card"></div>');

  for (const exStep of steps) {
    if (exStep.status !== 'done') continue;
    const tool = exStep.tool;
    const result = exStep.result || {};

    if (tool === 'get_system_status') {
      wrap.appendChild(renderStatusCard(result));
    } else if (tool === 'get_model_budget') {
      wrap.appendChild(renderBudgetCard(result));
    } else if (tool === 'list_models') {
      wrap.appendChild(renderModelList(result));
    } else if (tool === 'get_task_status') {
      wrap.appendChild(renderTaskStatus(result));
    } else if (tool === 'get_advice') {
      wrap.appendChild(renderAdviceCard(result));
    } else {
      wrap.appendChild(el(`<div class="chat-result__item"><strong>${escapeHtml(tool)}</strong>: ${escapeHtml(JSON.stringify(result).substring(0, 200))}</div>`));
    }
  }

  // 快捷操作：刷新
  const refreshBtn = el('<button class="btn btn--sm btn--ghost mt-sm">🔄 刷新</button>');
  refreshBtn.addEventListener('click', () => {
    const msg = messages.find((m) => m.execution === execution);
    if (msg) {
      delete msg.execution;
      renderMessages();
      executeDecision(msg.decision, msg);
    }
  });
  wrap.appendChild(refreshBtn);

  slot.appendChild(wrap);
}

function renderStatusCard(result) {
  const gpu = result.gpu || {};
  const ledger = result.vram_ledger || {};
  const ollama = result.ollama?.models || [];
  const comfy = result.comfyui_models?.models || [];
  const queue = result.comfy_queue || {};
  const danger = ledger.danger_level || 'safe';
  const dangerCls = danger === 'safe' ? 'ok' : danger === 'warn' ? 'warn' : 'bad';

  const models = [...ollama.map((m) => `${m.name} (${m.size_gb}GB)`),
                  ...comfy.map((m) => `${m.name} (${m.vram_gb}GB)`)].join('、') || '无';

  return el(`<div class="chat-result__section">
    <div class="chat-result__title">📊 系统状态</div>
    <div class="chat-result__grid">
      <div class="chat-result__item"><span class="text-muted">显存</span><strong>${fmtMb(gpu.used_mb)} / ${fmtMb(gpu.total_mb)}</strong></div>
      <div class="chat-result__item"><span class="text-muted">空闲</span><strong>${fmtMb(gpu.free_mb)}</strong></div>
      <div class="chat-result__item"><span class="text-muted">危险等级</span><strong class="text-${dangerCls}">${danger}</strong></div>
      <div class="chat-result__item"><span class="text-muted">场景</span><strong>${escapeHtml(result.scene || '-')}</strong></div>
      <div class="chat-result__item"><span class="text-muted">队列</span><strong>${(queue.running||[]).length} 运行 / ${(queue.pending||[]).length} 排队</strong></div>
      <div class="chat-result__item chat-result__item--full"><span class="text-muted">已加载模型</span><strong>${escapeHtml(models)}</strong></div>
    </div>
  </div>`);
}

function renderBudgetCard(result) {
  return el(`<div class="chat-result__section">
    <div class="chat-result__title">💰 模型预算</div>
    <div class="chat-result__item"><span class="text-muted">模型</span><strong>${escapeHtml(result.model || '-')}</strong></div>
    <div class="chat-result__item"><span class="text-muted">所需显存</span><strong>${fmtMb(result.required_mb || result.required_gb * 1024)}</strong></div>
    <div class="chat-result__item"><span class="text-muted">可行性</span><strong class="${result.feasible ? 'text-ok' : 'text-bad'}">${result.feasible ? '✅ 可行' : '❌ 不可行'}</strong></div>
    ${result.shortfall_gb ? `<div class="chat-result__item"><span class="text-muted">差额</span><strong class="text-bad">还差 ${result.shortfall_gb} GB</strong></div>` : ''}
  </div>`);
}

function renderModelList(result) {
  const models = result.models || result.registry || [];
  const items = models.map((m) => `<div class="chat-result__item"><strong>${escapeHtml(m.name || m.id)}</strong> <span class="text-muted">${m.modal || m.category || ''} · ${m.vram_gb || m.size_gb || '-'}GB${m.exclusive ? ' · 独占' : ''}</span></div>`).join('');
  return el(`<div class="chat-result__section">
    <div class="chat-result__title">📋 模型列表 (${models.length})</div>
    <div class="chat-result__list">${items || '<div class="text-muted">无</div>'}</div>
  </div>`);
}

function renderTaskStatus(result) {
  const task = result.task || result;
  return el(`<div class="chat-result__section">
    <div class="chat-result__title">📦 任务状态</div>
    <div class="chat-result__item"><span class="text-muted">任务ID</span><strong class="font-mono">${escapeHtml(task.id || '-')}</strong></div>
    <div class="chat-result__item"><span class="text-muted">模型</span><strong>${escapeHtml(task.model || '-')}</strong></div>
    <div class="chat-result__item"><span class="text-muted">状态</span><strong>${escapeHtml(task.status || '-')}</strong></div>
    <div class="chat-result__item"><span class="text-muted">进度</span><strong>${escapeHtml(task.progress || '-')}</strong></div>
  </div>`);
}

function renderAdviceCard(result) {
  const items = result.releasable || [];
  const list = items.map((i) => `<div class="chat-result__item"><strong>${escapeHtml(i.name)}</strong> <span class="text-muted">可释放 ${i.vram_gb}GB</span></div>`).join('');
  return el(`<div class="chat-result__section">
    <div class="chat-result__title">💡 优化建议</div>
    <div class="chat-result__list">${list || '<div class="text-muted">暂无建议，显存状态良好</div>'}</div>
  </div>`);
}

function renderGenerationResult(slot, steps, decision) {
  const wrap = el('<div class="chat-result__card"></div>');

  // 找到 submit_task 步骤
  const submitStep = steps.find((s) => s.tool === 'submit_task' && s.status === 'done');
  if (submitStep) {
    const taskId = submitStep.result?.task_id || submitStep.result?.task?.id || '';
    const model = submitStep.result?.model || submitStep.args?.model || '';

    wrap.appendChild(el(`<div class="chat-result__section">
      <div class="chat-result__title">🎨 ${escapeHtml(model || '生成任务')}</div>
      <div class="chat-result__item"><span class="text-muted">状态</span><strong data-gen-status>排队中...</strong></div>
      <div class="chat-result__progress mt-sm" data-gen-progress><div class="chat-result__progress-bar" style="width:0%"></div></div>
    </div>`));

    // 结果预览区
    const previewSlot = el('<div class="chat-result__preview mt-md" data-gen-preview></div>');
    wrap.appendChild(previewSlot);

    // 快捷操作
    const actions = el('<div class="flex gap-sm mt-sm"></div>');
    const againBtn = el('<button class="btn btn--sm btn--ghost">🔄 再来一张</button>');
    againBtn.addEventListener('click', () => {
      const input = page.querySelector('[data-input]');
      const lastUserMsg = [...messages].reverse().find((m) => m.role === 'user');
      if (lastUserMsg) {
        input.value = lastUserMsg.content;
        sendMessage();
      }
    });
    actions.appendChild(againBtn);
    wrap.appendChild(actions);

    slot.appendChild(wrap);

    // 启动任务轮询
    if (taskId) {
      pollTaskStatus(taskId, wrap);
    }
  } else {
    // 没有 submit_task（可能只有 switch_scene 等前置步骤）
    wrap.appendChild(el('<div class="chat-result__section"><div class="chat-result__title">✅ 执行完成</div><div class="text-muted text-sm">操作已完成</div></div>'));
    slot.appendChild(wrap);
  }
}

async function pollTaskStatus(taskId, wrap) {
  const statusEl = wrap.querySelector('[data-gen-status]');
  const progressEl = wrap.querySelector('[data-gen-progress] .chat-result__progress-bar');
  const previewEl = wrap.querySelector('[data-gen-preview]');
  let attempts = 0;
  const maxAttempts = 60;

  const poll = async () => {
    attempts++;
    if (attempts > maxAttempts) {
      if (statusEl) statusEl.textContent = '⏱️ 轮询超时，请在队列页查看';
      return;
    }

    try {
      const result = await api.queue();
      // P-Eng 返回 { queue: [], tasks: [...] }，注意空数组是 truthy
      const tasks = result.tasks || result.queue || result.running || [];
      const task = tasks.find((t) => t.id === taskId) || result.task;

      if (task) {
        if (statusEl) statusEl.textContent = task.status || 'running';
        if (progressEl) {
          const prog = task.progress ? parseInt(task.progress) : 0;
          progressEl.style.width = Math.min(prog, 100) + '%';
        }

        if (task.status === 'completed' || task.status === 'done' || task.ended) {
          if (statusEl) statusEl.textContent = '✅ 完成';
          if (progressEl) progressEl.style.width = '100%';
          if (previewEl && task.result) {
            renderGenerationPreview(previewEl, task.result, task.model);
          }
          return;
        }
        if (task.status === 'failed' || task.error) {
          if (statusEl) statusEl.textContent = '❌ 失败';
          if (previewEl) previewEl.innerHTML = `<div class="text-bad text-sm">${escapeHtml(task.error || '生成失败')}</div>`;
          return;
        }
      }
    } catch (e) {
      // 队列查询失败，继续轮询
    }

    setTimeout(poll, 3000);
  };
  poll();
}

function renderGenerationPreview(slot, result, model) {
  empty(slot);
  // 图片结果
  if (result.images || result.image || result.output_path) {
    const images = result.images || (result.image ? [result.image] : []);
    for (const img of images) {
      const url = typeof img === 'string' ? img : img.url || img.path;
      if (url) {
        slot.appendChild(el(`<div class="chat-result__image"><img src="${escapeHtml(url)}" alt="生成结果" /></div>`));
      }
    }
    if (result.output_path && !images.length) {
      slot.appendChild(el(`<div class="text-sm text-muted">输出路径: <code>${escapeHtml(result.output_path)}</code></div>`));
    }
  } else if (result.video || result.audio) {
    const media = result.video || result.audio;
    const url = typeof media === 'string' ? media : media.url || media.path;
    if (url) {
      const tag = result.video ? 'video' : 'audio';
      slot.appendChild(el(`<${tag} src="${escapeHtml(url)}" controls class="chat-result__media"></${tag}>`));
    }
  } else {
    slot.appendChild(el('<div class="text-muted text-sm">结果已生成，请在输出目录查看</div>'));
  }
}

function renderSystemResult(slot, steps) {
  const wrap = el('<div class="chat-result__card"></div>');

  for (const exStep of steps) {
    if (exStep.status !== 'done') continue;
    const tool = exStep.tool;
    const result = exStep.result || {};

    if (tool === 'free_vram') {
      wrap.appendChild(el(`<div class="chat-result__section">
        <div class="chat-result__title">🧹 显存释放</div>
        <div class="chat-result__item"><span class="text-muted">状态</span><strong class="text-ok">✅ 已释放</strong></div>
        <div class="chat-result__item"><span class="text-muted">详情</span><strong>${escapeHtml(result.message || result.status || 'ComfyUI /free + Ollama 模型卸载')}</strong></div>
      </div>`));
    } else if (tool === 'switch_scene') {
      wrap.appendChild(el(`<div class="chat-result__section">
        <div class="chat-result__title">🔄 场景切换</div>
        <div class="chat-result__item"><span class="text-muted">当前场景</span><strong>${escapeHtml(result.scene || '-')}</strong></div>
      </div>`));
    } else if (tool === 'evict_process') {
      wrap.appendChild(el(`<div class="chat-result__section">
        <div class="chat-result__title">⚡ 进程驱逐</div>
        <div class="chat-result__item"><span class="text-muted">结果</span><strong>${escapeHtml(result.message || JSON.stringify(result).substring(0, 100))}</strong></div>
      </div>`));
    } else if (tool === 'load_model') {
      wrap.appendChild(el(`<div class="chat-result__section">
        <div class="chat-result__title">📥 模型加载</div>
        <div class="chat-result__item"><span class="text-muted">模型</span><strong>${escapeHtml(result.model || '-')}</strong></div>
        <div class="chat-result__item"><span class="text-muted">状态</span><strong class="text-ok">${escapeHtml(result.status || 'loaded')}</strong></div>
      </div>`));
    } else {
      wrap.appendChild(el(`<div class="chat-result__section">
        <div class="chat-result__title">${escapeHtml(tool)}</div>
        <div class="text-sm text-muted">${escapeHtml(JSON.stringify(result).substring(0, 200))}</div>
      </div>`));
    }
  }

  // 快捷操作：查看当前状态
  const statusBtn = el('<button class="btn btn--sm btn--ghost mt-sm">📊 查看当前状态</button>');
  statusBtn.addEventListener('click', () => {
    const input = page.querySelector('[data-input]');
    input.value = '当前显存状态怎么样？';
    sendMessage();
  });
  wrap.appendChild(statusBtn);

  slot.appendChild(wrap);
}

function renderDefaultResult(slot, steps) {
  const wrap = el('<div class="chat-result__card"></div>');
  for (const exStep of steps) {
    if (exStep.status !== 'done') continue;
    wrap.appendChild(el(`<div class="chat-result__section">
      <div class="chat-result__title">${escapeHtml(exStep.tool)}</div>
      <div class="text-sm text-muted">${escapeHtml(JSON.stringify(exStep.result || {}).substring(0, 300))}</div>
    </div>`));
  }
  slot.appendChild(wrap);
}

/* ========== 执行决策（逐步动画） ========== */

async function executeDecision(decision, msg) {
  // 初始化执行状态
  msg.execution = {
    status: 'running',
    all_success: false,
    steps: (decision.plan || []).map((s) => ({
      step: s.step, tool: s.tool, args: s.args,
      status: 'pending', result: null, error: null,
    })),
  };
  renderMessages();

  // 调用后端执行
  const result = await cengRequest('/api/execute', {
    turn_id: decision.turn_id,
    plan: decision.plan,
  });

  // 回填执行结果
  const execLog = result.execution_log || [];
  for (const step of msg.execution.steps) {
    const logEntry = execLog.find((e) => e.step === step.step);
    if (logEntry) {
      step.status = logEntry.ok ? 'done' : 'failed';
      step.result = logEntry.result;
      step.error = logEntry.error;
    } else {
      step.status = 'failed';
      step.error = '无执行记录';
    }
  }

  // 完成（生成任务的实时进度由 renderGenerationResult 中的 pollTaskStatus 处理）
  msg.execution.status = 'done';
  msg.execution.all_success = msg.execution.steps.every((s) => s.status === 'done');
  renderMessages();

  if (msg.execution.all_success) {
    toast.show('完成', 'ok');
  } else {
    toast.show('执行完成（部分失败）', 'warn');
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/* ========== 发送消息 ========== */

async function sendMessage() {
  const input = page.querySelector('[data-input]');
  const text = input.value.trim();
  if (!text) return;

  messages.push({ role: 'user', content: text });
  input.value = '';
  renderMessages();

  // 思考中
  const thinking = el('<div class="chat-msg chat-msg--assistant"><div class="chat-msg__bubble chat-msg__bubble--thinking">🧠 思考中...</div></div>');
  page.querySelector('[data-messages]').appendChild(thinking);
  page.querySelector('[data-messages]').scrollTop = page.querySelector('[data-messages]').scrollHeight;

  const result = await cengRequest('/api/chat', {
    message: text,
    preferred_backend: backendSelect,
    execute: false,
  });

  thinking.remove();
  const msg = { role: 'assistant', content: '', decision: result };
  messages.push(msg);
  renderMessages();

  if (!result.ok) {
    toast.show(result.error || 'C-Eng 调用失败', 'err');
    return;
  }

  // Fooocus式：生成任务自动执行，不需要确认；对话类直接回复不执行
  const intent = result.intent || '';
  const hasSteps = (result.plan || []).length > 0;
  const allPassed = result.validation?.all_passed !== false;
  const isChat = intent === 'chat' || result.reply;

  if (!isChat && hasSteps && allPassed && intent !== 'clarify' && intent !== 'reject') {
    // 延迟一下让用户看到"思考中→待执行"的过渡
    setTimeout(() => executeDecision(result, msg), 300);
  }
}

/* ========== 页面渲染 ========== */

function render() {
  page = el(`<div class="chat-page">
    <div class="chat-page__head">
      <h2>🎼 指挥家对话</h2>
      <div class="chat-page__backend">
        <label class="text-xs text-muted">推理后端</label>
        <select data-backend class="select select--sm">
          <option value="auto">自动（快道优先，复杂升级深道）</option>
          <option value="fast">仅快道（0.8b，快速）</option>
          <option value="deep">仅深道（9b/云端，精准）</option>
        </select>
      </div>
    </div>
    <div class="chat-page__body">
      <div class="chat-messages" data-messages></div>
    </div>
    <div class="chat-page__input">
      <input type="text" data-input class="input" placeholder="用自然语言描述你的创作意图，如：出一张日落风景的图" />
      <button class="btn btn--primary" data-send>发送</button>
    </div>
    <div class="chat-page__hint text-xs text-muted">
      提示：C-Eng 会规划任务序列并显示显存预估，确认后才执行。所有写操作过 P-Eng 准入闸门。
    </div>
  </div>`);

  page.querySelector('[data-send]').addEventListener('click', sendMessage);
  page.querySelector('[data-input]').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });
  page.querySelector('[data-backend]').addEventListener('change', (e) => {
    backendSelect = e.target.value;
  });

  if (messages.length === 0) {
    messages.push({ role: 'assistant', welcome: true });
  }

  renderMessages();

  page.querySelectorAll('[data-example]').forEach((el) => {
    el.addEventListener('click', () => {
      const input = page.querySelector('[data-input]');
      input.value = el.dataset.example;
      sendMessage();
    });
  });

  return page;
}

function onEnter() {
  cengRequest('/api/health', null, 5000).then((r) => {
    if (!r.ok) {
      toast.show('C-Eng 服务未连接（端口8789），对话功能不可用', 'warn');
    }
  });
}

function onLeave() {}

export default {
  title: '指挥家对话',
  render,
  onEnter,
  onLeave,
};
