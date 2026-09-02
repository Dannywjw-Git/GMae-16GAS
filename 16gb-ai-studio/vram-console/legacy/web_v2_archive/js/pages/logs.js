/**
 * GMae 指挥家 v2.0 - pages/logs.js
 * 日志页（阶段 4）：结构化事件日志流（后端 /api/logs，读 vram-console.log 尾部）
 * - 事件流（最新在上），级别色标 INFO/ERROR
 * - 事件名中文翻译 + 关键字段（model/pid/scene/service 等）
 * 数据源：/api/logs
 */

import { api } from '../core/api.js';
import { el, empty, escapeHtml } from '../core/utils.js';

const POLL_INTERVAL = 15000;
let pollTimer = null;
let page = null;
let filter = 'all'; // all | error | info

/* 事件名 → 中文可读标签 */
const EVENT_LABELS = {
  server_start: '服务启动', auto_scanner_start: '自动扫描启动',
  registry_loaded: '登记表加载', registry_saved: '登记表保存',
  scene_switch_start: '场景切换开始', scene_switch_done: '场景切换完成',
  vram_pre_release: '预释放显存', vram_release: '显存释放',
  guard_kick: '门卫驱逐进程', gpu_guard_evict: '门卫驱逐',
  idle_reaper_reap: '空闲回收', idle_reaper_ollama_stop: '空闲回收·停模型',
  queue_enqueue: '任务入队', queue_finish: '任务完成', queue_cancel: '任务取消',
  comfy_ws_connected: 'ComfyUI 已连接', comfy_ws_error: 'ComfyUI 连接异常',
  model_loaded: '模型加载', model_unloaded: '模型卸载',
  service_started: '服务启动', service_stopped: '服务停止',
  toast_sent: '桌面通知', toast_failed: '通知失败',
  login: '登录', logout: '登出',
  helper_start: 'Helper 启动', helper_stop: 'Helper 停止',
  registry_load_failed: '登记表加载失败', qos_loop_start: 'QoS 巡检启动',
};

/* 展示时忽略的元字段 */
const SKIP_KEYS = new Set(['ts', 'time', 'level', 'event', 'event_type']);

function fmtEvent(entry) {
  const label = EVENT_LABELS[entry.event] || entry.event || '事件';
  const extra = Object.entries(entry)
    .filter(([k]) => !SKIP_KEYS.has(k))
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join(' ');
  return { label, extra };
}

function renderEntries(entries) {
  const list = page.querySelector('[data-log-list]');
  if (!list) return;
  empty(list);

  let filtered = entries;
  if (filter === 'error') filtered = entries.filter((e) => String(e.level || '').toUpperCase() === 'ERROR');
  if (filter === 'info') filtered = entries.filter((e) => String(e.level || '').toUpperCase() === 'INFO');

  if (!filtered.length) {
    list.appendChild(el('<div class="text-muted text-sm">暂无日志</div>'));
    return;
  }

  for (const e of filtered) {
    const isErr = String(e.level || '').toUpperCase() === 'ERROR';
    const { label, extra } = fmtEvent(e);
    const time = (e.time || '').replace(',', ' ');
    list.appendChild(el(`<div class="log-item ${isErr ? 'log-item--err' : ''}">
      <span class="log-item__time font-mono">${escapeHtml(time)}</span>
      <span class="tag tag--${isErr ? 'bad' : 'muted'} log-item__level">${escapeHtml(e.level || '')}</span>
      <span class="log-item__label">${escapeHtml(label)}</span>
      ${extra ? `<span class="log-item__extra text-muted">${escapeHtml(extra.slice(0, 160))}</span>` : ''}
    </div>`));
  }
}

/* ========== 页面骨架 ========== */

function render() {
  page = el(`<div class="page logs-page">
    <div class="page-header flex justify-between items-center">
      <div>
        <div class="page-title">日志</div>
        <div class="page-subtitle">GMae 结构化事件流（读 vram-console.log 尾部，最新在上）</div>
      </div>
      <div class="flex gap-md items-center">
        <div class="filter-bar flex gap-sm" data-log-filter>
          <button class="btn btn--sm btn--primary" data-lf="all">全部</button>
          <button class="btn btn--sm btn--ghost" data-lf="error">仅错误</button>
          <button class="btn btn--sm btn--ghost" data-lf="info">仅信息</button>
        </div>
        <button class="btn btn--sm" data-log-refresh>🔄 刷新</button>
      </div>
    </div>
    <div class="card">
      <div class="card__body log-list" data-log-list></div>
    </div>
  </div>`);

  page.querySelector('[data-log-filter]').addEventListener('click', (e) => {
    const b = e.target.closest('[data-lf]');
    if (!b) return;
    filter = b.dataset.lf;
    page.querySelectorAll('[data-lf]').forEach((x) => {
      x.classList.toggle('btn--primary', x === b);
      x.classList.toggle('btn--ghost', x !== b);
    });
    const last = lastEntries;
    if (last) renderEntries(last);
  });
  page.querySelector('[data-log-refresh]').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = '刷新中…';
    try {
      await refresh();
      events.emit('toast', { type: 'success', message: '日志已刷新' });
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

let lastEntries = null;

async function refresh() {
  try {
    const d = await api.logs(200);
    if (!d?.ok) return;
    lastEntries = d.entries || [];
    renderEntries(lastEntries);
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
  title: '日志',
  render,
  onEnter: () => {
    refresh();
    startPolling();
  },
  onLeave: () => stopPolling(),
};
