/**
 * GMae 指挥家 v2.0 - pages/guard.js
 * 门卫页（阶段 4）：显存执法 + 进程驱逐（蓝图 gpu_guard 登记簿）
 * - 门卫状态横幅（危急/警告/正常）+ 告警 + 建议驱逐
 * - 驱逐操作（L2，仅用户显式触发）：stop ollama models → comfyui /free → stop fooocus
 * - 进程级明细（受管/桌面/未登记）+ 强制驱逐（kick，验明正身后 docker exec kill）
 * 数据源：/api/status（guard/gpu_processes）+ POST /api/guard
 */

import { store } from '../core/state.js';
import { api } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, escapeHtml, fmtMb } from '../core/utils.js';
import { confirm } from '../components/modal.js';

const POLL_INTERVAL = 10000;
let pollTimer = null;
let unsubscribe = null;
let page = null;

const LEVEL_META = {
  critical: { label: '🔴 危急', cls: 'bad' },
  warning:  { label: '🟠 警告', cls: 'warn' },
  ok:       { label: '🟢 正常', cls: 'ok' },
  error:    { label: '⚪ 盲区', cls: 'muted' },
};

/* ========== 门卫检查区 ========== */

function renderGuard(status) {
  const slot = page.querySelector('[data-guard]');
  if (!slot) return;
  empty(slot);
  const g = status?.guard;
  if (!g) {
    slot.appendChild(el('<div class="card"><div class="card__body text-muted">门卫不可用</div></div>'));
    return;
  }
  const meta = LEVEL_META[g.level] || LEVEL_META.ok;
  const free = status?.gpu?.free_mb;

  const card = el(`<div class="card">
    <div class="card__title flex justify-between items-center">
      <span>门卫检查 <span class="tag tag--${meta.cls}">${meta.label}</span></span>
      ${free != null ? `<span class="text-xs text-muted font-mono">空闲 ${fmtMb(free)}</span>` : ''}
    </div>
    <div class="card__body">
      <div class="flex-col gap-sm">
        ${(g.alerts || []).length
          ? g.alerts.map((a) => `<div class="banner ${g.level === 'critical' ? 'banner--bad' : 'banner--warn'}">${escapeHtml(a)}</div>`).join('')
          : '<div class="text-muted text-sm">无告警 · 登记簿正常</div>'}
        ${(g.suggest || []).length
          ? `<div class="guard-suggest text-xs text-muted">建议驱逐：${g.suggest.map((s) => `${s.target}（${escapeHtml(s.evict)}）`).join('、')}</div>`
          : ''}
        <div class="flex gap-md mt-sm">
          <button class="btn" data-guard-check>🔄 重新检查</button>
          <button class="btn btn--danger" data-guard-evict>⚔️ 驱逐低优先级占用</button>
        </div>
        <div class="text-xs text-muted font-mono" data-guard-result></div>
      </div>
    </div>
  </div>`);

  card.querySelector('[data-guard-check]').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = '检查中…';
    try {
      await refresh();
      events.emit('toast', { type: 'success', message: '门卫已重新检查' });
    } catch (err) {
      events.emit('toast', { type: 'error', message: err.message });
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  });
  card.querySelector('[data-guard-evict]').addEventListener('click', onEvict);
  slot.appendChild(card);
}

async function onEvict() {
  const ok = await confirm({
    title: '执行门卫驱逐？',
    message: '依次执行：停 ollama 模型 → ComfyUI /free → 停 Fooocus 容器\n（仅对登记簿可安全重启的服务；若正在用 Fooocus 跑图请勿操作）',
    confirmText: '确认驱逐',
    danger: true,
  });
  if (!ok) return;
  const rst = page.querySelector('[data-guard-result]');
  if (!rst) return;
  rst.textContent = '驱逐中…';
  try {
    const d = await api.guardEvict();
    const steps = (d.actions || [])
      .map((a) => `${a.rc === 0 ? '✔' : '✘'} ${a.step} → rc=${a.rc}`)
      .join('\n');
    rst.innerHTML = `<span class="text-xs font-mono">${escapeHtml(steps)}<br>完成：空闲 ${fmtMb(d.free_before)} → ${fmtMb(d.free_after)}</span>`;
    events.emit('toast', { type: 'success', message: '驱逐完成' });
    await refresh();
  } catch (err) {
    rst.textContent = `✘ 失败：${err.message}`;
  }
}

/* ========== 进程明细 + 驱逐（kick） ========== */

function renderProcs(status) {
  const slot = page.querySelector('[data-procs]');
  if (!slot) return;
  empty(slot);
  const procs = status?.gpu_processes;
  const box = el(`<div class="card">
    <div class="card__title">GPU 进程明细 <span class="text-xs text-muted">点击「强制结束」对受管容器内进程验明正身后 kill</span></div>
    <div class="card__body table-wrap"><table class="table">
      <thead><tr><th>PID</th><th>进程</th><th>归属</th><th>显存</th><th>状态</th><th></th></tr></thead>
      <tbody data-proc-body></tbody>
    </table></div>
  </div>`);
  slot.appendChild(box);
  const body = box.querySelector('[data-proc-body]');

  const managed = procs?.processes || [];
  const desktop = procs?.desktop_processes || [];
  const unknown = procs?.unknown_pids || [];
  const rows = [];

  for (const p of managed) {
    rows.push({ pid: p.pid, name: p.name || p.comm || '?', owner: `受管 · ${p.app || ''}`, mb: p.used_mb, live: p.live, kind: 'managed', container: p.app });
  }
  for (const p of desktop || []) {
    rows.push({ pid: p.pid, name: p.name || '?', owner: '桌面', mb: p.used_mb, live: true, kind: 'desktop' });
  }
  for (const p of unknown) {
    rows.push({ pid: p.pid, name: p.comm || p.name || p.pid || '?', owner: '未登记', mb: p.used_mb, live: true, kind: 'unknown' });
  }

  if (!rows.length) {
    body.appendChild(el('<tr><td colspan="6" class="text-muted">暂无 GPU 进程明细</td></tr>'));
    return;
  }
  for (const r of rows) {
    const tr = el(`<tr>
      <td class="font-mono">${r.pid}</td>
      <td>${escapeHtml(r.name)}</td>
      <td><span class="tag tag--${r.kind === 'managed' ? 'primary' : r.kind === 'desktop' ? 'muted' : 'warn'}">${escapeHtml(r.owner)}</span></td>
      <td class="font-mono">${r.mb != null ? fmtMb(r.mb) : '—'}</td>
      <td>${r.live ? '<span class="text-ok">运行中</span>' : '<span class="text-muted">已退出</span>'}</td>
      <td>${r.kind === 'managed' ? `<button class="btn btn--sm btn--danger" data-kick="${r.pid}">强制结束</button>` : ''}</td>
    </tr>`);
    body.appendChild(tr);
  }
  body.querySelectorAll('[data-kick]').forEach((btn) => {
    btn.addEventListener('click', () => kickProc(btn.dataset.kick));
  });
}

async function kickProc(pid) {
  const ok = await confirm({
    title: `强制驱逐 PID ${pid}？`,
    message: '将对该进程验明正身（容器归属 + 进程名），protect 类进程会自动拒绝。\n确认继续？',
    confirmText: '强制结束',
    danger: true,
  });
  if (!ok) return;
  try {
    const d = await api.guardKick(pid);
    events.emit('toast', { type: 'success', message: d.message || '已驱逐' });
    await refresh();
  } catch (err) {
    events.emit('toast', { type: 'error', message: err.message });
  }
}

/* ========== 页面骨架 ========== */

function render() {
  page = el(`<div class="page guard-page">
    <div class="page-header flex justify-between items-center">
      <div>
        <div class="page-title">门卫</div>
        <div class="page-subtitle">显存执法：水位告警 + 场景违规 + 未登记占用 → 驱逐或强制结束</div>
      </div>
      <div class="text-xs text-muted font-mono" data-guard-ts></div>
    </div>
    <div class="flex-col gap-lg">
      <div data-guard></div>
      <div data-procs></div>
    </div>
  </div>`);
  return page;
}

/* ========== 数据加载 ========== */

async function refresh() {
  try {
    const status = await api.status();
    store.set('status', status);
  } catch { /* api:error 已广播 */ }
}

function renderAll(status) {
  if (!page?.isConnected) return;
  renderGuard(status);
  renderProcs(status);
  const ts = page.querySelector('[data-guard-ts]');
  if (ts) ts.textContent = `更新于 ${new Date().toLocaleTimeString()}`;
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
  title: '门卫',
  render,
  onEnter: () => {
    refresh();
    startPolling();
    unsubscribe = store.subscribe('status', renderAll);
  },
  onLeave: () => {
    stopPolling();
    if (unsubscribe) { unsubscribe(); unsubscribe = null; }
  },
};
