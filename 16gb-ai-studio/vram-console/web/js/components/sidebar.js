/**
 * GMae 指挥家 v2.0 - components/sidebar.js
 * 左侧导航栏（蓝图 11.2：240px，可折叠 64px）
 * 8 个功能页导航，响应路由变化高亮当前页
 */

import { el } from '../core/utils.js';
import { events } from '../core/events.js';
import { go } from '../core/router.js';

/** 导航项（name 需与 router.register 的页面名一致）
 *  v2.0 信息架构：总览 / 观测 / 诊断 / 工作负载 / 设置
 */
const NAV_ITEMS = [
  { name: 'dashboard', label: '总览', icon: '📊' },
  { name: 'observability', label: '观测中心', icon: '🔍' },
  { name: 'diagnostics', label: '诊断中心', icon: '🩺' },
  { name: 'workloads', label: '工作负载', icon: '⚙️' },
  { name: 'settings', label: '设置', icon: '⚙️' },
];

let sidebarNode = null;
let navNode = null;

function buildNav() {
  navNode = el('<nav class="sidebar__nav"></nav>');
  for (const item of NAV_ITEMS) {
    const a = el(`<a class="sidebar__item" href="#/${item.name}" data-nav="${item.name}" title="${item.label}">
      <span class="sidebar__icon">${item.icon}</span>
      <span class="sidebar__label">${item.label}</span>
    </a>`);
    a.addEventListener('click', (e) => {
      e.preventDefault();
      go(item.name);
    });
    navNode.appendChild(a);
  }
  return navNode;
}

/** 高亮当前激活项 */
function highlight(name) {
  if (!navNode) return;
  navNode.querySelectorAll('[data-nav]').forEach((item) => {
    item.classList.toggle('sidebar__item--active', item.dataset.nav === name);
  });
}

/** 折叠/展开 */
export function toggleCollapsed() {
  if (!sidebarNode) return;
  sidebarNode.classList.toggle('sidebar--collapsed');
  const collapsed = sidebarNode.classList.contains('sidebar--collapsed');
  if (collapsed) {
    sidebarNode.querySelectorAll('.sidebar__label').forEach((l) => (l.style.display = 'none'));
  } else {
    sidebarNode.querySelectorAll('.sidebar__label').forEach((l) => (l.style.display = ''));
  }
}

/** 渲染侧边栏（仅调用一次） */
export function render() {
  sidebarNode = el(`<aside class="sidebar">
    <div class="sidebar__logo" title="GPU Maestro">
      <span class="sidebar__logo-icon">🎼</span>
      <span class="sidebar__logo-text">GMae 指挥家</span>
    </div>
    <div class="sidebar__footer">
      <button class="btn btn--icon" data-collapse title="折叠侧边栏">◀</button>
    </div>
  </aside>`);

  // 直接 append 导航节点（保证 navNode 引用真实 DOM，高亮才生效）
  const nav = buildNav();
  sidebarNode.insertBefore(nav, sidebarNode.querySelector('.sidebar__footer'));

  sidebarNode.querySelector('[data-collapse]').addEventListener('click', toggleCollapsed);

  // 路由变化高亮
  events.on('route:change', ({ name }) => highlight(name));

  return sidebarNode;
}

export default { render, toggleCollapsed };
