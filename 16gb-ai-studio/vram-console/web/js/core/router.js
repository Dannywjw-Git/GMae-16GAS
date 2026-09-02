/* ============================================================
 * Router - core 模块
 * 从 app.js 拆分，保持原逻辑不变
 * ============================================================ */

const Router = {
  routes: {},
  current: '',
  register(path, handler) { this.routes[path] = handler; },
  go(path) { window.location.hash = path; },
  start() {
    window.addEventListener('hashchange', () => this._handle());
    this._handle();
  },
  _handle() {
    const hash = window.location.hash.slice(1) || '/dashboard';
    this.current = hash;
    const handler = this.routes[hash] || this.routes['/dashboard'];
    if (handler) {
      Utils.$('#app-content').innerHTML = '';
      handler();
      this._updateNav(hash);
      this._updateHeader(hash);
    }
  },
  _updateNav(path) {
    Utils.$$('.sidebar__item').forEach(item => {
      item.classList.toggle('sidebar__item--active', item.dataset.route === path);
    });
  },
  _updateHeader(path) {
    const titles = {
      '/dashboard': '总览',
      '/diagnose': '诊断中心',
      '/alerts': '告警中心',
      '/models': '模型登记台',
      '/vram': '显存账本',
      '/scenes': '场景切换',
      '/queue': '任务队列',
      '/guard': '门卫',
      '/audit': '操作审计',
      '/settings': '设置',
    };
    const el = Utils.$('#header-page-title');
    if (el) el.textContent = titles[path] || '';
  },
};
