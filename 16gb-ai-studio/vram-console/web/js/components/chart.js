/**
 * GMae 指挥家 v2.0 - components/chart.js
 * 轻量 SVG 图表（无第三方依赖）：折线图 / 柱状图 / 饼图
 * 全部返回 SVG 元素；颜色走 CSS 变量主题
 */

import { el } from '../core/utils.js';

const NS = 'http://www.w3.org/2000/svg';

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

/**
 * 折线图（显存趋势等）
 * @param {Array<{label:string, value:number}>} data
 * @param {object} opts { width, height, color, fill, yLabel, yMax }
 */
export function lineChart(data, opts = {}) {
  const w = opts.width || 600;
  const h = opts.height || 180;
  const pad = { top: 20, right: 16, bottom: 28, left: 44 };
  const color = opts.color || 'var(--primary-light)';

  if (!data || data.length < 2) {
    return el(`<div class="chart chart__empty">暂无趋势数据</div>`);
  }

  const values = data.map((d) => d.value);
  const yMax = opts.yMax || Math.max(...values, 1) * 1.1;
  const yMin = 0;
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const x = (i) => pad.left + (plotW * i) / (data.length - 1);
  const y = (v) => pad.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, class: 'chart chart--line' });

  // 网格线 + Y 轴标签
  const gridLines = 4;
  for (let i = 0; i <= gridLines; i++) {
    const v = yMin + ((yMax - yMin) * i) / gridLines;
    const gy = y(v);
    svg.appendChild(svgEl('line', { x1: pad.left, y1: gy, x2: w - pad.right, y2: gy, stroke: 'var(--line-dark)', 'stroke-width': 1 }));
    const txt = svgEl('text', { x: pad.left - 6, y: gy + 4, 'text-anchor': 'end', class: 'chart__label' });
    txt.textContent = Math.round(v);
    svg.appendChild(txt);
  }

  // 折线
  const points = data.map((d, i) => `${x(i)},${y(d.value)}`).join(' ');
  svg.appendChild(svgEl('polyline', {
    points, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
  }));

  // 填充
  const fillPoints = `${pad.left},${pad.top + plotH} ${points} ${x(data.length - 1)},${pad.top + plotH}`;
  svg.appendChild(svgEl('polygon', { points: fillPoints, fill: color, opacity: 0.12 }));

  // 数据点 + X 轴标签
  data.forEach((d, i) => {
    svg.appendChild(svgEl('circle', { cx: x(i), cy: y(d.value), r: 3, fill: color }));
    const lbl = svgEl('text', { x: x(i), y: h - 8, 'text-anchor': 'middle', class: 'chart__label' });
    lbl.textContent = d.label;
    svg.appendChild(lbl);
  });

  return svg;
}

/**
 * 柱状图
 * @param {Array<{label:string, value:number, color?:string}>} data
 */
export function barChart(data, opts = {}) {
  const w = opts.width || 600;
  const h = opts.height || 200;
  const pad = { top: 20, right: 16, bottom: 28, left: 44 };
  const yMax = opts.yMax || Math.max(...data.map((d) => d.value), 1) * 1.1;
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const barW = Math.min(48, (plotW / data.length) * 0.6);

  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, class: 'chart chart--bar' });
  const step = plotW / data.length;

  data.forEach((d, i) => {
    const bh = (d.value / yMax) * plotH;
    const bx = pad.left + step * i + (step - barW) / 2;
    const by = pad.top + plotH - bh;
    svg.appendChild(svgEl('rect', {
      x: bx, y: by, width: barW, height: bh,
      rx: 3, fill: d.color || 'var(--primary)',
    }));
    const lbl = svgEl('text', { x: bx + barW / 2, y: by - 5, 'text-anchor': 'middle', class: 'chart__label' });
    lbl.textContent = d.value;
    svg.appendChild(lbl);
    const xl = svgEl('text', { x: bx + barW / 2, y: h - 8, 'text-anchor': 'middle', class: 'chart__label' });
    xl.textContent = d.label;
    svg.appendChild(xl);
  });

  return svg;
}

/**
 * 饼图/环形图
 * @param {Array<{label:string, value:number, color?:string}>} data
 * @param {object} opts { size, thickness }
 */
export function pieChart(data, opts = {}) {
  const size = opts.size || 200;
  const thickness = opts.thickness || 26;
  const cx = size / 2, cy = size / 2;
  const r = (size - thickness) / 2;

  if (!data || !data.length || data.every((d) => !d.value)) {
    return el(`<div class="chart chart__empty">暂无数据</div>`);
  }

  const total = data.reduce((s, d) => s + d.value, 0);
  const palette = ['#4250af', '#4caf50', '#ff9800', '#f44336', '#2196f3', '#9c27b0', '#009688', '#795548'];
  const svg = svgEl('svg', { viewBox: `0 0 ${size} ${size}`, class: 'chart chart--pie' });

  let angle = -90;
  data.forEach((d, i) => {
    if (!d.value) return;
    const frac = d.value / total;
    const sweep = frac * 360;
    const largeArc = sweep > 180 ? 1 : 0;
    const a1 = (angle * Math.PI) / 180;
    const a2 = ((angle + sweep) * Math.PI) / 180;
    const x1 = cx + r * Math.cos(a1);
    const y1 = cy + r * Math.sin(a1);
    const x2 = cx + r * Math.cos(a2);
    const y2 = cy + r * Math.sin(a2);
    const ir = r - thickness;
    const ix1 = cx + ir * Math.cos(a2);
    const iy1 = cy + ir * Math.sin(a2);
    const ix2 = cx + ir * Math.cos(a1);
    const iy2 = cy + ir * Math.sin(a1);

    const path = `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} L ${ix1} ${iy1} A ${ir} ${ir} 0 ${largeArc} 0 ${ix2} ${iy2} Z`;
    svg.appendChild(svgEl('path', { d: path, fill: d.color || palette[i % palette.length] }));
    angle += sweep;
  });

  return svg;
}

export default { lineChart, barChart, pieChart };
