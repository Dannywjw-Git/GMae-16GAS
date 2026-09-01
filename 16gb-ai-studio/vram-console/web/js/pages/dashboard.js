/**
 * GMae v2.0 - pages/dashboard.js
 * 总览页：健康四卡片 + 告警面板 + 关键指标趋势 + 快速操作
 *
 * 信息架构：
 * - L0：健康四卡片（GPU/容器/模型/队列）一眼看全局
 * - L1：告警面板（最近异常，按严重程度排序）
 * - L2：关键指标趋势（显存/延迟/队列长度）
 * - L3：快速操作（一键释放/场景切换快捷入口）
 */

import { api } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, fmtMb, fmtPct } from '../core/utils.js';
import { go } from '../core/router.js';
import StatusCard from '../components/StatusCard.js';

const POLL_INTERVAL = 10000;
let pollTimer = null;
let page = null;
let statusData = null;
let vramHistory = []; // 显存历史（最近30个点）

/* ========== 页面渲染 ========== */

export function render() {
  page = el(`<div class="page dashboard-page">
    <div class="page-header">
      <h1 class="page-title">总览</h1>
      <p class="page-subtitle">全局健康状态一眼掌握，异常及时发现</p>
    </div>

    <!-- L0：健康四卡片 -->
    <div data-health-cards class="status-card-grid" style="grid-template-columns:repeat(4,1fr)"></div>

    <!-- L1：告警面板 -->
    <div class="dashboard-section">
      <div class="dashboard-section__header">
        <h2 class="dashboard-section__title">⚠️ 最近告警</h2>
        <span data-alert-count class="text-xs text-muted"></span>
      </div>
      <div data-alerts class="dashboard-alerts"></div>
    </div>

    <!-- L2：关键指标趋势 -->
    <div class="dashboard-section">
      <div class="dashboard-section__header">
        <h2 class="dashboard-section__title">📈 关键指标趋势</h2>
        <span data-refresh-hint class="text-xs text-muted"></span>
      </div>
      <div class="grid grid-2">
        <div class="dashboard-chart-card">
          <div class="dashboard-chart-card__title">显存使用趋势</div>
          <canvas data-vram-chart width="400" height="150"></canvas>
        </div>
        <div class="dashboard-chart-card">
          <div class="dashboard-chart-card__title">服务状态</div>
          <div data-services-list></div>
        </div>
      </div>
    </div>

    <!-- L3：快速操作 -->
    <div class="dashboard-section">
      <div class="dashboard-section__header">
        <h2 class="dashboard-section__title">⚡ 快速操作</h2>
      </div>
      <div class="dashboard-actions">
        <button class="btn btn--primary" data-action="free">🧹 一键释放显存</button>
        <button class="btn btn--ghost" data-action="scene-comfy">🎨 切换到出图场景</button>
        <button class="btn btn--ghost" data-action="scene-dialogue">💬 切换到对话场景</button>
        <button class="btn btn--ghost" data-action="observability">🔍 查看观测中心</button>
        <button class="btn btn--ghost" data-action="diagnostics">🩺 进入诊断中心</button>
      </div>
    </div>
  </div>`);

  bindActions(page);
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
    statusData = await api.status();
    updateView();
  } catch (err) {
    console.error('[dashboard] refresh error', err);
    events.emit('toast', { type: 'error', message: '状态刷新失败：' + err.message });
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(refresh, POLL_INTERVAL);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/* ========== 视图更新 ========== */

function updateView() {
  if (!page || !page.isConnected || !statusData) return;
  updateHealthCards();
  updateAlerts();
  updateVramChart();
  updateServices();
  const hint = page.querySelector('[data-refresh-hint]');
  if (hint) hint.textContent = `更新于 ${new Date().toLocaleTimeString()}`;
}

/* ---------- 健康四卡片 ---------- */

function updateHealthCards() {
  const slot = page.querySelector('[data-health-cards]');
  if (!slot) return;
  empty(slot);

  const gpu = statusData.gpu || {};
  const containers = statusData.containers || {};
  const queue = statusData.comfy_queue || {};
  const models = statusData.comfyui_models || {};

  // GPU 卡片
  const gpuUsed = gpu.used_mb || 0;
  const gpuTotal = gpu.total_mb || 1;
  const gpuPct = (gpuUsed / gpuTotal) * 100;
  const gpuStatus = gpuPct > 85 ? 'error' : gpuPct > 60 ? 'warning' : 'ok';
  slot.appendChild(StatusCard.render({
    title: 'GPU 显存',
    value: `${fmtMb(gpuUsed)} / ${fmtMb(gpuTotal)}`,
    status: gpuStatus,
    subtitle: `使用率 ${fmtPct(gpuPct)} · 利用率 ${gpu.utilization || 0}%`,
    icon: '🎮',
    trend: vramHistory.slice(-20),
    action: { label: '查看账本', onClick: () => go('observability') },
  }));

  // 容器卡片
  const allContainers = containers.all || [];
  const runningCount = allContainers.filter(c =>
    containers[c] === true || (containers.comfyui && c === 'comfyui') ||
    (containers.fooocus && c === 'fooocus')
  ).length;
  const containerStatus = allContainers.length > 0 && runningCount === allContainers.length ? 'ok'
    : runningCount > 0 ? 'warning' : 'error';
  slot.appendChild(StatusCard.render({
    title: '运行中服务',
    value: `${runningCount} / ${allContainers.length}`,
    status: containerStatus,
    subtitle: allContainers.join(', ') || '无容器',
    icon: '📦',
    action: { label: '服务健康', onClick: () => go('observability') },
  }));

  // 模型卡片
  const loadedModels = models.models || [];
  const modelVram = loadedModels.reduce((sum, m) => sum + (m.vram_mb || 0), 0);
  const modelStatus = loadedModels.length > 0 ? 'warning' : 'ok';
  slot.appendChild(StatusCard.render({
    title: '已加载模型',
    value: `${loadedModels.length} 个`,
    status: modelStatus,
    subtitle: `占用 ${fmtMb(modelVram)}`,
    icon: '🤖',
    action: { label: '模型管理', onClick: () => go('workloads') },
  }));

  // 队列卡片
  const queueRunning = queue.running ? 1 : 0;
  const queuePending = (queue.pending || []).length;
  const queueStatus = queuePending > 5 ? 'warning' : 'ok';
  slot.appendChild(StatusCard.render({
    title: '任务队列',
    value: `${queuePending} 等待 · ${queueRunning} 运行`,
    status: queueStatus,
    subtitle: queuePending > 0 ? `有 ${queuePending} 个任务等待中` : '队列空闲',
    icon: '📋',
    action: { label: '查看队列', onClick: () => go('workloads') },
  }));
}

/* ---------- 告警面板 ---------- */

function updateAlerts() {
  const slot = page.querySelector('[data-alerts]');
  const countEl = page.querySelector('[data-alert-count]');
  if (!slot) return;
  empty(slot);

  const alerts = generateAlerts();
  if (countEl) countEl.textContent = `${alerts.length} 条`;

  if (alerts.length === 0) {
    slot.innerHTML = '<div class="dashboard-alerts__empty">✅ 系统运行正常，暂无告警</div>';
    return;
  }

  alerts.forEach(alert => {
    const item = el(`<div class="dashboard-alert dashboard-alert--${alert.level}">
      <span class="dashboard-alert__icon">${alert.icon}</span>
      <div class="dashboard-alert__content">
        <div class="dashboard-alert__title">${alert.title}</div>
        <div class="dashboard-alert__desc">${alert.desc}</div>
      </div>
      <span class="dashboard-alert__time">${alert.time}</span>
    </div>`);
    slot.appendChild(item);
  });
}

function generateAlerts() {
  const alerts = [];
  const gpu = statusData.gpu || {};
  const gpuPct = gpu.total_mb ? (gpu.used_mb / gpu.total_mb) * 100 : 0;
  const now = new Date().toLocaleTimeString();

  if (gpuPct > 85) {
    alerts.push({
      level: 'error', icon: '🔴',
      title: '显存使用危险',
      desc: `当前使用率 ${fmtPct(gpuPct)}，超过 85% 阈值，可能导致 OOM`,
      time: now,
    });
  } else if (gpuPct > 60) {
    alerts.push({
      level: 'warning', icon: '🟡',
      title: '显存使用偏高',
      desc: `当前使用率 ${fmtPct(gpuPct)}，建议关注`,
      time: now,
    });
  }

  const containers = statusData.containers || {};
  const all = containers.all || [];
  const stopped = all.filter(c => !containers[c]);
  if (stopped.length > 0 && all.length > 0) {
    alerts.push({
      level: 'warning', icon: '⚠️',
      title: '部分服务未运行',
      desc: `未运行：${stopped.join(', ')}`,
      time: now,
    });
  }

  const queue = statusData.comfy_queue || {};
  const pending = (queue.pending || []).length;
  if (pending > 5) {
    alerts.push({
      level: 'warning', icon: '⏳',
      title: '任务队列堆积',
      desc: `当前有 ${pending} 个任务等待执行`,
      time: now,
    });
  }

  const qos = statusData.qos || {};
  if (qos.degraded) {
    alerts.push({
      level: 'warning', icon: '🛡️',
      title: 'QoS 降级中',
      desc: qos.msg || '服务质量已降级',
      time: now,
    });
  }

  return alerts.slice(0, 5); // 最多显示5条
}

/* ---------- 显存趋势图 ---------- */

function updateVramChart() {
  const canvas = page.querySelector('[data-vram-chart]');
  if (!canvas || !statusData?.gpu) return;

  const gpu = statusData.gpu;
  vramHistory.push(gpu.used_mb || 0);
  if (vramHistory.length > 30) vramHistory.shift();

  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  const pad = { top: 10, right: 10, bottom: 20, left: 50 };

  ctx.clearRect(0, 0, w, h);

  if (vramHistory.length < 2) return;

  const total = gpu.total_mb || 16384;
  const maxVal = total;
  const data = vramHistory;

  // 绘制网格
  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (i / 4) * (h - pad.top - pad.bottom);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(w - pad.right, y);
    ctx.stroke();
    // Y轴标签
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(fmtMb(maxVal - (i / 4) * maxVal), pad.left - 5, y + 3);
  }

  // 绘制折线
  const gradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
  const lastPct = (data[data.length - 1] / total) * 100;
  const color = lastPct > 85 ? '#ef4444' : lastPct > 60 ? '#f59e0b' : '#10b981';
  gradient.addColorStop(0, color + '60');
  gradient.addColorStop(1, color + '00');

  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  data.forEach((v, i) => {
    const x = pad.left + (i / (data.length - 1)) * (w - pad.left - pad.right);
    const y = pad.top + (1 - v / maxVal) * (h - pad.top - pad.bottom);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // 填充
  ctx.lineTo(w - pad.right, h - pad.bottom);
  ctx.lineTo(pad.left, h - pad.bottom);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  // 当前值标签
  const lastX = w - pad.right;
  const lastY = pad.top + (1 - data[data.length - 1] / maxVal) * (h - pad.top - pad.bottom);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
  ctx.fill();
}

/* ---------- 服务状态列表 ---------- */

function updateServices() {
  const slot = page.querySelector('[data-services-list]');
  if (!slot) return;
  empty(slot);

  const containers = statusData.containers || {};
  const all = containers.all || [];

  if (all.length === 0) {
    slot.innerHTML = '<div class="text-muted text-sm">无监控服务</div>';
    return;
  }

  all.forEach(name => {
    const running = containers[name];
    const item = el(`<div class="service-row">
      <span class="status-dot" style="background:${running ? '#10b981' : '#6b7280'}"></span>
      <span class="service-row__name">${name}</span>
      <span class="service-row__status">${running ? '运行中' : '已停止'}</span>
    </div>`);
    slot.appendChild(item);
  });
}

/* ========== 操作绑定 ========== */

function bindActions(pageEl) {
  pageEl.querySelector('[data-action="free"]')?.addEventListener('click', async () => {
    try {
      await api.free();
      events.emit('toast', { type: 'success', message: '显存已释放' });
      refresh();
    } catch (err) {
      events.emit('toast', { type: 'error', message: '释放失败：' + err.message });
    }
  });

  pageEl.querySelector('[data-action="scene-comfy"]')?.addEventListener('click', async () => {
    try {
      await api.scene('comfy');
      events.emit('toast', { type: 'success', message: '已切换到出图场景' });
      refresh();
    } catch (err) {
      events.emit('toast', { type: 'error', message: '切换失败：' + err.message });
    }
  });

  pageEl.querySelector('[data-action="scene-dialogue"]')?.addEventListener('click', async () => {
    try {
      await api.scene('dialogue');
      events.emit('toast', { type: 'success', message: '已切换到对话场景' });
      refresh();
    } catch (err) {
      events.emit('toast', { type: 'error', message: '切换失败：' + err.message });
    }
  });

  pageEl.querySelector('[data-action="observability"]')?.addEventListener('click', () => go('observability'));
  pageEl.querySelector('[data-action="diagnostics"]')?.addEventListener('click', () => go('diagnostics'));
}

export default { render, onEnter, onLeave };
