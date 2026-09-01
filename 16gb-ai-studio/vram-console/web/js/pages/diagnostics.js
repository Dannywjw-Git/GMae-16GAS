/**
 * GMae v2.0 - pages/diagnostics.js
 * 诊断中心：故障时间线 / 四层快照 / 健康检查（三个Tab）
 * D4 实现完整功能，当前为占位页
 */

import { el } from '../core/utils.js';
import TabNav from '../components/TabNav.js';

export function render() {
  const page = el(`<div class="page">
    <div class="page-header">
      <h1 class="page-title">诊断中心</h1>
      <p class="page-subtitle">故障根因分析：时间线 · 四层快照 · 健康检查</p>
    </div>
    <div data-tab-nav></div>
    <div data-tab-content></div>
  </div>`);

  const tab = TabNav.render({
    tabs: [
      { id: 'timeline', label: '故障时间线', icon: '⏱️' },
      { id: 'snapshot', label: '四层快照', icon: '🔍' },
      { id: 'check', label: '健康检查', icon: '✅' },
    ],
    default: 'timeline',
    onChange: (id) => renderTab(page, id),
  });
  page.querySelector('[data-tab-nav]').appendChild(tab.nav);
  renderTab(page, 'timeline');
  return page;
}

function renderTab(page, id) {
  const slot = page.querySelector('[data-tab-content]');
  if (!slot) return;
  const labels = { timeline: '故障时间线', snapshot: '四层快照', check: '健康检查' };
  slot.innerHTML = `<div class="loading-overlay">
    <div class="loading-overlay__inner">
      <div class="spinner" style="width:32px;height:32px"></div>
      <p>${labels[id] || id} — D4 实现</p>
    </div>
  </div>`;
}

export default { render };
