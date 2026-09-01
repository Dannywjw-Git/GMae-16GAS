/**
 * GMae 指挥家 v2.0 - pages/dashboard.js
 * 总览页（阶段 1）：L0 一瞥（显存水位/场景/健康）+ L1 动作（预演/一键释放）
 * 蓝图 §11.2 信息架构：一屏一主题，少即是多
 * 数据流：refresh → api.status → store.set('status') → subscribe 重渲染
 */

import { store } from '../core/state.js';
import { api } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, escapeHtml, fmtMb, fmtPct } from '../core/utils.js';
import { open as openModal } from '../components/modal.js';
import { openDemo } from '../components/demo.js';

const POLL_INTERVAL = 10000;
let pollTimer = null;
let unsubscribe = null;
let page = null;

/** 水位状态映射（蓝图 11.4：绿<60% 黄 60-85% 红>85%） */
function levelOf(status) {
  const gpu = status?.gpu;
  if (!gpu || !gpu.total_mb) return 'unknown';
  const ratio = gpu.used_mb / gpu.total_mb;
  if (ratio < 0.6) return 'safe';
  if (ratio <= 0.85) return 'warn';
  return 'danger';
}

const LEVEL_META = {
  safe:   { label: '安全',   cls: 'ok' },
  warn:   { label: '紧张',   cls: 'warn' },
  danger: { label: '危险',   cls: 'bad' },
  unknown:{ label: '未知',   cls: 'muted' },
};

const SCENE_LABEL = {
  dialogue: '对话', comfy: '出图', h3: '视频', music: '音乐',
  game: '游戏', fooocus: '出图(Fooocus)', none: '空闲',
};

/* ========== 数据视图更新 ========== */

function updateView(status) {
  if (!page || !page.isConnected) return;
  updateVramBar(status);
  updateStats(status);
  updateActivity(status);
  const hint = page.querySelector('[data-refresh-hint]');
  if (hint) hint.textContent = `更新于 ${new Date().toLocaleTimeString()}`;
}

function updateVramBar(status) {
  const slot = page.querySelector('[data-l0]');
  if (!slot) return;
  empty(slot);
  const gpu = status?.gpu;
  const used = gpu?.used_mb ?? 0;
  const total = gpu?.total_mb ?? 0;
  const pct = total ? (used / total) * 100 : 0;
  const lv = levelOf(status);
  const meta = LEVEL_META[lv];

  const bar = el(`<div class="vram-bar">
    <div class="vram-bar__label">
      <span class="vram-bar__pct text-${meta.cls}">${fmtPct(pct)}</span>
      <span class="text-muted text-xs">已用 ${fmtMb(used)} / 共 ${fmtMb(total)}</span>
    </div>
    <div class="vram-bar__track">
      <div class="vram-bar__fill vram-bar__fill--${meta.cls}" style="width:${Math.min(pct, 100)}%"></div>
    </div>
    <div class="vram-bar__hint text-xs">水位状态：<span class="text-${meta.cls}">${meta.label}</span>
      ${status?.vram_ledger?.note ? ` · ${escapeHtml(status.vram_ledger.note)}` : ''}
    </div>
    <div class="vram-bar__segs flex gap-sm"></div>
  </div>`);

  // 分段占用标签
  if (status?.vram_ledger) {
    const l = status.vram_ledger;
    const segs = [
      { label: '对话模型', mb: l.ollama_loaded_mb, cls: 'primary' },
      { label: '生成引擎', mb: l.comfy_loaded_mb, cls: 'ok' },
      { label: '底噪', mb: l.noise_mb, cls: 'muted' },
    ];
    const seg = bar.querySelector('.vram-bar__segs');
    for (const s of segs) {
      const sw = total ? (s.mb / total) * 100 : 0;
      if (sw < 0.5) continue;
      seg.appendChild(el(`<span class="tag tag--${s.cls}" title="${escapeHtml(s.label)} ${fmtMb(s.mb)}">${escapeHtml(s.label)} ${fmtMb(s.mb)}</span>`));
    }
  }
  slot.appendChild(bar);
}

function updateStats(status) {
  const slot = page.querySelector('[data-stats]');
  if (!slot) return;
  empty(slot);
  const gpu = status?.gpu;
  const scene = status?.scene || 'none';
  const ollamaModels = status?.ollama?.models?.length || 0;
  const qosLevel = status?.qos?.level || '—';

  const cards = [
    { label: 'GPU 显存', value: gpu ? `${fmtMb(gpu.used_mb)} / ${fmtMb(gpu.total_mb, 0)}` : '—', hint: gpu ? `利用率 ${gpu.utilization ?? 0}%` : '未检测到 GPU' },
    { label: '当前场景', value: SCENE_LABEL[scene] || scene || '—', hint: '场景 = 一套模型组合' },
    { label: '活跃对话模型', value: String(ollamaModels), hint: '已加载的 ollama 模型数' },
    { label: 'QoS 水位', value: qosLevel, hint: status?.qos?.msg ? escapeHtml(status.qos.msg) : 'GREEN=安全' },
  ];

  const grid = el('<div class="grid grid-4 dashboard-stats"></div>');
  for (const c of cards) {
    grid.appendChild(el(`<div class="stat-card">
      <div class="stat-card__label">${escapeHtml(c.label)}</div>
      <div class="stat-card__value">${c.value}</div>
      <div class="stat-card__hint">${c.hint || ''}</div>
    </div>`));
  }
  slot.appendChild(grid);
}

function updateActivity(status) {
  const slot = page.querySelector('[data-lower]');
  if (!slot) return;
  empty(slot);
  const act = status?.activity?.services;
  if (!act || !Object.keys(act).length) {
    slot.appendChild(el('<div class="card"><div class="card__title">服务活跃度</div><div class="card__body text-muted text-sm mt-sm">暂无服务活跃记录</div></div>'));
    return;
  }
  const rows = Object.entries(act).map(([name, info]) => {
    const busy = info?.busy;
    const last = info?.last_busy ? new Date(info.last_busy * 1000).toLocaleTimeString() : '—';
    const idle = info?.idle_s ? `${Math.round(info.idle_s / 60)} 分钟` : '';
    return `<div class="activity-row flex justify-between">
      <span>${escapeHtml(name)} <span class="tag ${busy ? 'tag--ok' : 'tag--muted'}">${busy ? '忙碌' : '空闲'}</span></span>
      <span class="text-muted text-xs">最后忙碌 ${last}${idle ? ` · 空闲 ${idle}` : ''}</span>
    </div>`;
  }).join('');
  slot.appendChild(el(`<div class="card"><div class="card__title">服务活跃度</div><div class="card__body mt-sm">${rows}</div></div>`));
}

/* ========== 页面骨架 ========== */

function render() {
  page = el(`<div class="page dashboard-page">
    <div class="page-header flex justify-between items-center">
      <div>
        <div class="page-title">总览</div>
        <div class="page-subtitle">一眼看清系统忙不忙、谁在干活、安不安全</div>
      </div>
      <div class="text-xs text-muted font-mono" data-refresh-hint></div>
    </div>
    <div class="flex-col gap-lg">
      <div data-l0></div>
      <div data-actions></div>
      <div data-stats></div>
      <div class="grid grid-2" data-lower></div>
    </div>
  </div>`);

  // L1 动作（仅绑定一次）
  const actions = page.querySelector('[data-actions]');
  actions.appendChild(el(`<div class="dashboard-actions flex gap-md">
    <button class="btn btn--primary btn--lg" data-action="preview">🎼 预演模式</button>
    <button class="btn btn--lg" data-action="demo" style="background:rgba(168,85,247,.15);border:1px solid rgba(168,85,247,.4);color:#c4b5fd">🎬 一键演示</button>
    <button class="btn btn--ok btn--lg" data-action="free">🧹 一键释放</button>
  </div>`));

  actions.querySelector('[data-action="free"]').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = '释放中…';
    try {
      const result = await api.free();
      const msg = result?.message || '显存已释放';
      events.emit('toast', { type: 'success', message: msg });
      // 释放后延迟刷新：等 PowerShell 脚本实际执行完，显存数据才准确
      setTimeout(async () => { await refresh(); }, 3000);
      await refresh();  // 先立即刷新一次（可能还是旧数据，但按钮状态会恢复）
    } catch (err) {
      events.emit('toast', { type: 'error', message: err.message });
    } finally {
      btn.disabled = false;
      btn.textContent = '🧹 一键释放';
    }
  });

  actions.querySelector('[data-action="preview"]').addEventListener('click', openPreview);
  actions.querySelector('[data-action="demo"]').addEventListener('click', openDemo);

  return page;
}

/* ========== 预演模式（阶段5）：显存预算引擎 ========== */

function decisionTag(m) {
  if (m.decision === 'ok') return '<span class="tag tag--ok">可直接加载</span>';
  if (m.decision === 'free' || m.need_free_gb > 0) return `<span class="tag tag--warn">需释放 ${m.need_free_gb}G</span>`;
  if (m.gap_gb > 0) return `<span class="tag tag--bad">超限 ${m.gap_gb}G</span>`;
  return `<span class="tag tag--muted">${escapeHtml(String(m.decision || '—'))}</span>`;
}

function buildCtxSelect(m, overrides, onChange) {
  const ctxMap = m.context_vram || {};
  const keys = Object.keys(ctxMap);
  if (!keys.length) return el('<span class="text-muted text-xs">默认</span>');
  const sel = el('<select class="preview-ctx"></select>');
  for (const k of keys) {
    const opt = document.createElement('option');
    opt.value = k;
    opt.textContent = `${Math.round(Number(k) / 1024)}K → ${ctxMap[k]}G`;
    opt.selected = String(Number(m.specified_ctx ?? m.default_ctx)) === String(Number(k));
    sel.appendChild(opt);
  }
  sel.addEventListener('change', () => {
    if (Number(sel.value) === Number(m.default_ctx)) delete overrides[m.id];
    else overrides[m.id] = Number(sel.value);
    onChange();
  });
  return sel;
}

async function openPreview() {
  const body = el('<div class="preview"><div class="text-muted">正在核算显存预算…</div></div>');
  const close = openModal({ title: '🎼 预演模式 · 显存预算引擎', body, width: '780px' });
  let budget = null;
  try {
    budget = await api.budget();
  } catch (err) {
    body.innerHTML = `<div class="text-bad">预算加载失败：${escapeHtml(err.message)}</div>`;
    return;
  }
  const overrides = {};
  const render = async () => {
    try {
      const b = await api.budget(overrides);
      renderBudget(body, b, overrides, render);
    } catch (err) {
      body.innerHTML = `<div class="text-bad">重算失败：${escapeHtml(err.message)}</div>`;
    }
  };
  renderBudget(body, budget, overrides, render);
}

function renderBudget(body, b, overrides, rerender) {
  empty(body);
  if (!b?.ok) {
    body.innerHTML = `<div class="text-bad">预算不可用</div>`;
    return;
  }
  const usedPct = b.safe_ceiling_gb ? Math.min((b.used_gb / b.safe_ceiling_gb) * 100, 100) : 0;

  body.appendChild(el(`<div class="preview-overview card card--compact">
    <div class="flex justify-between items-center">
      <span><span class="tag tag--primary">安全上限 ${b.safe_ceiling_gb}G / ${b.total_gb}G</span></span>
      <span class="text-xs text-muted font-mono">已用 ${b.used_gb}G · 可释放 ${b.releasable_gb}G · 可用 ${b.avail_gb}G</span>
    </div>
    <div class="vram-bar__track mt-sm"><div class="vram-bar__fill vram-bar__fill--ok" style="width:${usedPct}%"></div></div>
    <div class="text-xs text-muted mt-sm">预演 = 只看不动：调整 Context 试算所需显存与加载决策，不会实际加载模型</div>
  </div>`));

  const table = el(`<table class="table mt-md">
    <thead><tr><th>模型</th><th>所需显存</th><th>决策</th><th>Context</th><th>预计耗时</th></tr></thead>
    <tbody></tbody>
  </table>`);
  const tbody = table.querySelector('tbody');
  for (const m of b.models || []) {
    const tr = el(`<tr>
      <td><div class="model-name">${escapeHtml(m.name)}</div><div class="text-xs text-muted">${escapeHtml(m.source)}${m.loaded ? ' · <span class="text-ok">已加载</span>' : ''}</div></td>
      <td class="font-mono">${m.vram_gb}G</td>
      <td>${decisionTag(m)}</td>
      <td></td>
      <td class="text-xs text-muted">${escapeHtml(m.est_time_text || '—')}</td>
    </tr>`);
    tr.children[3].appendChild(buildCtxSelect(m, overrides, rerender));
    tbody.appendChild(tr);
  }
  body.appendChild(table);
  body.appendChild(el(`<div class="text-xs text-muted mt-md">底噪 ${b.noise_gb}G + 系统保留 ${b.reserve_gb}G → 安全上限 ${b.safe_ceiling_gb}G</div>`));
}

/* ========== 数据加载 ========== */

async function refresh() {
  try {
    const data = await api.status();
    store.set('status', data);
  } catch (err) {
    // api.js 已广播 api:error
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(refresh, POLL_INTERVAL);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/* ========== 页面注册配置 ========== */

export default {
  title: '总览',
  render,
  onEnter: () => {
    refresh();
    startPolling();
    // 订阅状态变化 → 更新视图
    unsubscribe = store.subscribe('status', updateView);
  },
  onLeave: () => {
    stopPolling();
    if (unsubscribe) { unsubscribe(); unsubscribe = null; }
  },
};
