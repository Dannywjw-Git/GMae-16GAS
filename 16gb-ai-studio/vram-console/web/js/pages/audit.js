/* ============================================================
 * Pages - 操作审计页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
  async audit() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">操作审计
          <div class="page-header__actions">
            <select class="form-select form-select--sm" id="audit-category-filter">
              <option value="">全部类型</option>
              <option value="user_action">用户操作</option>
              <option value="vram">显存</option>
              <option value="container">容器</option>
              <option value="model">模型</option>
              <option value="task">任务</option>
              <option value="system">系统</option>
              <option value="guard">门卫</option>
            </select>
            <button class="btn btn--secondary btn--sm" id="btn-audit-refresh">${Icons.refresh} 刷新</button>
          </div>
        </div>
        <div class="page-header__subtitle">用户操作与系统事件审计日志</div>
      </div>
      <div id="audit-body"><div class="loading-overlay"><div class="spinner"></div></div></div>
    `;
    Utils.$('#btn-audit-refresh').onclick = () => this._loadAudit();
    Utils.$('#audit-category-filter').onchange = () => this._loadAudit();
    this._loadAudit();
  },

  async _loadAudit() {
    const category = Utils.$('#audit-category-filter')?.value || '';
    const res = await API.getEvents({ limit: 100, category: category || undefined });
    if (Router.current !== '/audit') return;  // 切页竞态守卫
    const events = res.events || [];
    const userActionCount = events.filter(e => e.category === 'user_action').length;
    const vramCount = events.filter(e => e.category === 'vram').length;
    const errorCount = events.filter(e => e.level === 'error' || e.level === 'critical').length;
    const body = Utils.$('#audit-body');
    body.innerHTML = `
      <div class="grid mb-4">
        <div class="col-3 stat-card"><div class="stat-card__header"><span class="stat-card__icon">${Icons.list}</span><span class="stat-card__label">总事件</span></div><div class="stat-card__value">${events.length}</div><div class="stat-card__footer">最近 100 条</div></div>
        <div class="col-3 stat-card"><div class="stat-card__header"><span class="stat-card__icon">${Icons.user}</span><span class="stat-card__label">用户操作</span></div><div class="stat-card__value">${userActionCount}</div><div class="stat-card__footer">手动触发的操作</div></div>
        <div class="col-3 stat-card"><div class="stat-card__header"><span class="stat-card__icon">${Icons.vram}</span><span class="stat-card__label">显存事件</span></div><div class="stat-card__value">${vramCount}</div><div class="stat-card__footer">显存状态变化</div></div>
        <div class="col-3 stat-card"><div class="stat-card__header"><span class="stat-card__icon">${Icons.alert}</span><span class="stat-card__label">错误/严重</span></div><div class="stat-card__value" style="color:${errorCount > 0 ? 'var(--color-danger)' : 'var(--color-text-primary)'}">${errorCount}</div><div class="stat-card__footer">需要关注的事件</div></div>
      </div>
      <div class="card"><div class="card__body--no-padding"><table class="table">
        <thead><tr><th style="width:160px">时间</th><th style="width:90px">类型</th><th style="width:70px">级别</th><th style="width:100px">来源</th><th>事件</th><th style="width:200px">详情</th></tr></thead>
        <tbody>
          ${events.map(e => `<tr>
            <td class="text-mono" style="font-size:11px">${Utils.formatTime(new Date(e.timestamp).getTime())}</td>
            <td><span class="badge badge--${e.category === 'user_action' ? 'info' : e.category === 'vram' ? 'warning' : 'neutral'}">${e.category}</span></td>
            <td><span class="badge badge--${e.level}">${e.level}</span></td>
            <td class="text-mono" style="font-size:11px">${Utils.escapeHtml(e.source || '')}</td>
            <td class="text-mono" style="font-size:12px">${Utils.escapeHtml(e.event || '')}</td>
            <td style="font-size:12px;color:var(--color-text-secondary);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${Utils.escapeHtml(e.message || JSON.stringify(e.metadata || {}))}">${Utils.escapeHtml(e.message || '')}</td>
          </tr>`).join('') || '<tr><td colspan="6" class="text-center text-tertiary">暂无事件记录</td></tr>'}
        </tbody>
      </table></div></div>
    `;
  }
});
