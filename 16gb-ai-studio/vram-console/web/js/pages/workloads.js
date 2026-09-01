/**
 * GMae v2.0 - pages/workloads.js
 * 工作负载：模型登记台 / 任务队列 / 场景切换（三个Tab）
 * D5 实现完整功能，当前为占位页
 */

import { el } from '../core/utils.js';
import TabNav from '../components/TabNav.js';

export function render() {
  const page = el(`<div class="page">
    <div class="page-header">
      <h1 class="page-title">工作负载</h1>
      <p class="page-subtitle">模型 · 队列 · 场景切换</p>
    </div>
    <div data-tab-nav></div>
    <div data-tab-content></div>
  </div>`);

  const tab = TabNav.render({
    tabs: [
      { id: 'models', label: '模型登记台', icon: '🤖' },
      { id: 'queue', label: '任务队列', icon: '📋' },
      { id: 'scenes', label: '场景切换', icon: '🎭' },
    ],
    default: 'models',
    onChange: (id) => renderTab(page, id),
  });
  page.querySelector('[data-tab-nav]').appendChild(tab.nav);
  renderTab(page, 'models');
  return page;
}

function renderTab(page, id) {
  const slot = page.querySelector('[data-tab-content]');
  if (!slot) return;
  const labels = { models: '模型登记台', queue: '任务队列', scenes: '场景切换' };
  slot.innerHTML = `<div class="loading-overlay">
    <div class="loading-overlay__inner">
      <div class="spinner" style="width:32px;height:32px"></div>
      <p>${labels[id] || id} — D5 实现</p>
    </div>
  </div>`;
}

export default { render };
