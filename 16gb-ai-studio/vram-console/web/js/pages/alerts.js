/* ============================================================
 * Pages - 告警中心页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
  async alerts() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">告警中心
          <div class="page-header__actions"><button class="btn btn--secondary btn--sm" id="btn-alert-refresh">${Icons.refresh} 刷新</button></div>
        </div>
        <div class="page-header__subtitle">告警聚合、静默与历史管理</div>
      </div>
      <div id="alerts-body"><div class="loading-overlay"><div class="spinner"></div></div></div>
    `;
    Utils.$('#btn-alert-refresh').onclick = () => this._loadAlerts();
    this._loadAlerts();
  },

  async _loadAlerts() {
    const [activeRes, historyRes, silencedRes] = await Promise.all([
      API.getAlerts(), API.getAlertHistory({ limit: 50 }), API.getSilencedAlerts(),
    ]);
    if (Router.current !== '/alerts') return;  // 切页竞态守卫
    const active = activeRes.alerts || [];
    const history = historyRes.history || [];
    const silenced = silencedRes.silenced || [];

    const criticalCount = active.filter(a => a.level === 'critical').length;
    const warningCount = active.filter(a => a.level === 'warning').length;

    // 告警类型聚合统计
    const typeAggregation = {};
    let maxTypeCount = 0;
    let totalTriggers = 0;
    for (const a of active) {
      const type = a.alert_type || 'unknown';
      if (!typeAggregation[type]) {
        typeAggregation[type] = { count: 0, critical: 0, warning: 0, info: 0 };
      }
      const cnt = a.count || 1;
      typeAggregation[type].count += cnt;
      totalTriggers += cnt;
      if (a.level === 'critical') typeAggregation[type].critical += cnt;
      else if (a.level === 'warning') typeAggregation[type].warning += cnt;
      else typeAggregation[type].info += cnt;
      if (typeAggregation[type].count > maxTypeCount) maxTypeCount = typeAggregation[type].count;
    }

    // 降噪率计算：(总触发次数 - 活跃告警数) / 总触发次数 * 100
    const aggregatedCount = Math.max(0, totalTriggers - active.length);
    const noiseReductionRate = totalTriggers > 0 ? Math.round((aggregatedCount / totalTriggers) * 100) : 0;

    const body = Utils.$('#alerts-body');
    body.innerHTML = `
      <div class="grid mb-4">
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.bell}</span><span class="stat-card__label">活跃告警</span></div>
          <div class="stat-card__value">${active.length}</div>
          <div class="stat-card__footer">${criticalCount > 0 ? `critical ${criticalCount} · ` : ''}warning ${warningCount}</div>
        </div>
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.clock}</span><span class="stat-card__label">静默中</span></div>
          <div class="stat-card__value">${silenced.length}</div>
          <div class="stat-card__footer">${silenced.length > 0 ? `${silenced.length} 条规则生效中` : '无静默告警'}</div>
        </div>
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.list}</span><span class="stat-card__label">历史记录</span></div>
          <div class="stat-card__value">${history.length}</div>
          <div class="stat-card__footer">最近 50 条</div>
        </div>
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.shield}</span><span class="stat-card__label">降噪率</span></div>
          <div class="stat-card__value" style="color:${noiseReductionRate >= 50 ? 'var(--color-success)' : noiseReductionRate > 0 ? 'var(--color-warning)' : 'var(--color-text-secondary)'}">${noiseReductionRate}%</div>
          <div class="stat-card__footer">聚合 ${aggregatedCount} 次 · 静默 ${silenced.length} 条</div>
        </div>
      </div>

      <!-- 告警类型聚合分布 -->
      <div class="card mb-4">
        <div class="card__header"><div class="card__title">告警类型聚合</div>
          <div class="card__actions"><span class="badge badge--neutral">${Object.keys(typeAggregation).length} 种类型</span></div>
        </div>
        <div class="card__body">
          ${Object.keys(typeAggregation).length > 0 ? Object.entries(typeAggregation).map(([type, agg]) => `
            <div class="agg-row">
              <div class="agg-row__header">
                <span class="text-mono" style="font-size:12px">${Utils.escapeHtml(type)}</span>
                <span class="text-mono" style="font-size:12px;color:var(--color-text-secondary)">${agg.count} 次 · ${agg.critical > 0 ? `<span style="color:var(--color-danger)">critical ${agg.critical}</span>` : ''} ${agg.warning > 0 ? `<span style="color:var(--color-warning)">warning ${agg.warning}</span>` : ''} ${agg.info > 0 ? `<span style="color:var(--color-info)">info ${agg.info}</span>` : ''}</span>
              </div>
              <div class="agg-row__bar">
                <div class="agg-row__fill" style="width:${Math.min(100, (agg.count / maxTypeCount) * 100)}%;background:${agg.critical > 0 ? 'var(--color-danger)' : agg.warning > 0 ? 'var(--color-warning)' : 'var(--color-brand-500)'}"></div>
              </div>
            </div>
          `).join('') : '<div class="text-tertiary text-center" style="padding:20px">暂无告警数据</div>'}
        </div>
      </div>

      <div class="tabs">
        <div class="tab tab--active" data-tab="active">活跃告警 ${active.length > 0 ? `<span class="tab__badge">${active.length}</span>` : ''}</div>
        <div class="tab" data-tab="history">历史记录</div>
        <div class="tab" data-tab="silenced">静默管理</div>
      </div>
      <div id="tab-content"></div>
    `;

    Utils.$$('.tab').forEach(tab => {
      tab.onclick = () => {
        Utils.$$('.tab').forEach(t => t.classList.remove('tab--active'));
        tab.classList.add('tab--active');
        this._renderAlertTab(tab.dataset.tab, { active, history, silenced });
      };
    });
    this._renderAlertTab('active', { active, history, silenced });
  },

  _renderAlertTab(tab, data) {
    const el = Utils.$('#tab-content');
    if (tab === 'active') {
      el.innerHTML = data.active.length > 0 ? data.active.map(a => `
        <div class="alert-card alert-card--${a.level}">
          <div class="alert-card__header">
            <span class="badge badge--${a.level}">${a.level}</span>
            <span class="alert-card__type">${Utils.escapeHtml(a.alert_type)}</span>
            <span class="alert-card__duration">已持续 ${Utils.formatDuration(a.duration_seconds || 0)} · 触发 ${a.count || 1} 次</span>
          </div>
          <div class="alert-card__message">${Utils.escapeHtml(a.message || '')}</div>
          <div class="alert-card__meta">
            <span>首次: ${Utils.formatTime(a.first_triggered * 1000)}</span>
            <span>最近: ${Utils.formatTime(a.last_triggered * 1000)}</span>
          </div>
          <div class="alert-card__actions">
            <button class="btn btn--secondary btn--sm" onclick="Router.go('/diagnose')">查看根因</button>
            <button class="btn btn--ghost btn--sm" onclick="Pages._silenceAlert('${a.alert_type}')">静默 30分钟</button>
            <button class="btn btn--success btn--sm" onclick="Pages._resolveAlert('${a.alert_type}')">标记已解决</button>
          </div>
        </div>
      `).join('') : '<div class="empty-state"><div class="empty-state__icon">'+Icons.bell+'</div><div class="empty-state__title">暂无活跃告警</div><div class="empty-state__desc">系统运行正常</div></div>';
    } else if (tab === 'history') {
      el.innerHTML = `
        <div class="card">
          <div class="card__body--no-padding">
            <table class="table">
              <thead><tr><th>时间</th><th>动作</th><th>类型</th><th>级别</th><th>消息</th><th>计数</th></tr></thead>
              <tbody>
                ${data.history.map(h => `
                  <tr>
                    <td class="text-mono" style="font-size:11px">${Utils.formatTime(h.timestamp)}</td>
                    <td><span class="badge badge--${h.action === 'resolved' ? 'success' : h.action === 'escalated' ? 'danger' : h.action === 'silenced' ? 'warning' : 'info'}">${h.action}</span></td>
                    <td class="text-mono" style="font-size:11px">${Utils.escapeHtml(h.alert_type)}</td>
                    <td><span class="badge badge--${h.level}">${h.level}</span></td>
                    <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(h.message || '')}</td>
                    <td class="table__num text-mono">${h.count || 1}</td>
                  </tr>
                `).join('') || '<tr><td colspan="6" class="text-center text-tertiary">暂无历史记录</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      `;
    } else {
      el.innerHTML = `
        <div class="card mb-4">
          <div class="card__header"><div class="card__title">当前静默中的告警</div></div>
          <div class="card__body">
            ${data.silenced.length > 0 ? data.silenced.map(s => `
              <div class="flex items-center gap-3" style="padding:8px 0;border-bottom:1px solid var(--color-border-light)">
                <span class="text-mono">${Utils.escapeHtml(s.alert_type)}</span>
                <span class="text-secondary text-mono" style="font-size:12px">剩余静默 ${Utils.formatDuration(s.remaining_seconds)}</span>
                <button class="btn btn--ghost btn--sm" style="margin-left:auto" onclick="Pages._unsilenceAlert('${s.alert_type}')">取消静默</button>
              </div>
            `).join('') : '<div class="text-tertiary">暂无静默告警</div>'}
          </div>
        </div>
      `;
    }
  },

  async _silenceAlert(type) {
    const res = await API.silenceAlert({ alert_type: type, duration_minutes: 30 });
    if (res.ok) { Toast.success(`已静默 ${type}`); this._loadAlerts(); }
    else Toast.error(res.error?.message || '操作失败');
  },
  async _resolveAlert(type) {
    const res = await API.resolveAlert({ alert_type: type });
    if (res.ok) { Toast.success(`已解决 ${type}`); this._loadAlerts(); }
    else Toast.error(res.error?.message || '操作失败');
  },
  async _unsilenceAlert(type) {
    const res = await API.silenceAlert({ alert_type: type, duration_minutes: 0 });
    if (res.ok) { Toast.success(`已取消静默 ${type}`); this._loadAlerts(); }
    else Toast.error(res.error?.message || '操作失败');
  }
});
