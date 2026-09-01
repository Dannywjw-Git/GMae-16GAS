/**
 * GMae v2.0 - pages/observability.js
 * 观测中心：显存账本 / 服务健康 / 事件日志（三个Tab）
 * D3 实现完整功能，当前为占位页
 */

import { el } from '../core/utils.js';
import TabNav from '../components/TabNav.js';

export function render() {
  const page = el(`<div class="page">
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
    onChange: (id) => renderTab(page, id),
  });
  page.querySelector('[data-tab-nav]').appendChild(tab.nav);
  renderTab(page, 'vram');
  return page;
}

function renderTab(page, id) {
  const slot = page.querySelector('[data-tab-content]');
  if (!slot) return;
  slot.innerHTML = `<div class="loading-overlay">
    <div class="loading-overlay__inner">
      <div class="spinner" style="width:32px;height:32px"></div>
      <p>${id === 'vram' ? '显存账本' : id === 'health' ? '服务健康' : '事件日志'} — D3 实现</p>
    </div>
  </div>`;
}

export default { render };
