/**
 * GMae v2.0 - pages/observability.js
 * 观测中心：显存账本 / 服务健康 / 事件日志（三个Tab）
 */

import { api } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, fmtMb, fmtPct } from '../core/utils.js';
import TabNav from '../components/TabNav.js';

// 通用 API 请求（新 v1 端点直接用 fetch）
async function apiGet(path) {
  const token = localStorage.getItem('gm_api_token') || '';
  const headers = { 'X-API-Key': token };
  const resp = await fetch(path, { headers });
  const data = await resp.json();
  return data.data || data;
}

async function apiPost(path, body = {}) {
  const token = localStorage.getItem('gm_api_token') || '';
  const headers = { 'X-API-Key': token, 'Content-Type': 'application/json' };
  const resp = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) });
  const data = await resp.json();
  return data.data || data;
}

let page = null;
let currentTab = 'vram';
let pollTimer = null;
let healthData = null;
let eventsData = null;
let statusData = null;

/* ========== 页面渲染 ========== */

export function render() {
  page = el(`<div class="page observability-page">
    <div class="page-header">
      <h1 class="page-title">观测中心</h1>
      <p class="page-subtitle">全栈可观测：显存账本 · 服务健康 · 事件日志</p>
    </div>
    <div data-tab-nav></div>
    <div data-tab-content></div>
  </div>`);

  const tab = TabNav.render({
    tabs: [
      { id: 'vram', label: '显存账本', icon: '📈' },
      { id: 'health', label: '服务健康', icon: '💚' },
      { id: 'events', label: '事件日志', icon: '📜' },
    ],
    default: 'vram',
    onChange: (id) => {
      currentTab = id;
      renderTab();
    },
  });
  page.querySelector('[data-tab-nav]').appendChild(tab.nav);
  return page;
}

export function onEnter() {
  startPolling();
  refresh();
}

export function onLeave() {
  stopPolling();
}

/* ========== 数据刷新 ========== */

async function refresh() {
  try {
    const [status, health, evts] = await Promise.all([
      api.status().catch(() => null),
      apiGet('/api/v1/health/services').catch(() => null),
      apiGet('/api/v1/events?limit=50').catch(() => null),
    ]);
    statusData = status;
    healthData = health;
    eventsData = evts;
    renderTab();
  } catch (err) {
    console.error('[observability] refresh error', err);
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(refresh, 10000);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/* ========== Tab 渲染 ========== */

function renderTab() {
  const slot = page?.querySelector('[data-tab-content]');
  if (!slot) return;
  empty(slot);

  if (currentTab === 'vram') renderVramTab(slot);
  else if (currentTab === 'health') renderHealthTab(slot);
  else if (currentTab === 'events') renderEventsTab(slot);
}

/* ---------- Tab1: 显存账本 ---------- */

function renderVramTab(slot) {
  if (!statusData?.gpu) {
    slot.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><p>加载中...</p></div>';
    return;
  }

  const gpu = statusData.gpu;
  const used = gpu.used_mb || 0;
  const total = gpu.total_mb || 1;
  const pct = (used / total) * 100;
  const ledger = statusData.vram_ledger || {};
  const processes = statusData.gpu_processes?.processes || [];

  const container = el(`<div class="observability-vram">
    <!-- 显存分布 -->
    <div class="card">
      <div class="card__title">显存分布</div>
      <div class="vram-overview">
        <div class="vram-overview__main">
          <div class="vram-overview__pct">${fmtPct(pct)}</div>
          <div class="vram-overview__detail">${fmtMb(used)} / ${fmtMb(total)}</div>
        </div>
        <div class="vram-bar">
          <div class="vram-bar__track">
            <div class="vram-bar__fill" style="width:${Math.min(pct, 100)}%;background:${pct > 85 ? '#ef4444' : pct > 60 ? '#f59e0b' : '#10b981'}"></div>
          </div>
        </div>
      </div>
      <!-- 分段占用 -->
      <div class="vram-segments">
        ${renderVramSegments(ledger)}
      </div>
    </div>

    <!-- 进程明细 -->
    <div class="card">
      <div class="card__header">
        <div class="card__title">进程明细 (${processes.length})</div>
        <button class="btn btn--sm btn--danger" data-action="free-all">一键释放</button>
      </div>
      <div class="data-table">
        <table>
          <thead>
            <tr>
              <th>PID</th>
              <th>进程名</th>
              <th>显存占用</th>
              <th>占比</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${processes.length === 0 ? '<tr><td colspan="5" class="text-muted text-center">无 GPU 进程</td></tr>' :
              processes.map(p => `
                <tr>
                  <td class="font-mono">${p.pid || '-'}</td>
                  <td>${p.name || '未知'}${p.app ? ` <span class="text-xs text-muted">(${p.app})</span>` : ''}</td>
                  <td>${fmtMb(p.used_mb || 0)}</td>
                  <td>${fmtPct(((p.used_mb || 0) / total) * 100)}</td>
                  <td><button class="btn btn--xs btn--ghost" data-kill-pid="${p.pid}">结束</button></td>
                </tr>
              `).join('')
            }
          </tbody>
        </table>
      </div>
    </div>
  </div>`);

  // 绑定操作
  container.querySelector('[data-action="free-all"]')?.addEventListener('click', async () => {
    try {
      await api.free();
      events.emit('toast', { type: 'success', message: '显存已释放' });
      refresh();
    } catch (err) {
      events.emit('toast', { type: 'error', message: '释放失败：' + err.message });
    }
  });

  container.querySelectorAll('[data-kill-pid]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const pid = btn.dataset.killPid;
      try {
        await api.post('/api/desktop/kill', { pid });
        events.emit('toast', { type: 'success', message: `进程 ${pid} 已结束` });
        refresh();
      } catch (err) {
        events.emit('toast', { type: 'error', message: '结束失败：' + err.message });
      }
    });
  });

  slot.appendChild(container);
}

function renderVramSegments(ledger) {
  const segs = [];
  const ollama = ledger.ollama_loaded_mb || 0;
  const comfy = ledger.comfy_loaded_mb || 0;
  const actual = ledger.actual_used_mb || 0;
  const other = Math.max(0, actual - ollama - comfy);

  if (ollama > 0) segs.push({ label: 'Ollama', value: ollama, color: '#8b5cf6' });
  if (comfy > 0) segs.push({ label: 'ComfyUI', value: comfy, color: '#3b82f6' });
  if (other > 0) segs.push({ label: '其它/系统', value: other, color: '#6b7280' });

  if (segs.length === 0) {
    const note = ledger.note || ledger.state || '暂无分段数据';
    return `<div class="text-muted text-sm">${note}</div>`;
  }

  const total = segs.reduce((s, x) => s + x.value, 0) || 1;
  return `
    <div class="vram-seg-bar">
      ${segs.map(s => `<div class="vram-seg" style="width:${(s.value / total) * 100}%;background:${s.color}" title="${s.label}: ${fmtMb(s.value)}"></div>`).join('')}
    </div>
    <div class="vram-seg-legend">
      ${segs.map(s => `
        <div class="vram-seg-legend__item">
          <span class="vram-seg-legend__dot" style="background:${s.color}"></span>
          <span>${s.label}</span>
          <span class="text-muted">${fmtMb(s.value)}</span>
        </div>
      `).join('')}
    </div>
  `;
}

/* ---------- Tab2: 服务健康 ---------- */

function renderHealthTab(slot) {
  if (!healthData?.services) {
    slot.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><p>加载中...</p></div>';
    return;
  }

  const services = Object.entries(healthData.services);
  const summary = healthData.summary || {};

  const container = el(`<div class="observability-health">
    <!-- 汇总卡片 -->
    <div class="status-card-grid" style="grid-template-columns:repeat(4,1fr)">
      <div class="status-card" data-status="ok">
        <div class="status-card__header"><span>总计</span></div>
        <div class="status-card__value">${summary.total || 0}</div>
      </div>
      <div class="status-card" data-status="ok">
        <div class="status-card__header"><span>运行中</span></div>
        <div class="status-card__value text-ok">${summary.running || 0}</div>
      </div>
      <div class="status-card" data-status="warning">
        <div class="status-card__header"><span>已停止</span></div>
        <div class="status-card__value text-warn">${summary.stopped || 0}</div>
      </div>
      <div class="status-card" data-status="error">
        <div class="status-card__header"><span>不可达</span></div>
        <div class="status-card__value text-bad">${summary.unreachable || 0}</div>
      </div>
    </div>

    <!-- 服务列表 -->
    <div class="card">
      <div class="card__header">
        <div class="card__title">服务列表 (${services.length})</div>
        <button class="btn btn--sm btn--primary" data-action="probe-all">立即探测</button>
      </div>
      <div class="data-table">
        <table>
          <thead>
            <tr>
              <th>服务</th>
              <th>类型</th>
              <th>状态</th>
              <th>延迟</th>
              <th>错误率</th>
              <th>最后检查</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${services.length === 0 ? '<tr><td colspan="7" class="text-muted text-center">无监控服务</td></tr>' :
              services.map(([sid, svc]) => {
                const status = svc.status || 'unknown';
                const statusLabel = { running: '运行中', stopped: '已停止', unreachable: '不可达', timeout: '超时', unknown: '未知' }[status] || status;
                const statusCls = { running: 'text-ok', stopped: 'text-muted', unreachable: 'text-bad', timeout: 'text-warn', unknown: 'text-muted' }[status] || '';
                const latency = svc.latency_ms != null ? `${svc.latency_ms}ms` : '-';
                const errorRate = svc.error_rate != null ? fmtPct(svc.error_rate * 100) : '-';
                const lastCheck = svc.last_check ? new Date(svc.last_check * 1000).toLocaleTimeString() : '-';
                return `
                  <tr>
                    <td><strong>${svc.name || sid}</strong><div class="text-xs text-muted">${svc.container || svc.url || ''}</div></td>
                    <td>${svc.type || '-'}</td>
                    <td class="${statusCls}">● ${statusLabel}</td>
                    <td class="font-mono">${latency}</td>
                    <td class="font-mono">${errorRate}</td>
                    <td class="text-xs">${lastCheck}</td>
                    <td><button class="btn btn--xs btn--ghost" data-probe-id="${sid}">探测</button></td>
                  </tr>
                `;
              }).join('')
            }
          </tbody>
        </table>
      </div>
    </div>
  </div>`);

  // 绑定操作
  container.querySelector('[data-action="probe-all"]')?.addEventListener('click', async () => {
    try {
      await apiPost('/api/v1/health/probe', {});
      events.emit('toast', { type: 'success', message: '已触发全量探测' });
      refresh();
    } catch (err) {
      events.emit('toast', { type: 'error', message: '探测失败：' + err.message });
    }
  });

  container.querySelectorAll('[data-probe-id]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const sid = btn.dataset.probeId;
      try {
        await apiPost('/api/v1/health/probe', { id: sid });
        events.emit('toast', { type: 'success', message: `已探测 ${sid}` });
        refresh();
      } catch (err) {
        events.emit('toast', { type: 'error', message: '探测失败：' + err.message });
      }
    });
  });

  slot.appendChild(container);
}

/* ---------- Tab3: 事件日志 ---------- */

function renderEventsTab(slot) {
  if (!eventsData) {
    slot.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><p>加载中...</p></div>';
    return;
  }

  const evts = Array.isArray(eventsData) ? eventsData : [];

  const container = el(`<div class="observability-events">
    <!-- 筛选栏 -->
    <div class="card">
      <div class="events-filter">
        <select class="form-input" data-filter="level">
          <option value="">全部级别</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="critical">Critical</option>
        </select>
        <select class="form-input" data-filter="service">
          <option value="">全部服务</option>
          ${[...new Set(evts.map(e => e.service).filter(Boolean))].map(s => `<option value="${s}">${s}</option>`).join('')}
        </select>
        <input type="text" class="form-input" data-filter="keyword" placeholder="搜索关键词..." style="flex:1">
        <button class="btn btn--sm btn--primary" data-action="refresh">刷新</button>
      </div>
    </div>

    <!-- 事件列表 -->
    <div class="card">
      <div class="card__title">事件流 (${evts.length})</div>
      <div class="events-list">
        ${evts.length === 0 ? '<div class="text-muted text-center py-4">暂无事件</div>' :
          evts.map(e => {
            const levelCls = { info: 'event--info', warning: 'event--warning', error: 'event--error', critical: 'event--critical' }[e.level] || '';
            const time = e.ts ? new Date(e.ts).toLocaleString() : '-';
            const meta = e.metadata && Object.keys(e.metadata).length > 0
              ? `<details class="event-meta"><summary>详情</summary><pre>${JSON.stringify(e.metadata, null, 2)}</pre></details>`
              : '';
            return `
              <div class="event-item ${levelCls}">
                <div class="event-item__time">${time}</div>
                <div class="event-item__level">${e.level?.toUpperCase()}</div>
                <div class="event-item__service">${e.service || '-'}</div>
                <div class="event-item__content">
                  <div class="event-item__type">${e.event_type}</div>
                  <div class="event-item__msg">${e.message || ''}</div>
                  ${meta}
                </div>
              </div>
            `;
          }).join('')
        }
      </div>
    </div>
  </div>`);

  // 绑定筛选
  container.querySelectorAll('[data-filter]').forEach(el => {
    el.addEventListener('change', () => applyFilter(container));
    el.addEventListener('input', () => applyFilter(container));
  });
  container.querySelector('[data-action="refresh"]')?.addEventListener('click', refresh);

  slot.appendChild(container);
}

function applyFilter(container) {
  const level = container.querySelector('[data-filter="level"]').value;
  const service = container.querySelector('[data-filter="service"]').value;
  const keyword = container.querySelector('[data-filter="keyword"]').value.toLowerCase();

  container.querySelectorAll('.event-item').forEach(item => {
    let show = true;
    if (level && !item.classList.contains(`event--${level}`)) show = false;
    if (service && !item.querySelector('.event-item__service')?.textContent.includes(service)) show = false;
    if (keyword && !item.textContent.toLowerCase().includes(keyword)) show = false;
    item.style.display = show ? '' : 'none';
  });
}

export default { render, onEnter, onLeave };
