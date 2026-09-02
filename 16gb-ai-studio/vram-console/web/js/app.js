/* ============================================================
 * 16GAS 前端应用入口
 * 拆分结构：
 *   core/       - 核心模块（utils, eventbus, state, api, router）
 *   components/ - 通用组件（toast, modal, icons）
 *   pages/      - 页面渲染（pages, topology）
 *   app.js      - 应用入口（initApp, updateHeader, startGlobalPolling, logout）
 * ============================================================ */

async function initApp() {
  // 初始化组件
  Toast.init();
  Modal.init();

  // 尝试从 localStorage 读取 token
  const token = localStorage.getItem('gmae_api_token');
  if (token) State.set('apiToken', token);

  // 检查认证状态
  const authRes = await API.authStatus();
  const isAuthed = authRes.ok && authRes.authenticated;

  // 构建应用骨架
  const app = Utils.$('#app');
  app.innerHTML = `
    <div class="app">
      <header class="header">
        <div class="header__brand" onclick="Router.go('/dashboard')">
          <div class="header__logo">G</div>
          <div class="header__title">16G-AI-Studio</div>
        </div>
        <div class="header__page-title" id="header-page-title">总览</div>
        <div class="header__spacer"></div>
        <div class="header__right">
          <div class="data-freshness" id="data-freshness" title="数据新鲜度">
            <span class="data-freshness__dot" id="data-freshness-dot"></span>
            <span class="data-freshness__text" id="data-freshness-text">—</span>
          </div>
          <div class="header__vram-mini" onclick="Router.go('/vram')" id="header-vram-wrap" title="显存使用情况">
            <div class="header__vram-bar"><div class="header__vram-fill" id="header-vram-fill" style="width:0%"></div></div>
            <span class="header__vram-text" id="header-vram-text">—</span>
          </div>
          <div class="header__alert-badge" onclick="Router.go('/alerts')" title="告警中心">
            ${Icons.bell}
            <span class="header__alert-count hidden" id="header-alert-count">0</span>
          </div>
          <div class="header__user" title="用户">
            <div class="header__avatar">D</div>
            <span class="header__username">Danny</span>
          </div>
          <button class="btn btn--ghost btn--sm" onclick="logout()" title="退出">${Icons.logout}</button>
        </div>
      </header>
      <div class="app__body">
        <aside class="sidebar">
          <nav class="sidebar__nav">
            <div class="sidebar__group">
              <div class="sidebar__group-label">核心</div>
              <div class="sidebar__item sidebar__item--active" data-route="/dashboard" onclick="Router.go('/dashboard')"><span class="sidebar__icon">${Icons.dashboard}</span><span>总览</span></div>
              <div class="sidebar__item" data-route="/diagnose" onclick="Router.go('/diagnose')"><span class="sidebar__icon">${Icons.diagnose}</span><span>诊断中心</span></div>
              <div class="sidebar__item" data-route="/topology" onclick="Router.go('/topology')"><span class="sidebar__icon">${Icons.layers}</span><span>系统拓扑</span></div>
              <div class="sidebar__item" data-route="/alerts" onclick="Router.go('/alerts')"><span class="sidebar__icon">${Icons.alerts}</span><span>告警中心</span><span class="sidebar__badge hidden" id="sidebar-alert-badge">0</span></div>
            </div>
            <div class="sidebar__divider"></div>
            <div class="sidebar__group">
              <div class="sidebar__group-label">管理</div>
              <div class="sidebar__item" data-route="/models" onclick="Router.go('/models')"><span class="sidebar__icon">${Icons.models}</span><span>模型登记台</span></div>
              <div class="sidebar__item" data-route="/vram" onclick="Router.go('/vram')"><span class="sidebar__icon">${Icons.vram}</span><span>显存账本</span></div>
              <div class="sidebar__item" data-route="/scenes" onclick="Router.go('/scenes')"><span class="sidebar__icon">${Icons.scenes}</span><span>场景切换</span></div>
              <div class="sidebar__item" data-route="/queue" onclick="Router.go('/queue')"><span class="sidebar__icon">${Icons.queue}</span><span>任务队列</span></div>
              <div class="sidebar__item" data-route="/guard" onclick="Router.go('/guard')"><span class="sidebar__icon">${Icons.guard}</span><span>门卫</span></div>
            </div>
            <div class="sidebar__divider"></div>
            <div class="sidebar__group">
              <div class="sidebar__group-label">系统</div>
              <div class="sidebar__item" data-route="/audit" onclick="Router.go('/audit')"><span class="sidebar__icon">${Icons.list}</span><span>操作审计</span></div>
              <div class="sidebar__item" data-route="/settings" onclick="Router.go('/settings')"><span class="sidebar__icon">${Icons.settings}</span><span>设置</span></div>
            </div>
          </nav>
          <div class="sidebar__footer"><div class="sidebar__version">v1.0.0</div></div>
        </aside>
        <main class="content"><div class="content__inner" id="app-content"></div></main>
      </div>
    </div>
  `;

  // 注册路由
  Router.register('/dashboard', () => Pages.dashboard());
  Router.register('/diagnose', () => Pages.diagnose());
  Router.register('/alerts', () => Pages.alerts());
  Router.register('/models', () => Pages.models());
  Router.register('/vram', () => Pages.vram());
  Router.register('/scenes', () => Pages.scenes());
  Router.register('/queue', () => Pages.queue());
  Router.register('/guard', () => Pages.guard());
  Router.register('/audit', () => Pages.audit());
  Router.register('/settings', () => Pages.settings());
  Router.register('/topology', () => TopologyPage.render());

  // 启动路由
  Router.start();

  // 启动全局数据轮询
  startGlobalPolling();
}

// 全局更新顶部导航栏（显存+告警），供一键释放等操作后立即调用
async function updateHeader() {
  try {
    const res = await API.getStatus();
    const status = res;
    const gpu = status.gpu || {};
    const total = gpu.total_mb || 16384;
    const used = gpu.used_mb || 0;
    const pct = Math.round((used / total) * 100);
    const fill = Utils.$('#header-vram-fill');
    const text = Utils.$('#header-vram-text');
    const freeMb = gpu.free_mb || total - used;
    if (fill) { fill.style.width = pct + '%'; fill.style.background = pct > 85 ? 'var(--color-danger)' : pct > 70 ? 'var(--color-warning)' : 'var(--color-brand-500)'; }
    if (text) text.textContent = Utils.formatMB(used) + '/' + Utils.formatMB(total) + ' · ' + pct + '%';
    const wrap = Utils.$('#header-vram-wrap');
    if (wrap) wrap.title = '已用 ' + Utils.formatMB(used) + ' / 总量 ' + Utils.formatMB(total) + ' / 空闲 ' + Utils.formatMB(freeMb) + ' / 使用率 ' + pct + '%';
    // 更新数据新鲜度指示器
    const meta = status._meta || {};
    const freshnessEl = Utils.$('#data-freshness');
    const freshnessDot = Utils.$('#data-freshness-dot');
    const freshnessText = Utils.$('#data-freshness-text');
    if (freshnessEl && freshnessDot && freshnessText) {
      if (meta.cached) {
        const cacheAge = Math.round((Date.now() / 1000 - (meta.cached_at || 0)));
        const isStale = meta.stale || cacheAge > 15;
        if (isStale) {
          freshnessDot.style.background = 'var(--color-danger)';
          freshnessText.textContent = '过期 ' + cacheAge + 's';
          freshnessText.style.color = 'var(--color-danger)';
          freshnessEl.title = '数据已过期 ' + cacheAge + ' 秒，请刷新';
        } else {
          freshnessDot.style.background = 'var(--color-warning)';
          freshnessText.textContent = '缓存 ' + cacheAge + 's';
          freshnessText.style.color = 'var(--color-warning)';
          freshnessEl.title = '数据来自缓存，缓存时间 ' + cacheAge + ' 秒';
        }
      } else {
        freshnessDot.style.background = 'var(--color-success)';
        freshnessText.textContent = '实时';
        freshnessText.style.color = 'var(--color-success)';
        freshnessEl.title = '数据实时获取';
      }
    }
    // 更新全局状态，让所有页面共享同一份数据（统一数据源）
    State.set('status', status);
    State.recordVram(used, gpu.free_mb || total - used, total);
    // 如果当前在显存账本页，自动刷新（避免数据滞后，_loadVram 优先使用全局状态不会发请求）
    if (location.hash === '#/vram' && typeof Pages._loadVram === 'function') {
      Pages._loadVram();
    }
  } catch (e) { /* 静默失败 */ }
  try {
    const alertRes = await API.getAlerts();
    const count = alertRes.count || alertRes.alerts?.length || 0;
    const badge = Utils.$('#header-alert-count');
    const sideBadge = Utils.$('#sidebar-alert-badge');
    if (badge) { badge.textContent = count; badge.classList.toggle('hidden', count === 0); }
    if (sideBadge) { sideBadge.textContent = count; sideBadge.classList.toggle('hidden', count === 0); }
  } catch (e) { /* 静默失败 */ }
}

async function startGlobalPolling() {
  updateHeader();
  setInterval(updateHeader, 10000);
}

async function logout() {
  Modal.confirm({
    title: '退出登录', message: '确认退出登录？', confirmText: '退出',
    onConfirm: async () => {
      await API.authLogout();
      localStorage.removeItem('gmae_api_token');
      Toast.info('已退出登录');
      setTimeout(() => location.reload(), 1000);
    },
  });
}

// 启动应用
document.addEventListener('DOMContentLoaded', initApp);
