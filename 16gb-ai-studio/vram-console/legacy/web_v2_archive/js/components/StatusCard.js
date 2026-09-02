/**
 * GMae v2.0 - components/StatusCard.js
 * 状态卡片组件：展示关键指标 + 状态点 + 趋势
 *
 * 用法：
 *   const card = StatusCard.render({
 *     title: 'GPU 显存',
 *     value: '6.2 / 16 GB',
 *     status: 'warning',  // ok / warning / error / unknown
 *     subtitle: '使用率 39%',
 *     trend: [10, 20, 15, 30, 25],  // 可选，迷你趋势图数据
 *     action: { label: '详情', onClick: () => go('observability') }  // 可选
 *   });
 */

import { el } from '../core/utils.js';

const STATUS_COLORS = {
  ok: 'var(--success)',
  warning: 'var(--warning)',
  error: 'var(--danger)',
  unknown: 'var(--muted)',
};

const STATUS_LABELS = {
  ok: '正常',
  warning: '警告',
  error: '异常',
  unknown: '未知',
};

/**
 * 渲染状态卡片
 * @param {object} opts
 * @param {string} opts.title - 卡片标题
 * @param {string} opts.value - 主数值
 * @param {string} [opts.status='unknown'] - 状态：ok/warning/error/unknown
 * @param {string} [opts.subtitle] - 副标题/说明
 * @param {number[]} [opts.trend] - 迷你趋势图数据（最近N个点）
 * @param {object} [opts.action] - 操作按钮 {label, onClick}
 * @param {string} [opts.icon] - 图标 emoji
 * @returns {HTMLElement}
 */
export function render(opts = {}) {
  const {
    title = '',
    value = '-',
    status = 'unknown',
    subtitle = '',
    trend = null,
    action = null,
    icon = '',
  } = opts;

  const statusColor = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  const statusLabel = STATUS_LABELS[status] || STATUS_LABELS.unknown;

  const card = el(`<div class="status-card" data-status="${status}">
    <div class="status-card__header">
      <div class="status-card__title">
        ${icon ? `<span class="status-card__icon">${icon}</span>` : ''}
        <span>${title}</span>
      </div>
      <span class="status-card__status" style="color:${statusColor}">
        <span class="status-dot" style="background:${statusColor}"></span>
        ${statusLabel}
      </span>
    </div>
    <div class="status-card__value">${value}</div>
    ${subtitle ? `<div class="status-card__subtitle">${subtitle}</div>` : ''}
    ${trend ? `<canvas class="status-card__trend" width="200" height="40"></canvas>` : ''}
    ${action ? `<button class="btn btn--sm btn--ghost status-card__action">${action.label}</button>` : ''}
  </div>`);

  // 绑定操作按钮
  if (action && typeof action.onClick === 'function') {
    card.querySelector('.status-card__action')?.addEventListener('click', action.onClick);
  }

  // 绘制迷你趋势图
  if (trend && trend.length > 1) {
    const canvas = card.querySelector('.status-card__trend');
    if (canvas) {
      requestAnimationFrame(() => drawTrend(canvas, trend, statusColor));
    }
  }

  return card;
}

/**
 * 绘制迷你趋势图（sparkline）
 * @param {HTMLCanvasElement} canvas
 * @param {number[]} data
 * @param {string} color
 */
function drawTrend(canvas, data, color) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  const pad = 4;

  ctx.clearRect(0, 0, w, h);

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  // 绘制折线
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.lineJoin = 'round';

  data.forEach((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // 填充渐变
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, color + '40');
  grad.addColorStop(1, color + '00');
  ctx.lineTo(w - pad, h - pad);
  ctx.lineTo(pad, h - pad);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();
}

/**
 * 批量渲染状态卡片网格
 * @param {object[]} cards - 卡片配置数组
 * @param {number} [cols=4] - 列数
 * @returns {HTMLElement}
 */
export function renderGrid(cards = [], cols = 4) {
  const grid = el(`<div class="status-card-grid" style="grid-template-columns:repeat(${cols},1fr)"></div>`);
  cards.forEach((c) => grid.appendChild(render(c)));
  return grid;
}

export default { render, renderGrid };
