/**
 * GMae 指挥家 v2.0 - pages/queue.js
 * 队列页（阶段 3）：GMae 任务队列（串行 worker）+ ComfyUI 原生队列
 * - GMae 队列：提交表单（有工作流模板的模型）+ 任务列表（状态色标/进度/取消）
 * - ComfyUI 队列：运行中/排队任务概要
 * 数据源：/api/queue（snapshot）+ /api/registry（comfyui_models）+ /api/status（comfy_queue）
 */

import { store } from '../core/state.js';
import { api } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, escapeHtml, fmtRelative } from '../core/utils.js';

const POLL_INTERVAL = 10000;
let pollTimer = null;
let unsubscribe = null;

const Q_STATUS = {
  queued:   { label: '⏳ 排队',   cls: 'warn' },
  precheck: { label: '🔎 预检',   cls: 'warn' },
  freeing:  { label: '🧹 释放',   cls: 'warn' },
  running:  { label: '▶ 运行中', cls: 'ok' },
  done:     { label: '✅ 完成',   cls: 'ok' },
  failed:   { label: '❌ 失败',   cls: 'bad' },
  canceled: { label: '🚫 已取消', cls: 'muted' },
};
const ACTIVE_STATUS = ['queued', 'precheck', 'freeing', 'running'];

let page = null;
let comfyModels = [];

/* ========== GMae 队列 ========== */

function renderGmaeQueue(q) {
  const slot = page.querySelector('[data-gmae]');
  if (!slot) return;
  empty(slot);

  const running = (q.tasks || []).filter((t) => t.status === 'running').length;
  const waiting = (q.tasks || []).filter((t) => ACTIVE_STATUS.includes(t.status)).length;
  const summary = q.tasks?.length
    ? `worker ${q.worker_alive ? '🟢' : '⚪'} · 运行 ${running} · 排队 ${waiting} · 共 ${q.tasks.length}`
    : '队列空闲';

  const box = el(`<div class="card">
    <div class="card__title flex justify-between items-center">
      <span>GMae 任务队列 <span class="text-xs text-muted font-mono">${summary}</span></span>
    </div>
    <div class="card__body">
      <div class="q-list mt-md" data-qlist></div>
    </div>
  </div>`);
  slot.appendChild(box);

  // 表单是 DOM 节点，需单独插入（不能嵌入模板字符串）
  const body = box.querySelector('.card__body');
  body.insertBefore(renderSubmitForm(), body.querySelector('[data-qlist]'));

  const list = box.querySelector('[data-qlist]');
  const tasks = (q.tasks || []).slice(0, 20);
  if (!tasks.length) {
    list.appendChild(el('<div class="text-muted text-sm">队列空闲 · 提交一个任务开始（16G 单卡串行）</div>'));
    return;
  }
  for (const t of tasks) {
    const st = Q_STATUS[t.status] || { label: t.status, cls: 'muted' };
    const cancelable = ACTIVE_STATUS.includes(t.status);
    list.appendChild(el(`<div class="q-item">
      <div class="q-item__head flex justify-between items-center">
        <span class="q-item__model font-mono">${escapeHtml(t.model || '—')}</span>
        <span class="tag tag--${st.cls}">${st.label}</span>
      </div>
      <div class="q-item__meta text-xs text-muted">
        #${String(t.id || '').slice(0, 6)}${t.progress ? ` · ${escapeHtml(t.progress)}` : ''}
        ${t.created ? ` · ${fmtRelative(t.created)}` : ''}
        ${t.error ? ` · <span class="text-bad">${escapeHtml(String(t.error).slice(0, 90))}</span>` : ''}
      </div>
      ${cancelable ? '<button class="btn btn--sm btn--danger q-item__cancel">取消</button>' : ''}
    </div>`));
    const cancelBtn = list.lastElementChild.querySelector('.q-item__cancel');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => cancelTask(t.id));
    }
  }
}

function renderSubmitForm() {
  const form = el(`<form class="q-submit" data-qform>
    <div class="q-submit__row">
      <label class="q-submit__label text-xs text-muted">模型（有工作流模板）</label>
      <select class="q-submit__model" data-qmodel>
        <option value="">选择模型…</option>
      </select>
    </div>
    <div class="q-submit__row">
      <label class="q-submit__label text-xs text-muted">Prompt</label>
      <textarea class="q-submit__prompt" data-qprompt rows="2" placeholder="例如：a red fox in the snow, cinematic lighting"></textarea>
    </div>
    <div class="q-submit__row flex gap-md items-end">
      <div class="flex-col gap-sm" style="flex:1">
        <label class="q-submit__label text-xs text-muted">Seed</label>
        <input class="q-submit__seed" data-qseed type="number" value="42" />
      </div>
      <button class="btn btn--primary" type="submit" data-qsubmit>🚀 入队</button>
    </div>
  </form>`);

  const sel = form.querySelector('[data-qmodel]');
  for (const m of comfyModels) {
    if (!m.workflow) continue;
    const opt = document.createElement('option');
    opt.value = m.id || m.name || '';
    opt.textContent = `${m.name || m.id}${m.vram_gb ? ` (~${m.vram_gb}G)` : ''}`;
    sel.appendChild(opt);
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const model = sel.value;
    const prompt = form.querySelector('[data-qprompt]').value.trim();
    if (!model) { events.emit('toast', { type: 'error', message: '请先选择有工作流模板的模型' }); return; }
    if (!prompt) { events.emit('toast', { type: 'error', message: '请输入 prompt' }); return; }
    const seed = parseInt(form.querySelector('[data-qseed]').value, 10) || 42;
    const btn = form.querySelector('[data-qsubmit]');
    btn.disabled = true;
    try {
      await api.queueEnqueue(model, { prompt, seed, width: 480, height: 480 });
      form.querySelector('[data-qprompt]').value = '';
      events.emit('toast', { type: 'success', message: '任务已入队' });
      await refresh();
    } catch (err) {
      events.emit('toast', { type: 'error', message: err.message });
    } finally {
      btn.disabled = false;
    }
  });
  return form;
}

async function cancelTask(id) {
  try {
    await api.queueCancel(id);
    events.emit('toast', { type: 'info', message: '取消请求已发送' });
    await refresh();
  } catch (err) {
    events.emit('toast', { type: 'error', message: err.message });
  }
}

/* ========== ComfyUI 队列 ========== */

function renderComfyQueue(status) {
  const slot = page.querySelector('[data-comfy]');
  if (!slot) return;
  empty(slot);
  const q = status?.comfy_queue;
  if (!q) {
    slot.appendChild(el('<div class="card"><div class="card__title">ComfyUI 队列</div><div class="card__body text-muted text-sm">ComfyUI 未响应</div></div>'));
    return;
  }
  if (!q.ok) {
    slot.appendChild(el('<div class="card"><div class="card__title">ComfyUI 队列</div><div class="card__body text-muted text-sm">ComfyUI 未响应 /queue</div></div>'));
    return;
  }
  const fmtT = (arr) => (arr && arr.length)
    ? arr.map((t) => `${t.class_type || '?'}<small class="text-muted">(${String(t.id).slice(0, 8)})</small>`).join('、')
    : '无';
  slot.appendChild(el(`<div class="card">
    <div class="card__title">ComfyUI 队列</div>
    <div class="card__body text-sm">
      <div class="mb-sm"><span class="tag tag--ok">▶ 运行中 ${q.running_count || 0}</span> <span class="text-muted">${fmtT(q.running)}</span></div>
      <div><span class="tag tag--warn">⏳ 排队 ${q.pending_count || 0}</span> <span class="text-muted">${fmtT(q.pending)}</span></div>
      <div class="text-xs text-muted mt-sm">由 GMae 队列（左）串行调度，避免多任务抢显存</div>
    </div>
  </div>`));
}

/* ========== 页面骨架 ========== */

function render() {
  page = el(`<div class="page queue-page">
    <div class="page-header flex justify-between items-center">
      <div>
        <div class="page-title">队列</div>
        <div class="page-subtitle">GMae 串行任务队列 + ComfyUI 原生队列</div>
      </div>
      <button class="btn" data-qrefresh>🔄 刷新</button>
    </div>
    <div class="flex-col gap-lg">
      <div class="grid grid-2" data-gmae></div>
      <div class="grid grid-2" data-comfy></div>
    </div>
  </div>`);
  page.querySelector('[data-qrefresh]').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = '刷新中…';
    try {
      await refresh();
      events.emit('toast', { type: 'success', message: '队列已刷新' });
    } catch (err) {
      events.emit('toast', { type: 'error', message: err.message });
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  });
  return page;
}

/* ========== 数据加载 ========== */

async function refresh() {
  try {
    // 模型下拉（有工作流模板的 comfyui 模型）；registry.comfyui_models 是数组
    if (!comfyModels.length) {
      try {
        const reg = await api.registry();
        comfyModels = Array.isArray(reg?.comfyui_models) ? reg.comfyui_models : [];
      } catch { comfyModels = []; }
    }
    const [q, status] = await Promise.all([
      api.queue(),
      api.status(),
    ]);
    store.set('status', status);
    renderGmaeQueue(q);
    renderComfyQueue(status);
  } catch { /* api:error 已广播 */ }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(refresh, POLL_INTERVAL);
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/* ========== 页面注册 ========== */

export default {
  title: '队列',
  render,
  onEnter: () => {
    refresh();
    startPolling();
    unsubscribe = store.subscribe('status', renderComfyQueue);
  },
  onLeave: () => {
    stopPolling();
    if (unsubscribe) { unsubscribe(); unsubscribe = null; }
  },
};
