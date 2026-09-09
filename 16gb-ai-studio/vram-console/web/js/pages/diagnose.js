/* ============================================================
 * Pages - 诊断中心页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
  async diagnose() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">诊断中心
          <div class="page-header__actions"><button class="btn btn--secondary btn--sm" id="btn-diag-refresh">${Icons.refresh} 刷新</button></div>
        </div>
        <div class="page-header__subtitle">故障根因分析与事件时间线回溯</div>
      </div>
      <div class="card mb-4">
        <div class="card__body">
          <div class="flex items-center gap-3 flex-wrap">
            <div class="flex items-center gap-2">
              <span class="form-label" style="margin:0">告警类型</span>
              <select class="form-select" id="diag-alert-type" style="width:180px">
                <option value="">自动检测</option>
                <option value="vram_critical">显存危险</option>
                <option value="vram_warning">显存警告</option>
                <option value="container_crash">容器崩溃</option>
                <option value="service_down">服务不可达</option>
              </select>
            </div>
            <div class="flex items-center gap-2">
              <span class="form-label" style="margin:0">时间窗</span>
              <select class="form-select" id="diag-window" style="width:120px">
                <option value="300">5分钟</option>
                <option value="60">1分钟</option>
                <option value="900">15分钟</option>
                <option value="1800">30分钟</option>
                <option value="3600">1小时</option>
              </select>
            </div>
            <button class="btn btn--primary" id="btn-run-diag">🔍 执行诊断</button>
          </div>
        </div>
      </div>
      <div class="grid">
        <div class="col-5" id="diag-results"><div class="loading-overlay"><div class="spinner"></div></div></div>
        <div class="col-7" id="diag-timeline"><div class="loading-overlay"><div class="spinner"></div></div></div>
      </div>
      <div class="card mt-4" id="diag-scenarios"></div>
    `;
    Utils.$('#btn-diag-refresh').onclick = () => this._loadDiagnose();
    Utils.$('#btn-run-diag').onclick = () => this._runDiagnose();
    this._loadDiagnose();
  },

  /** 缓存所有事件，供筛选使用 */
  _allTimelineEvents: [],
  /** 缓存诊断结果，供关联事件查看使用 */
  _diagnoseCandidates: [],

  async _loadDiagnose() {
    const [eventsRes, rulesRes] = await Promise.all([API.getEvents({ limit: 50 }), API.getDiagnoseRules()]);
    if (Router.current !== '/diagnose') return;  // 切页竞态守卫
    const events = eventsRes.events || [];
    const rules = rulesRes.rules || [];
    this._allTimelineEvents = events;
    this._renderTimeline(events);
    this._renderScenarios(rules);
    this._runDiagnose();
  },

  async _runDiagnose() {
    const alertType = Utils.$('#diag-alert-type')?.value || '';
    const windowSec = parseInt(Utils.$('#diag-window')?.value) || 300;
    const resultsEl = Utils.$('#diag-results');
    if (!resultsEl) return;
    resultsEl.innerHTML = '<div class="loading-overlay"><div class="spinner"></div></div>';
    const res = await API.diagnose({ alert_type: alertType || undefined, window_seconds: windowSec });
    const candidates = res.matched_rules || res.candidates || res.root_causes || [];
    this._diagnoseCandidates = candidates;
    const matchedScenarios = res.matched_failure_scenarios || [];
    this._renderScenarios(matchedScenarios.length > 0 ? matchedScenarios : this._diagnoseRules);
    resultsEl.innerHTML = `
      <div class="card">
        <div class="card__header">
          <div class="card__title">根因候选 Top${candidates.length || 3}</div>
          <span class="badge badge--neutral">${res.diagnosed_at ? Utils.formatTime(res.diagnosed_at) : '已诊断'}</span>
        </div>
        <div class="card__body">
          ${candidates.length > 0 ? candidates.map((c, i) => `
            <div class="root-cause-card root-cause-card--rank-${i+1}">
              <div class="root-cause-card__header">
                <div class="root-cause-card__rank">${i+1}</div>
                <div class="root-cause-card__title">${Utils.escapeHtml(c.title || c.rule_id || '未知')}</div>
                <div class="root-cause-card__confidence">
                  <div class="root-cause-card__confidence-bar"><div class="root-cause-card__confidence-fill" style="width:${c.confidence || 0}%"></div></div>
                  <span class="root-cause-card__confidence-text">${c.confidence || 0}%</span>
                </div>
              </div>
              <div class="root-cause-card__desc">${Utils.escapeHtml(c.description || c.reason || '')}</div>
              ${c.suggestions ? `
                <div class="root-cause-card__suggestions">
                  <div class="root-cause-card__suggestions-title">处置建议</div>
                  <ol class="root-cause-card__suggestions-list">
                    ${(Array.isArray(c.suggestions) ? c.suggestions : [c.suggestions]).map(s => `<li>${Utils.escapeHtml(s)}</li>`).join('')}
                  </ol>
                </div>
              ` : ''}
              <div class="root-cause-card__actions">
                <button class="btn btn--ghost btn--sm" onclick="Pages._showRelatedEvents(${i})">查看关联事件(${c.related_events?.length || 0})</button>
              </div>
            </div>
          `).join('') : '<div class="empty-state"><div class="empty-state__icon">'+Icons.activity+'</div><div class="empty-state__title">未匹配到根因规则</div><div class="empty-state__desc">系统当前状态正常，或需要更多事件数据</div></div>'}
          <div class="text-tertiary" style="font-size:11px;margin-top:12px">诊断规则: ${res.total_rules || candidates.length || 0} 条已加载</div>
        </div>
      </div>
    `;
  },

  /** 显示关联事件弹窗 */
  _showRelatedEvents(index) {
    const candidate = this._diagnoseCandidates[index];
    if (!candidate) { Toast.error('无诊断结果'); return; }
    const related = candidate.related_events || [];
    const events = related.length > 0
      ? related.map(e => `
        <div class="timeline__item" style="margin-bottom:8px">
          <div class="timeline__time">${Utils.formatTime(e.timestamp || e.time)}</div>
          <div class="timeline__header">
            <span class="badge badge--neutral" style="font-size:10px">${Utils.escapeHtml(e.category || '')}</span>
            <span class="timeline__event">${Utils.escapeHtml(e.event || e.type || '')}</span>
          </div>
          <div class="timeline__message">${Utils.escapeHtml(e.message || e.detail || '')}</div>
        </div>
      `).join('')
      : '<div class="text-tertiary">该候选无关联事件记录</div>';
    Modal.open({
      title: `关联事件 - ${Utils.escapeHtml(candidate.title || candidate.rule_id || '未知')}`,
      size: 'lg',
      content: `<div style="max-height:400px;overflow-y:auto">${events}</div>`,
      footer: `<button class="btn btn--secondary" data-action="close">关闭</button>`,
    });
    Modal.modal.querySelector('[data-action="close"]').onclick = () => Modal.close();
  },

  _renderTimeline(events) {
    const el = Utils.$('#diag-timeline');
    if (!el) return;
    el.innerHTML = `
      <div class="card">
        <div class="card__header">
          <div class="card__title">事件时间线</div>
          <div class="card__actions">
            <select class="form-select" id="tl-filter" style="width:120px;height:28px;font-size:11px">
              <option value="">全部类别</option>
              <option value="vram">显存</option>
              <option value="container">容器</option>
              <option value="model">模型</option>
              <option value="task">任务</option>
              <option value="user_action">用户操作</option>
              <option value="system">系统</option>
              <option value="guard">门卫</option>
            </select>
          </div>
        </div>
        <div class="card__body" style="max-height:500px;overflow-y:auto" id="tl-list">
          ${this._renderTimelineItems(events)}
        </div>
      </div>
    `;
    // 绑定筛选
    const filter = Utils.$('#tl-filter');
    if (filter) {
      filter.onchange = () => {
        const cat = filter.value;
        const filtered = cat ? this._allTimelineEvents.filter(e => e.category === cat) : this._allTimelineEvents;
        const list = Utils.$('#tl-list');
        if (list) list.innerHTML = this._renderTimelineItems(filtered);
      };
    }
  },

  _renderTimelineItems(events) {
    return events.length > 0 ? `
      <div class="timeline">
        ${events.map(e => `
          <div class="timeline__item">
            <div class="timeline__dot timeline__dot--${Utils.escapeHtml(e.category || 'system')}"></div>
            <div class="timeline__time">${Utils.formatTime(e.timestamp)}</div>
            <div class="timeline__header">
              <span class="badge badge--neutral" style="font-size:10px">${Utils.escapeHtml(e.category || '')}</span>
              <span class="timeline__event">${Utils.escapeHtml(e.event || '')}</span>
            </div>
            <div class="timeline__message">${Utils.escapeHtml(e.message || '')}</div>
          </div>
        `).join('')}
      </div>
    ` : '<div class="empty-state"><div class="empty-state__icon">'+Icons.activity+'</div><div class="empty-state__title">暂无事件</div></div>';
  },

  _renderScenarios(scenarios) {
    const el = Utils.$('#diag-scenarios');
    if (!el) return;
    // 缓存规则列表
    if (scenarios && scenarios.length > 0 && scenarios[0].rule_id) {
      this._diagnoseRules = scenarios;
    }
    const list = scenarios && scenarios.length > 0 ? scenarios : (this._diagnoseRules || []);
    if (list.length === 0) {
      el.innerHTML = '<div class="card__body"><div class="text-tertiary">加载诊断规则中...</div></div>';
      return;
    }
    el.innerHTML = `
      <div class="card__header"><div class="card__title">故障场景库（${list.length} 条规则）</div></div>
      <div class="card__body">
        <div class="grid">
          ${list.map(s => {
            const level = s.severity || s.level || 'info';
            const levelClass = level === 'critical' || level === 'danger' ? 'danger' : level === 'warning' ? 'warning' : 'info';
            return `
              <div class="col-6">
                <div class="scenario-card scenario-card--${levelClass}">
                  <div class="scenario-card__header">
                    <span class="badge badge--${levelClass}">${Utils.escapeHtml(s.rule_id || s.id || '')}</span>
                    <span class="scenario-card__name">${Utils.escapeHtml(s.name || s.title || '')}</span>
                  </div>
                  <div class="scenario-card__trigger">${Utils.escapeHtml(s.description || s.trigger || s.desc || '')}</div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }
});
