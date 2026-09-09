/* ============================================================
 * Pages - 门卫页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
  async guard() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">门卫
          <div class="page-header__actions"><button class="btn btn--secondary btn--sm" id="btn-guard-refresh">${Icons.refresh} 刷新</button></div>
        </div>
        <div class="page-header__subtitle">GPU 进程治理与驱逐保护</div>
      </div>
      <div id="guard-body"><div class="loading-overlay"><div class="spinner"></div></div></div>
    `;
    Utils.$('#btn-guard-refresh').onclick = () => this._loadGuard();
    this._loadGuard();
  },

  _allGuardProcesses: [],

  async _loadGuard() {
    const res = await API.getStatus();
    const status = res;
    if (Router.current !== '/guard') return;  // 切页竞态守卫
    const gp = status.gpu_processes || {};
    const guard = status.guard || {};
    const processes = gp.processes || [];
    this._allGuardProcesses = processes;
    const knownCount = processes.filter(p => p.known).length;
    const unknownCount = gp.unknown_pids?.length || 0;
    const whitelist = this._getWhitelist();
    const body = Utils.$('#guard-body');
    body.innerHTML = `
      <div class="alert-banner" style="border-left-color:var(--color-brand-600);background:rgba(13,148,136,0.08)">
        <div class="alert-banner__icon" style="color:var(--color-brand-500)">${Icons.shield}</div>
        <div class="alert-banner__content">
          <div class="alert-banner__title">门卫状态: ${Utils.escapeHtml(guard.level || 'ok')}</div>
          <div class="alert-banner__meta">受管进程 ${knownCount} · 桌面进程 ${gp.desktop_count || 0} · 未登记 ${unknownCount} · 已知显存 ${Utils.formatMB(gp.known_total_mb || 0)} · 白名单 ${whitelist.length} 个</div>
        </div>
      </div>
      <div class="card mt-4">
        <div class="card__header"><div class="card__title">进程列表</div>
          <div class="card__actions">
            <select class="form-select" id="guard-filter" style="width:120px;height:28px;font-size:11px">
              <option value="">全部</option>
              <option value="known">受管</option>
              <option value="desktop">桌面</option>
              <option value="unknown">未登记</option>
              <option value="whitelist">白名单</option>
            </select>
          </div>
        </div>
        <div class="card__body--no-padding" id="guard-process-list">
          ${this._renderGuardProcesses(processes, whitelist)}
        </div>
      </div>
      <div class="card mt-4">
        <div class="card__header">
          <div class="card__title">白名单管理</div>
          <div class="card__actions"><button class="btn btn--primary btn--sm" id="btn-add-whitelist">+ 添加</button></div>
        </div>
        <div class="card__body" id="guard-whitelist">
          ${this._renderWhitelist(whitelist)}
        </div>
      </div>
    `;
    // 绑定筛选
    const filter = Utils.$('#guard-filter');
    if (filter) {
      filter.onchange = () => {
        const val = filter.value;
        const wl = this._getWhitelist();
        let filtered = this._allGuardProcesses;
        if (val === 'known') filtered = filtered.filter(p => p.known);
        if (val === 'desktop') filtered = filtered.filter(p => p.app === 'desktop' || p.is_desktop);
        if (val === 'unknown') filtered = filtered.filter(p => !p.known);
        if (val === 'whitelist') filtered = filtered.filter(p => wl.includes(p.name || ''));
        const list = Utils.$('#guard-process-list');
        if (list) list.innerHTML = this._renderGuardProcesses(filtered, wl);
      };
    }
    // 绑定添加白名单
    const addBtn = Utils.$('#btn-add-whitelist');
    if (addBtn) addBtn.onclick = () => this._addWhitelistItem();
  },

  _renderGuardProcesses(processes, whitelist) {
    if (processes.length === 0) {
      return '<div class="empty-state"><div class="empty-state__icon">'+Icons.shield+'</div><div class="empty-state__title">暂无进程数据</div></div>';
    }
    return `
      <table class="table">
        <thead><tr><th>进程名</th><th>PID</th><th>类型</th><th>显存</th><th>白名单</th><th>操作</th></tr></thead>
        <tbody>
          ${processes.map(p => {
            const pName = p.name || '';
            const isWL = whitelist.includes(pName);
            const typeLabel = p.known ? (p.app || '受管') : '未登记';
            const typeClass = p.known ? 'success' : 'warning';
            return `
              <tr>
                <td class="text-mono">${Utils.escapeHtml(pName)}</td>
                <td class="text-mono">${p.pid || '—'}</td>
                <td><span class="badge badge--${typeClass}">${Utils.escapeHtml(typeLabel)}</span></td>
                <td class="table__num text-mono">${Utils.formatMB(p.used_mb || 0)}</td>
                <td>${isWL ? '<span class="badge badge--info">白名单</span>' : '—'}</td>
                <td class="table__actions">
                  ${isWL
                    ? `<button class="btn btn--ghost btn--sm" onclick="Pages._removeWhitelistItem('${Utils.escapeHtml(pName)}')">移出白名单</button>`
                    : `<button class="btn btn--ghost btn--sm" onclick="Pages._addWhitelistItem('${Utils.escapeHtml(pName)}')">加入白名单</button>`}
                  ${!p.known && !isWL ? `<button class="btn btn--danger btn--sm" onclick="Pages._kickProcess(${p.pid})">驱逐</button>` : ''}
                </td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    `;
  },

  /** 白名单存储（localStorage） */
  _getWhitelist() {
    try { return JSON.parse(localStorage.getItem('gmae_guard_whitelist') || '[]'); }
    catch { return []; }
  },
  _setWhitelist(list) {
    localStorage.setItem('gmae_guard_whitelist', JSON.stringify(list));
  },
  _renderWhitelist(whitelist) {
    if (whitelist.length === 0) {
      return '<div class="text-tertiary" style="font-size:12px">白名单为空。白名单中的进程不会被自动驱逐。</div>';
    }
    return `<div class="flex flex-wrap gap-2">${whitelist.map(name => `
      <span class="badge badge--info" style="padding:6px 10px">
        ${Utils.escapeHtml(name)}
        <button style="margin-left:6px;background:none;border:none;color:var(--color-text-secondary);cursor:pointer;font-size:14px" onclick="Pages._removeWhitelistItem('${Utils.escapeHtml(name)}')">×</button>
      </span>
    `).join('')}</div>`;
  },
  _addWhitelistItem(defaultName) {
    const name = defaultName || prompt('输入进程名（如 python.exe）：');
    if (!name || !name.trim()) return;
    const wl = this._getWhitelist();
    if (!wl.includes(name.trim())) {
      wl.push(name.trim());
      this._setWhitelist(wl);
      Toast.success(`已添加到白名单：${name}`);
      this._loadGuard();
    } else {
      Toast.info('已在白名单中');
    }
  },
  _removeWhitelistItem(name) {
    const wl = this._getWhitelist().filter(n => n !== name);
    this._setWhitelist(wl);
    Toast.info(`已移出白名单：${name}`);
    this._loadGuard();
  },

  async _kickProcess(pid) {
    Modal.confirm({ title: '驱逐进程', message: `确认驱逐进程 PID ${pid}？`, confirmText: '驱逐', danger: true, onConfirm: async () => {
      const res = await API.guardKick({ pid });
      if (res.ok) { Toast.success('进程已驱逐'); this._loadGuard(); }
      else Toast.error(res.error?.message || '驱逐失败');
    }});
  }
});
