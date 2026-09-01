/**
 * GMae v2.0 - components/TabNav.js
 * Tab 导航组件：页面内二级导航
 *
 * 用法：
 *   const tab = TabNav.render({
 *     tabs: [
 *       { id: 'vram', label: '显存账本', icon: '📈' },
 *       { id: 'health', label: '服务健康', icon: '💚' },
 *       { id: 'events', label: '事件日志', icon: '📜' },
 *     ],
 *     default: 'vram',
 *     onChange: (id) => renderTabContent(id),
 *   });
 *   container.appendChild(tab.nav);
 *   tab.setActive('vram');  // 手动切换
 */

import { el } from '../core/utils.js';

/**
 * 渲染 Tab 导航
 * @param {object} opts
 * @param {Array} opts.tabs - [{id, label, icon}]
 * @param {string} [opts.default] - 默认激活的 tab id
 * @param {Function} [opts.onChange] - 切换回调 (id) => void
 * @returns {{nav: HTMLElement, setActive: Function, getActive: Function}}
 */
export function render(opts = {}) {
  const { tabs = [], default: defaultTab = null, onChange = null } = opts;

  let activeId = defaultTab || (tabs[0] && tabs[0].id);

  const nav = el('<nav class="tab-nav"></nav>');
  const tabMap = new Map();

  tabs.forEach((tab) => {
    const btn = el(`<button class="tab-nav__item" data-tab="${tab.id}" type="button">
      ${tab.icon ? `<span class="tab-nav__icon">${tab.icon}</span>` : ''}
      <span class="tab-nav__label">${tab.label}</span>
    </button>`);
    btn.addEventListener('click', () => setActive(tab.id));
    nav.appendChild(btn);
    tabMap.set(tab.id, btn);
  });

  function setActive(id) {
    if (!tabMap.has(id)) return;
    activeId = id;
    tabMap.forEach((btn, tid) => {
      btn.classList.toggle('tab-nav__item--active', tid === id);
    });
    if (typeof onChange === 'function') {
      try { onChange(id); } catch (e) { console.error('[TabNav] onChange error', e); }
    }
  }

  function getActive() {
    return activeId;
  }

  // 初始化激活状态
  if (activeId) setActive(activeId);

  return { nav, setActive, getActive };
}

export default { render };
