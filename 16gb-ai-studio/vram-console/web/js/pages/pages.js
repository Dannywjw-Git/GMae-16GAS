/* ============================================================
 * Pages - 页面渲染模块
 * 从 app.js 拆分，包含所有页面的渲染逻辑
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

const Pages = {
  // ===== Dashboard 总览页 =====
  async dashboard() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">
          总览
          <div class="page-header__actions">
            <button class="btn btn--secondary btn--sm" id="btn-refresh">${Icons.refresh} 刷新</button>
            <button class="btn btn--danger btn--sm" id="btn-free">${Icons.zap} 一键释放</button>
          </div>
        </div>
        <div class="page-header__subtitle">GPU 显存与服务全局状态监控</div>
      </div>
      <div id="dashboard-body">
        <div class="loading-overlay"><div class="spinner" style="width:32px;height:32px;border-width:3px"></div></div>
      </div>
    `;
    Utils.$('#btn-refresh').onclick = () => this._loadDashboard();
    Utils.$('#btn-free').onclick = () => this._doFreeVram();
    this._loadDashboard();
  },

  async _loadDashboard() {
    const body = Utils.$('#dashboard-body');
    // 优先使用全局状态（统一数据源）
    let status = State.get('status');
    const [alertsRes, eventsRes] = await Promise.all([
      API.getAlerts(), API.getEvents({ limit: 10 }),
    ]);
    if (!status) {
      const statusRes = await API.getStatus();
      status = statusRes;
    }
    State.set('status', status);
    const alerts = alertsRes.alerts || [];
    const events = eventsRes.events || [];
    State.set('status', status);
        const _hGpu = status.gpu || {};
        State.recordVram(_hGpu.used_mb || 0, _hGpu.free_mb || 0, _hGpu.total_mb || 16384);

    const gpu = status.gpu || {};
    const vramTotal = gpu.total_mb || 16384;
    const vramUsed = gpu.used_mb || 0;
    const vramFree = gpu.free_mb || vramTotal - vramUsed;
    const vramPct = Math.round((vramUsed / vramTotal) * 100);
    // 模型数量：优先用 ollama.models.length，其次用 vram_ledger.ollama_model_count
    const loadedModels = status.ollama?.models || [];
    const loadedModelCount = loadedModels.length || status.vram_ledger?.ollama_model_count || 0;
    const loadedModelNames = loadedModels.slice(0, 2).map(m => m.name || m.model || '').filter(Boolean).join(', ') || '无';
    const baseNoise = status.gpu_processes?.system_baseline_mb || status.vram_ledger?.noise_mb || 400;

    // 显存分段
    const segments = this._calcVramSegments(status);
    const qosLevel = status.qos?.level || 'ok';
    const qosColor = qosLevel === 'ok' ? 'success' : qosLevel === 'warning' ? 'warning' : 'danger';

    body.innerHTML = `
      ${alerts.length > 0 ? `
        <div class="alert-banner">
          <div class="alert-banner__icon">${Icons.warning}</div>
          <div class="alert-banner__content">
            <div class="alert-banner__title">${alerts.length} 个活跃告警</div>
            <div class="alert-banner__meta">最近：${Utils.escapeHtml(alerts[0].message || alerts[0].alert_type)}</div>
          </div>
          <div class="alert-banner__actions">
            <button class="btn btn--secondary btn--sm" onclick="Router.go('/alerts')">查看详情</button>
          </div>
        </div>
      ` : ''}

      <!-- 显存水位卡 -->
      <div class="card mb-4">
        <div class="card__header">
          <div class="card__title">GPU 显存</div>
          <div class="card__actions">
            <span class="text-mono" style="font-size:24px;font-weight:700">${Utils.formatMB(vramUsed)} <span style="font-size:14px;color:var(--color-text-secondary)">/ ${Utils.formatMB(vramTotal)}</span></span>
            <span class="badge badge--${vramPct > 85 ? 'danger' : vramPct > 70 ? 'warning' : 'success'}" style="font-size:14px;padding:4px 10px;margin-left:8px">${vramPct}%</span>
          </div>
        </div>
        <div class="card__body">
          <div class="vram-bar vram-bar--lg">
            ${segments.map(s => `<div class="vram-bar__segment vram-bar__segment--${s.type}" style="width:${s.pct}%" title="${s.name}: ${Utils.formatMB(s.mb)}">${s.pct > 10 ? `<span class="vram-bar__label">${s.name} ${Utils.formatMB(s.mb)}</span>` : ''}</div>`).join('')}
          </div>
          <div class="flex items-center gap-4 mt-3 flex-wrap">
            <span class="badge badge--${qosColor}"><span class="status-dot status-dot--${qosColor}"></span> QoS ${qosLevel.toUpperCase()}</span>
            ${segments.filter(s => s.type !== 'free').map(s => `<span class="vram-mini-tag"><span class="vram-mini-tag__dot vram-mini-tag__dot--${s.type}"></span>${s.name} <b>${Utils.formatMB(s.mb)}</b></span>`).join('')}
            <span class="vram-mini-tag" style="margin-left:auto"><span class="vram-mini-tag__dot vram-mini-tag__dot--free"></span>空闲 <b>${Utils.formatMB(vramFree)}</b></span>
          </div>
        </div>
      </div>

      <!-- 统计卡 -->
      <div class="grid mb-4">
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.cpu}</span><span class="stat-card__label">GPU 显存</span></div>
          <div class="stat-card__value">${vramPct}<span class="stat-card__unit">%</span></div>
          <div class="stat-card__footer">已用 ${Utils.formatMB(vramUsed)} · 空闲 ${Utils.formatMB(vramFree)}</div>
        </div>
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.layers}</span><span class="stat-card__label">当前场景</span></div>
          <div class="stat-card__value" style="font-size:18px">${Utils.escapeHtml(typeof status.scene === 'string' ? status.scene : (status.scene?.current || '未知'))}</div>
          <div class="stat-card__footer">${Utils.escapeHtml(typeof status.scene === 'string' ? '' : (status.scene?.current_en || ''))}</div>
        </div>
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.box}</span><span class="stat-card__label">已加载模型</span></div>
          <div class="stat-card__value">${loadedModelCount}</div>
          <div class="stat-card__footer">${Utils.escapeHtml(loadedModelNames)}</div>
        </div>
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.activity}</span><span class="stat-card__label">QoS 状态</span></div>
          <div class="stat-card__value" style="font-size:18px;color:var(--color-${qosColor})">${qosLevel.toUpperCase()}</div>
          <div class="stat-card__footer"><span class="status-dot status-dot--${qosColor}"></span> ${qosLevel === 'ok' ? '正常' : qosLevel === 'warning' ? '注意' : '危险'}</div>
        </div>
      </div>

      <!-- 服务状态 + 快捷操作 -->
      <!-- 服务显存映射：从 gpu_processes 中提取每个服务的显存 -->
      ${(() => {
        const gp = status.gpu_processes || {};
        const procs = gp.processes || [];
        const serviceVramMap = {};
        procs.forEach(p => {
          const app = p.app || p.name || '';
          if (app) {
            serviceVramMap[app] = (serviceVramMap[app] || 0) + (p.used_mb || 0);
          }
        });
        window._serviceVramMap = serviceVramMap;
        return '';
      })()}
      <div class="grid mb-4">
        <div class="col-8">
          <div class="card">
            <div class="card__header">
              <div class="card__title">服务活跃度</div>
              <div class="card__actions"><button class="btn btn--ghost btn--sm" onclick="Router.go('/settings')">全部服务 →</button></div>
            </div>
            <div class="card__body--no-padding">
              <table class="table">
                <thead><tr><th>服务</th><th>状态</th><th>显存</th><th>操作</th></tr></thead>
                <tbody>
                  ${(Object.entries(status.activity?.services || {}).map(([name, s]) => ({
                    name: name,
                    running: s.busy !== undefined ? true : status.containers?.[name] !== false,
                    busy: s.busy || false,
                    idle_s: s.idle_s || 0,
                  })) || []).slice(0, 6).map(s => `
                    <tr>
                      <td>${Utils.escapeHtml(s.name)}</td>
                      <td><span class="status-dot status-dot--${s.running ? 'online' : 'offline'}"></span> ${s.running ? (s.busy ? '忙碌' : '在线') : '离线'}</td>
                      <td class="table__num text-mono">${(() => {
                        const sv = window._serviceVramMap || {};
                        const v = sv[s.name] || 0;
                        if (v > 0) return Utils.formatMB(v);
                        return s.busy ? '使用中' : '<span class="text-tertiary">空闲</span>';
                      })()}</td>
                      <td class="table__actions">
                        ${s.running
                          ? `<button class="btn btn--ghost btn--sm" onclick="Pages._serviceAction('${s.name}', 'stop')">停止</button>`
                          : `<button class="btn btn--ghost btn--sm" onclick="Pages._serviceAction('${s.name}', 'start')">启动</button>`}
                      </td>
                    </tr>
                  `).join('') || '<tr><td colspan="4" class="text-center text-tertiary">暂无服务数据</td></tr>'}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <div class="col-4">
          <div class="card">
            <div class="card__header"><div class="card__title">快捷操作</div></div>
            <div class="card__body" style="display:flex;flex-direction:column;gap:8px">
              <button class="btn btn--danger" onclick="document.getElementById('btn-free').click()">${Icons.zap} 一键释放显存</button>
              <button class="btn btn--secondary" onclick="Router.go('/scenes')">${Icons.layers} 切换场景</button>
              <button class="btn btn--secondary" onclick="Router.go('/diagnose')">${Icons.activity} 诊断中心</button>
              <button class="btn btn--secondary" onclick="Router.go('/alerts')">${Icons.bell} 告警中心</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 最近事件 -->
      <div class="card">
        <div class="card__header">
          <div class="card__title">最近事件</div>
          <div class="card__actions"><button class="btn btn--ghost btn--sm" onclick="Router.go('/diagnose')">查看全部 →</button></div>
        </div>
        <div class="card__body--no-padding">
          ${events.length > 0 ? `
            <div style="padding:12px 16px">
              ${events.slice(0, 8).map(e => `
                <div class="flex items-center gap-3" style="padding:6px 0;border-bottom:1px solid var(--color-border-light)">
                  <span class="text-mono text-tertiary" style="font-size:11px;min-width:60px">${Utils.formatTime(e.timestamp)}</span>
                  <span class="badge badge--${(() => {
                    const cat = e.category || '';
                    if (cat === 'vram' || cat === 'gpu') return 'danger';
                    if (cat === 'container' || cat === 'docker') return 'warning';
                    if (cat === 'model' || cat === 'service') return 'info';
                    if (cat === 'user_action' || cat === 'system') return 'success';
                    return 'neutral';
                  })()}" style="font-size:10px">${Utils.escapeHtml(e.category || '')}</span>
                  <span style="font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(e.message || e.event || '')}</span>
                </div>
              `).join('')}
            </div>
          ` : '<div class="empty-state"><div class="empty-state__icon">'+Icons.activity+'</div><div class="empty-state__title">暂无事件</div></div>'}
        </div>
      </div>
    `;
  },

  _getContainerList(containers) {
    if (Array.isArray(containers)) return containers.filter(c => typeof c === 'object');
    if (containers && Array.isArray(containers.all)) return containers.all.filter(c => typeof c === 'object');
    if (containers && typeof containers === 'object') {
      return Object.values(containers).filter(c => c && typeof c === 'object' && c.name);
    }
    return [];
  },

  _calcVramSegments(status) {
    // 使用 gpu_processes 中的准确数据，确保所有数字逻辑自洽
    const gpu = status.gpu || {};
    const gp = status.gpu_processes || {};
    const total = gpu.total_mb || 16384;
    const used = gpu.used_mb || 0;
    const free = gpu.free_mb || Math.max(0, total - used);

    // 已知进程显存（进程明细之和，优先用 known_total_mb）
    const knownMb = gp.known_total_mb || (gp.processes || []).reduce((sum, p) => sum + (p.used_mb || 0), 0);
    // 桌面进程显存
    const desktopMb = gp.desktop_used_mb || 0;
    // 系统底噪
    const baseMb = gp.system_baseline_mb || (status.vram_ledger?.noise_mb) || 400;

    // 确保分类之和不超过 used（数据可能有重叠，按比例缩放）
    const accounted = knownMb + desktopMb + baseMb;
    let other = Math.max(0, used - accounted);
    // 如果分类之和超过 used，按比例缩减 known/desktop/base
    if (accounted > used && accounted > 0) {
      const scale = used / accounted;
      other = 0;
    }

    const segs = [
      { type: 'base', name: '底噪', mb: Math.round(baseMb), colorIdx: 1 },
      { type: 'known', name: '已知进程', mb: Math.round(knownMb), colorIdx: 2 },
      { type: 'desktop', name: '桌面', mb: Math.round(desktopMb), colorIdx: 3 },
      { type: 'other', name: '未登记', mb: Math.round(other), colorIdx: 7 },
      { type: 'free', name: '空闲', mb: Math.round(free), colorIdx: 0 },
    ].filter(s => s.mb > 0);
    segs.forEach(s => s.pct = (s.mb / total) * 100);
    return segs;
  },

  async _serviceAction(name, action) {
    const res = await API.serviceAction({ service: name, action });
    if (res.ok) { Toast.success(`${name} ${action} 成功`); this._loadDashboard(); }
    else Toast.error(res.error?.message || '操作失败');
  },

  // ===== 诊断中心页 =====
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

  async _loadDiagnose() {
    const [eventsRes, rulesRes] = await Promise.all([API.getEvents({ limit: 50 }), API.getDiagnoseRules()]);
    const events = eventsRes.events || [];
    const rules = rulesRes.rules || [];
    this._renderTimeline(events);
    this._renderScenarios(rules);
    // 自动执行诊断
    this._runDiagnose();
  },

  async _runDiagnose() {
    const alertType = Utils.$('#diag-alert-type').value;
    const windowSec = parseInt(Utils.$('#diag-window').value) || 300;
    const resultsEl = Utils.$('#diag-results');
    resultsEl.innerHTML = '<div class="loading-overlay"><div class="spinner"></div></div>';
    const res = await API.diagnose({ alert_type: alertType || undefined, window_seconds: windowSec });
    const candidates = res.matched_rules || res.candidates || res.root_causes || [];
    const matchedScenarios = res.matched_failure_scenarios || [];
    // 更新故障场景卡片（展示匹配状态）
    this._renderScenarios(matchedScenarios);
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
                <button class="btn btn--ghost btn--sm">查看关联事件(${c.related_events?.length || 0})</button>
              </div>
            </div>
          `).join('') : '<div class="empty-state"><div class="empty-state__icon">'+Icons.activity+'</div><div class="empty-state__title">未匹配到根因规则</div><div class="empty-state__desc">系统当前状态正常，或需要更多事件数据</div></div>'}
          <div class="text-tertiary" style="font-size:11px;margin-top:12px">诊断规则: ${candidates.length > 0 ? (res.total_rules || 9) : 9} 条已加载</div>
        </div>
      </div>
    `;
  },

  _renderTimeline(events) {
    const el = Utils.$('#diag-timeline');
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
        <div class="card__body" style="max-height:500px;overflow-y:auto">
          ${events.length > 0 ? `
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
          ` : '<div class="empty-state"><div class="empty-state__icon">'+Icons.activity+'</div><div class="empty-state__title">暂无事件</div></div>'}
        </div>
      </div>
    `;
  },

  _renderScenarios(matchedScenarios) {
    const el = Utils.$('#diag-scenarios');
    if (!el) return;
    const allScenarios = [
      { id: 'FC-001', name: '显存耗尽/OOM风险', level: 'critical', trigger: '显存剩余 < 1GB 持续10秒' },
      { id: 'FC-002', name: '容器异常退出/频繁重启', level: 'warning', trigger: '5分钟内容器重启 ≥ 3次' },
      { id: 'FC-003', name: '推理延迟升高', level: 'warning', trigger: 'P95响应时间 > 阈值持续3次' },
      { id: 'FC-004', name: '任务队列堆积', level: 'info', trigger: '队列 pending > 5 持续30秒' },
      { id: 'FC-005', name: '服务不可达', level: 'danger', trigger: '健康检查连续3次失败' },
    ];
    const matchedIds = new Set((matchedScenarios || []).map(s => s.id));
    const matchedMap = {};
    (matchedScenarios || []).forEach(s => { matchedMap[s.id] = s; });

    el.innerHTML = `
      <div class="card__header">
        <div class="card__title">故障场景库（${allScenarios.length} 个已知场景，${matchedIds.size} 个匹配）</div>
        ${matchedIds.size > 0 ? '<span class="badge badge--danger">检测到 ' + matchedIds.size + ' 个匹配场景</span>' : ''}
      </div>
      <div class="card__body">
        <div class="grid">
          ${allScenarios.map(s => {
            const isMatched = matchedIds.has(s.id);
            const matched = matchedMap[s.id] || {};
            const steps = matched.resolution_steps || [];
            return `
              <div class="col-2 scene-fault-card ${isMatched ? 'scene-fault-card--matched' : ''}">
                <div class="scene-fault-card__header">
                  <div class="scene-fault-card__id">${s.id}</div>
                  ${isMatched ? '<span class="badge badge--success">匹配中</span>' : '<span class="badge badge--neutral">未触发</span>'}
                </div>
                <div class="scene-fault-card__name">${s.name}</div>
                <span class="badge badge--${s.level}">${s.level}</span>
                <div class="scene-fault-card__trigger">${s.trigger}</div>
                ${isMatched && matched.match_count ? '<div class="scene-fault-card__match">匹配规则: ' + matched.match_count + ' 条</div>' : ''}
                ${isMatched && steps.length > 0 ? '<div class="scene-fault-card__steps"><div class="scene-fault-card__steps-title">处置步骤:</div>' + steps.map(step => '<div class="scene-fault-card__step">' + Utils.escapeHtml(step) + '</div>').join('') + '</div>' : ''}
                ${isMatched && matched.verification ? '<div class="scene-fault-card__verify">验证: ' + Utils.escapeHtml(matched.verification) + '</div>' : ''}
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  },

  // ===== 告警中心页 =====
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
          <div class="stat-card__footer">${silenced.length > 0 ? `剩余 ${Utils.formatDuration(silenced[0].remaining_seconds)}` : '无静默告警'}</div>
        </div>
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.list}</span><span class="stat-card__label">历史记录</span></div>
          <div class="stat-card__value">${history.length}</div>
          <div class="stat-card__footer">最近 50 条</div>
        </div>
        <div class="col-3 stat-card">
          <div class="stat-card__header"><span class="stat-card__icon">${Icons.shield}</span><span class="stat-card__label">降噪率</span></div>
          <div class="stat-card__value" style="color:var(--color-success)">${noiseReductionRate}%</div>
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
  },

  // ===== 模型登记台页 =====
  async models() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">模型登记台
          <div class="page-header__actions">
            <button class="btn btn--secondary btn--sm" id="btn-model-refresh">${Icons.refresh} 刷新</button>
            <button class="btn btn--primary btn--sm" id="btn-model-scan">🔍 扫描新模型</button>
          </div>
        </div>
        <div class="page-header__subtitle" id="model-subtitle">加载中...</div>
      </div>
      <div class="filter-bar">
        <div class="filter-bar__item"><span class="filter-bar__label">类别</span>
          <select class="form-select" id="model-category" style="width:120px"><option value="">全部</option><option value="LLM">LLM</option><option value="图像">图像</option><option value="视频">视频</option><option value="音频">音频</option></select>
        </div>
        <div class="filter-bar__item"><span class="filter-bar__label">来源</span>
          <select class="form-select" id="model-source" style="width:120px"><option value="">全部</option><option value="ollama">Ollama</option><option value="comfyui">ComfyUI</option></select>
        </div>
        <div class="toolbar__search"><input class="form-input" id="model-search" placeholder="搜索模型名..."></div>
      </div>
      <div id="models-grid" class="grid"><div class="loading-overlay col-12"><div class="spinner"></div></div></div>
    `;
    Utils.$('#btn-model-refresh').onclick = () => this._loadModels();
    Utils.$('#btn-model-scan').onclick = async () => {
      Toast.info('正在扫描模型...');
      const res = await API.scanModels();
      if (res.ok) { Toast.success('扫描完成'); this._loadModels(); }
      else Toast.error(res.error?.message || '扫描失败');
    };
    ['model-category', 'model-source', 'model-search'].forEach(id => {
      Utils.$('#' + id).addEventListener('input', () => this._filterModels());
    });
    this._loadModels();
  },

  _allModels: [],
  _loadedModels: [],
  async _loadModels() {
    const res = await API.getRegistry();
    const reg = res || {};
    // 获取已加载模型列表（含实际显存占用）
    this._loadedModels = reg.loaded_models || [];
    const loadedNames = new Set(this._loadedModels.map(m => m.name));
    const loadedVramMap = {};
    this._loadedModels.forEach(m => { loadedVramMap[m.name] = m.size_gb || 0; });
    // 合并 ollama_models 和 comfyui_models，添加 source 字段和 vram_mb
    const ollamaModels = (reg.ollama_models || []).map(m => {
      const isLoaded = loadedNames.has(m.id || m.name);
      return {
        ...m,
        source: 'ollama',
        vram_mb: isLoaded ? Math.round((loadedVramMap[m.id || m.name] || 0) * 1024) : Math.round((m.vram_gb || 0) * 1024),
        loaded: isLoaded,
        installed: m.installed || false,
        actual_vram_gb: isLoaded ? (loadedVramMap[m.id || m.name] || 0) : null,
      };
    });
    const comfyModels = (reg.comfyui_models || []).map(m => ({
      ...m,
      source: 'comfyui',
      vram_mb: Math.round((m.vram_gb || 0) * 1024),
      loaded: false,  // ComfyUI 模型加载状态需要单独查询
      installed: m.installed || false,
      actual_vram_gb: null,
    }));
    this._allModels = [...ollamaModels, ...comfyModels];
    const loadedCount = this._allModels.filter(m => m.loaded).length;
    const loadedVram = reg.loaded_vram_gb || 0;
    Utils.$('#model-subtitle').textContent = `已登记 ${this._allModels.length} 个模型（Ollama ${ollamaModels.length} · ComfyUI ${comfyModels.length}）· 已加载 ${loadedCount} 个 · 占用 ${loadedVram}GB`;
    this._filterModels();
  },

  _filterModels() {
    const cat = Utils.$('#model-category').value;
    const src = Utils.$('#model-source').value;
    const q = Utils.$('#model-search').value.toLowerCase();
    const filtered = this._allModels.filter(m => {
      if (cat && !(m.category || '').includes(cat) && !(m.type || '').includes(cat)) return false;
      if (src && !(m.source || '').toLowerCase().includes(src)) return false;
      if (q && !(m.name || '').toLowerCase().includes(q)) return false;
      return true;
    });
    const grid = Utils.$('#models-grid');
    grid.innerHTML = filtered.length > 0 ? filtered.map(m => {
      const modelName = m.id || m.model || m.name || '';  // 优先使用原始模型名（如 qwen3.5:9b），用于后端操作
      const isLoaded = m.loaded || false;
      const isInstalled = m.installed || false;
      const actualVram = m.actual_vram_gb || 0;
      const vramText = isLoaded && actualVram > 0
        ? `实际: ${actualVram.toFixed(1)}GB`
        : `预估: ${Utils.formatMB(m.vram_mb || 0)}`;
      const statusBadge = isLoaded
        ? '<span class="badge badge--success">运行中</span>'
        : isInstalled
          ? '<span class="badge badge--info">已安装</span>'
          : '<span class="badge badge--neutral">未安装</span>';
      const actionBtn = isLoaded
        ? `<button class="btn btn--danger btn--sm" onclick="Pages._unloadModel('${Utils.escapeHtml(modelName)}')">卸载</button>`
        : isInstalled
          ? `<button class="btn btn--primary btn--sm" onclick="Pages._loadModel('${Utils.escapeHtml(modelName)}')">加载</button>`
          : '<button class="btn btn--ghost btn--sm" disabled>未安装</button>';
      return `
      <div class="col-3 model-card ${isLoaded ? 'model-card--loaded' : ''}">
        <div class="model-card__header">
          <span class="model-card__icon">${Icons.box}</span>
          <span class="model-card__name">${Utils.escapeHtml(modelName)}</span>
        </div>
        <div class="model-card__tags">
          <span class="badge badge--neutral">${Utils.escapeHtml(m.category || m.type || '未知')}</span>
          <span class="badge badge--neutral">${Utils.escapeHtml(m.source || '')}</span>
          ${statusBadge}
        </div>
        <div class="model-card__specs">
          <span>${vramText}</span>
          ${m.speed ? `<span>速度: ${m.speed}</span>` : ''}
        </div>
        <div class="model-card__actions">
          <button class="btn btn--ghost btn--sm">详情</button>
          ${actionBtn}
        </div>
      </div>`;
    }).join('') : '<div class="empty-state col-12"><div class="empty-state__icon">'+Icons.box+'</div><div class="empty-state__title">暂无模型</div></div>';
  },

  async _loadModel(name) {
    Toast.info('正在加载...');
    const res = await API.loadModel({ model: name });
    if (res.ok) {
      Toast.success(`已加载 ${name}`);
      State.set('status', null);
      if (typeof updateHeader === 'function') updateHeader();
      this._loadModels();
    } else {
      Toast.error(res.error?.message || '加载失败');
    }
  },
  async _unloadModel(name) {
    Modal.confirm({
      title: '卸载模型',
      message: `确认卸载模型 ${name}？将释放其占用的显存。`,
      confirmText: '卸载',
      danger: true,
      onConfirm: async () => {
        Toast.info('正在卸载...');
        const beforeStatus = State.get('status');
        const beforeUsed = beforeStatus?.gpu?.used_mb || 0;
        const res = await API.unloadModel({ model: name });
        if (res.ok) {
          // 等待3秒让显存真正释放
          await new Promise(r => setTimeout(r, 3000));
          // 重新获取状态
          State.set('status', null);
          const statusRes = await API.getStatus();
          const status = statusRes;
          State.set('status', status);
          if (typeof updateHeader === 'function') updateHeader();
          this._loadModels();
          const afterUsed = status.gpu?.used_mb || 0;
          const freed = Math.max(0, beforeUsed - afterUsed);
          // 显示详细卸载结果
          const remainingProcs = (status.gpu_processes?.processes || []).filter(p => (p.used_mb || 0) > 100);
          let remainingHtml = '<div style="margin-top:12px"><div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:6px">当前仍在占用显存的进程：</div>';
          if (remainingProcs.length > 0) {
            remainingProcs.forEach(p => {
              const pName = p.app ? p.app + ' (' + (p.name || 'python') + ')' : (p.name || 'unknown');
              remainingHtml += `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--color-border-light);font-size:12px"><span>${Utils.escapeHtml(pName)}</span><span class="text-mono" style="font-weight:600">${Utils.formatMB(p.used_mb || 0)}</span></div>`;
            });
          } else {
            remainingHtml += '<div style="padding:4px 0;font-size:12px;color:var(--color-text-tertiary)">无 GPU 计算进程</div>';
          }
          remainingHtml += `<div style="display:flex;justify-content:space-between;padding:6px 0;margin-top:4px;font-size:12px;font-weight:600;border-top:2px solid var(--color-border)"><span>GPU 总占用</span><span class="text-mono" style="color:var(--color-brand-500)">${Utils.formatMB(afterUsed)} / ${Utils.formatMB(status.gpu?.total_mb || 16384)}</span></div></div>`;
          Modal.open({
            title: '模型卸载结果',
            size: 'md',
            content: `
              <div style="margin-bottom:12px;padding:12px;background:rgba(13,148,136,0.08);border-radius:8px">
                <div style="font-size:13px;font-weight:600;color:var(--color-brand-500);margin-bottom:4px">卸载完成</div>
                <div style="font-size:12px;color:var(--color-text-secondary)">模型：${Utils.escapeHtml(name)}${freed > 0 ? ` · 释放 ${Utils.formatMB(freed)}` : ''}</div>
              </div>
              ${remainingHtml}
            `,
            footer: '<button class="btn btn--primary" data-action="close">确定</button>',
          });
          Modal.modal.querySelector('[data-action="close"]').onclick = () => Modal.close();
        } else {
          Toast.error(res.error?.message || '卸载失败');
        }
      },
    });
  },

  // ===== 显存账本页 =====
  async vram() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">显存账本
          <div class="page-header__actions">
            <button class="btn btn--secondary btn--sm" id="btn-vram-refresh">${Icons.refresh} 刷新</button>
            <button class="btn btn--danger btn--sm" id="btn-vram-free">${Icons.zap} 一键释放</button>
          </div>
        </div>
        <div class="page-header__subtitle">进程级显存明细与趋势分析</div>
      </div>
      <div id="vram-body"><div class="loading-overlay"><div class="spinner"></div></div></div>
    `;
    Utils.$('#btn-vram-refresh').onclick = () => this._loadVram();
    Utils.$('#btn-vram-free').onclick = () => this._doFreeVram();
    this._loadVram();
  },

  // 一键释放（公共函数，显示详细释放结果）
  async _doFreeVram() {
    Modal.confirm({
      title: '一键释放显存',
      message: '将执行显存释放（停止空闲模型+服务），释放后模型可能重新加载。确认？',
      confirmText: '释放',
      danger: true,
      onConfirm: async () => {
        Toast.info('正在释放显存...');
        const res = await API.freeVram('L1');
        if (res.ok) {
          const data = res;
          const freed = data.freed_mb || 0;
          const before = data.free_mb_before || 0;
          const after = data.free_mb_after || 0;
          const actions = data.actions || [];
          // 等待2秒，让显存真正释放
          await new Promise(r => setTimeout(r, 2000));
          // 重新获取状态，获取当前仍在占用显存的进程
          State.set('status', null);
          const statusRes = await API.getStatus();
          const status = statusRes;
          State.set('status', status);
          if (typeof updateHeader === 'function') updateHeader();
          // 构建释放结果详情
          const successActions = actions.filter(a => a.ok);
          const failActions = actions.filter(a => !a.ok);
          let releasedHtml = '';
          if (successActions.length > 0) {
            releasedHtml = '<div style="margin-bottom:12px"><div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:6px">已释放的进程/服务：</div>';
            successActions.forEach(a => {
              const freedMb = a.freed_mb || 0;
              releasedHtml += `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--color-border-light);font-size:12px"><span style="color:var(--color-success)">✓ ${Utils.escapeHtml(a.name || 'unknown')}</span><span class="text-mono">${a.action}${freedMb > 0 ? ' · 释放 ' + Utils.formatMB(freedMb) : ''}</span></div>`;
            });
            releasedHtml += '</div>';
          } else {
            releasedHtml = '<div style="margin-bottom:12px;padding:8px;background:rgba(245,158,11,0.08);border-radius:6px;font-size:12px;color:var(--color-warning)">未释放任何进程（当前没有可释放的空闲模型/服务）</div>';
          }
          if (failActions.length > 0) {
            releasedHtml += '<div style="margin-bottom:12px"><div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:6px">释放失败：</div>';
            failActions.forEach(a => {
              releasedHtml += `<div style="padding:4px 0;font-size:12px;color:var(--color-danger)">✗ ${Utils.escapeHtml(a.name || 'unknown')} - ${Utils.escapeHtml(a.output || a.action || '未知错误')}</div>`;
            });
            releasedHtml += '</div>';
          }
          // 剩余仍在占用显存的进程
          const remainingProcs = (status.gpu_processes?.processes || []).filter(p => (p.used_mb || 0) > 100);
          const desktopUsed = status.gpu_processes?.desktop_used_mb || 0;
          const gpuUsed = status.gpu?.used_mb || 0;
          let remainingHtml = '<div><div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:6px">当前仍在占用显存的进程：</div>';
          if (remainingProcs.length > 0) {
            remainingProcs.forEach(p => {
              const pName = p.app ? p.app + ' (' + (p.name || 'python') + ')' : (p.name || 'unknown');
              remainingHtml += `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--color-border-light);font-size:12px"><span>${Utils.escapeHtml(pName)}</span><span class="text-mono" style="font-weight:600">${Utils.formatMB(p.used_mb || 0)}</span></div>`;
            });
          } else {
            remainingHtml += '<div style="padding:4px 0;font-size:12px;color:var(--color-text-tertiary)">无 GPU 计算进程</div>';
          }
          if (desktopUsed > 0) {
            remainingHtml += `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--color-border-light);font-size:12px"><span style="color:var(--color-text-tertiary)">Windows 桌面进程（合计）</span><span class="text-mono">${Utils.formatMB(desktopUsed)}</span></div>`;
          }
          remainingHtml += `<div style="display:flex;justify-content:space-between;padding:6px 0;margin-top:4px;font-size:12px;font-weight:600;border-top:2px solid var(--color-border)"><span>GPU 总占用</span><span class="text-mono" style="color:var(--color-brand-500)">${Utils.formatMB(gpuUsed)} / ${Utils.formatMB(status.gpu?.total_mb || 16384)}</span></div>`;
          remainingHtml += '</div>';
          // 显示详细结果 Modal
          Modal.open({
            title: '显存释放结果',
            size: 'md',
            content: `
              <div style="margin-bottom:16px;padding:12px;background:rgba(13,148,136,0.08);border-radius:8px">
                <div style="font-size:13px;font-weight:600;color:var(--color-brand-500);margin-bottom:4px">释放完成</div>
                <div style="font-size:12px;color:var(--color-text-secondary)">空闲 ${Utils.formatMB(before)} → ${Utils.formatMB(after)}${freed > 0 ? ` · 释放 ${Utils.formatMB(freed)}` : ''}</div>
              </div>
              ${releasedHtml}
              ${remainingHtml}
            `,
            footer: '<button class="btn btn--primary" data-action="close">确定</button>',
          });
          Modal.modal.querySelector('[data-action="close"]').onclick = () => {
            Modal.close();
            // 根据当前页面决定刷新哪个页面
            const hash = window.location.hash;
            if (hash === '#/vram' && typeof this._loadVram === 'function') {
              this._loadVram();
            } else if (hash === '#/dashboard' && typeof this._loadDashboard === 'function') {
              this._loadDashboard();
            }
          };
        } else {
          Toast.error(res.error?.message || '释放失败');
        }
      },
    });
  },

  async _loadVram() {
    // 优先使用全局状态（统一数据源，避免多次请求和数据不一致）
    let status = State.get('status');
    if (!status) {
      const res = await API.getStatus();
      status = res;
      State.set('status', status);
    }
    const gpu = status.gpu || {};
    const gp = status.gpu_processes || {};
    const ledger = status.vram_ledger || {};
    const total = gpu.total_mb || 16384;
    const used = gpu.used_mb || 0;
    const free = gpu.free_mb || Math.max(0, total - used);
    // 可释放显存 = 真实空闲 - 2G安全余量（如果空闲<2G则为0）
    const releasable = Math.max(0, free - 2048);
    const segments = this._calcVramSegments(status);
    const processes = gp.processes || [];
    // 前端自己计算预期已用和差异，确保和分布条一致（不依赖后端 vram_ledger 的错误计算）
    const baseNoise = gp.system_baseline_mb || ledger.noise_mb || 400;
    const knownMb = gp.known_total_mb || processes.reduce((sum, p) => sum + (p.used_mb || 0), 0);
    const desktopMb = gp.desktop_used_mb || 0;
    const expectedUsed = baseNoise + knownMb + desktopMb;
    const diffMb = Math.max(0, used - expectedUsed);

    const body = Utils.$('#vram-body');
    // 前端自己计算状态，不依赖后端 vram_ledger 的错误数据
    const isConsistent = diffMb < 1024;
    body.innerHTML = `
      ${!isConsistent ? `<div class="alert-banner mb-4" style="border-left-color:var(--color-warning-600);background:rgba(245,158,11,0.08)">
        <div class="alert-banner__icon" style="color:var(--color-warning)">${Icons.warning}</div>
        <div class="alert-banner__content">
          <div class="alert-banner__title">发现未登记显存 ${Utils.formatMB(diffMb)}</div>
          <div class="alert-banner__meta">实际已用超出预期，可能有未受管进程在使用显存，建议检查进程明细</div>
        </div>
      </div>` : ''}
      <div class="grid mb-4">
        <div class="col-3 stat-card"><div class="stat-card__label">实际已用</div><div class="stat-card__value">${Utils.formatMB(used)}</div><div class="stat-card__footer">nvidia-smi 实时</div></div>
        <div class="col-3 stat-card"><div class="stat-card__label">预期已用</div><div class="stat-card__value">${Utils.formatMB(expectedUsed)}</div><div class="stat-card__footer">底噪+${Utils.formatMB(knownMb)}进程+${Utils.formatMB(desktopMb)}桌面</div></div>
        <div class="col-3 stat-card"><div class="stat-card__label">差异(未登记)</div><div class="stat-card__value" style="color:${diffMb > 1024 ? 'var(--color-danger)' : 'var(--color-success)'}">${Utils.formatMB(diffMb)}</div><div class="stat-card__footer">${diffMb > 1024 ? '有未登记进程' : '账实相符'}</div></div>
        <div class="col-3 stat-card"><div class="stat-card__label">已知进程显存</div><div class="stat-card__value">${Utils.formatMB(knownMb)}</div><div class="stat-card__footer">${processes.length} 个进程</div></div>
      </div>
      <div class="card mb-4">
        <div class="card__body">
          <div class="vram-bar" style="height:20px">
            ${segments.map(s => `<div class="vram-bar__segment vram-bar__segment--${s.type}" style="width:${s.pct}%"></div>`).join('')}
          </div>
          <div class="vram-legend mt-3">
            ${segments.map(s => `<div class="vram-legend__item"><span class="vram-legend__color vram-legend__color--${s.type}"></span>${s.name} ${Utils.formatMB(s.mb)}</div>`).join('')}
          </div>
        </div>
      </div>
      <div class="grid mb-4">
        <div class="col-8">
          <div class="card">
            <div class="card__header"><div class="card__title">显存趋势</div>
              <div class="card__actions">
                <select class="form-select" style="width:100px;height:28px;font-size:11px"><option>1小时</option><option>6小时</option><option>24小时</option></select>
              </div>
            </div>
            <div class="card__body" style="padding:12px">
              <div id="vram-trend-stats" class="vram-trend-stats"></div>
              <div id="vram-trend-chart"></div>
              <div class="flex justify-between text-tertiary" style="font-size:11px;margin-top:4px">
                <span>已用显存趋势（最近 ${State.vramHistory.length} 个采样点，每10秒）</span>
                <span id="vram-trend-current"></span>
              </div>
            </div>
          </div>
        </div>
        <div class="col-4">
          <div class="card">
            <div class="card__header"><div class="card__title">智能建议</div></div>
            <div class="card__body">
              <div class="stat-card" style="margin-bottom:12px">
                <div class="stat-card__label">可释放显存</div>
                <div class="stat-card__value" style="color:${releasable > 1024 ? 'var(--color-brand-500)' : 'var(--color-text-tertiary)'}">${Utils.formatMB(releasable)}</div>
                <div class="stat-card__footer">${releasable > 0 ? '空闲模型 + 空闲服务（保留2G安全余量）' : '空闲不足2G，暂无可安全释放的显存'}</div>
              </div>
              ${processes.filter(p => (p.used_mb || 0) > 100).length > 0 ? `
              <div style="margin-bottom:12px">
                <div class="text-secondary" style="font-size:11px;margin-bottom:6px">可停止进程释放显存：</div>
                ${processes.filter(p => (p.used_mb || 0) > 100).map(p => `
                  <div class="flex items-center justify-between" style="padding:4px 0;border-bottom:1px solid var(--color-border-light)">
                    <span class="text-mono" style="font-size:11px">${Utils.escapeHtml(p.app || p.name || 'unknown')}</span>
                    <span class="text-mono" style="font-size:11px;font-weight:600">${Utils.formatMB(p.used_mb || 0)}</span>
                  </div>
                `).join('')}
              </div>
              ` : ''}
              <button class="btn btn--primary w-full" id="btn-vram-free-inline">一键释放</button>
            </div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card__header"><div class="card__title">进程级显存明细</div>
          <div class="card__actions"><span class="badge badge--neutral">${processes.length} 个进程 · 合计 ${Utils.formatMB(knownMb)}</span></div>
        </div>
        <div class="card__body--no-padding">
          ${processes.length > 0 ? `
            <table class="table">
              <thead><tr><th>进程</th><th>PID</th><th>类型</th><th>显存</th><th>首次出现</th><th>操作</th></tr></thead>
              <tbody>
                ${processes.map(p => {
                  const pUsed = p.used_mb || 0;
                  const isIdle = pUsed < 100;
                  const pName = p.app ? p.app + ' (' + (p.name || 'python') + ')' : (p.name || 'unknown');
                  const firstSeen = p.first_seen ? new Date(p.first_seen * 1000).toLocaleTimeString() : '—';
                  return `
                  <tr style="${isIdle ? 'opacity:0.5' : ''}">
                    <td class="text-mono">${Utils.escapeHtml(pName)}</td>
                    <td class="text-mono">${p.pid || '—'}</td>
                    <td><span class="badge badge--${p.known ? 'success' : 'warning'}">${Utils.escapeHtml(p.app || (p.known ? '受管' : '未登记'))}</span></td>
                    <td class="table__num text-mono" style="font-weight:600">${Utils.formatMB(pUsed)}${isIdle ? ' <span class="text-tertiary" style="font-size:10px">(空闲)</span>' : ''}</td>
                    <td class="text-mono text-tertiary" style="font-size:11px">${firstSeen}</td>
                    <td class="table__actions">
                      ${p.known
                        ? `<button class="btn btn--ghost btn--sm" onclick="Pages._serviceAction('${p.app || p.name}', 'stop')">停止</button>`
                        : `<button class="btn btn--danger btn--sm" onclick="Pages._kickProcess(${p.pid})">驱逐</button>`}
                    </td>
                  </tr>`;
                }).join('')}
              </tbody>
            </table>
          ` : '<div class="empty-state"><div class="empty-state__icon">'+Icons.cpu+'</div><div class="empty-state__title">暂无进程数据</div><div class="empty-state__desc">当前没有检测到 GPU 进程</div></div>'}
        </div>
      </div>
    `;
    // 渲染显存趋势SVG图
    this._renderVramTrend();

    // 绑定一键释放按钮（调用公共函数）
    const freeBtn = Utils.$('#btn-vram-free-inline');
    if (freeBtn) {
      freeBtn.onclick = () => this._doFreeVram();
    }
  },

  _renderVramTrend() {
    const el = Utils.$('#vram-trend-chart');
    if (!el) return;
    const history = State.vramHistory;
    const width = 700, height = 200, padding = { top: 15, right: 15, bottom: 30, left: 55 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    if (history.length < 2) {
      el.innerHTML = '<div style="height:200px;display:flex;align-items:center;justify-content:center;color:var(--color-text-tertiary);font-size:12px">正在收集显存数据...（至少需要2个采样点）</div>';
      return;
    }

    // 统计信息
    const values = history.map(h => h.used);
    const currentVal = values[values.length - 1];
    const avgVal = Math.round(values.reduce((a, b) => a + b, 0) / values.length);
    const peakVal = Math.max(...values);
    const minVal = Math.min(...values);
    const total = history[history.length - 1].total || 16384;

    // Y轴：使用整齐的刻度（0, 4G, 8G, 12G, 16G），根据峰值动态调整
    const niceTicks = [0, 2048, 4096, 6144, 8192, 10240, 12288, 14336, 16384];
    const yMax = Math.max(...niceTicks.filter(t => t >= peakVal * 1.1), 4096);
    const visibleTicks = niceTicks.filter(t => t <= yMax);

    const points = history.map((h, i) => {
      const x = padding.left + (i / (history.length - 1)) * chartW;
      const y = padding.top + chartH - (h.used / yMax) * chartH;
      return { x, y, ...h };
    });

    const pathD = points.map((p, i) => (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1)).join(' ');
    const areaD = pathD + ` L${points[points.length-1].x.toFixed(1)},${(padding.top + chartH).toFixed(1)} L${points[0].x.toFixed(1)},${(padding.top + chartH).toFixed(1)} Z`;

    // Y轴刻度（整齐刻度）
    const yTicks = visibleTicks.map(val => {
      const y = padding.top + chartH - (val / yMax) * chartH;
      return `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="var(--color-border-light)" stroke-width="1" stroke-dasharray="${val === 0 ? '0' : '3,3'}"/><text x="${padding.left - 8}" y="${y + 4}" text-anchor="end" fill="var(--color-text-tertiary)" font-size="10">${Utils.formatMB(val)}</text>`;
    }).join('');

    // X轴时间标签（相对时间，智能精度）
    const xTickCount = Math.min(5, history.length);
    const xTicks = Array.from({ length: xTickCount }, (_, i) => {
      const idx = Math.round((i / (xTickCount - 1)) * (history.length - 1));
      const p = points[idx];
      const timeAgo = Math.round((Date.now() - p.t) / 1000);
      let label;
      if (i === xTickCount - 1) {
        label = '现在';
      } else if (timeAgo < 90) {
        label = timeAgo + '秒前';
      } else if (timeAgo < 3600) {
        const mins = Math.floor(timeAgo / 60);
        const secs = timeAgo % 60;
        label = mins + '分' + (secs > 0 ? secs + '秒' : '') + '前';
      } else {
        label = Math.round(timeAgo / 3600) + '小时前';
      }
      return `<text x="${p.x.toFixed(1)}" y="${height - 8}" text-anchor="middle" fill="var(--color-text-tertiary)" font-size="10">${label}</text>`;
    }).join('');

    const last = points[points.length - 1];
    const currentEl = Utils.$('#vram-trend-current');
    if (currentEl) currentEl.textContent = `当前: ${Utils.formatMB(last.used)} / ${Utils.formatMB(last.total)}`;

    // 更新统计信息
    const statsEl = Utils.$('#vram-trend-stats');
    if (statsEl) {
      statsEl.innerHTML = `
        <div class="vram-stat"><span class="vram-stat__label">当前</span><span class="vram-stat__value" style="color:var(--color-brand-500)">${Utils.formatMB(currentVal)}</span></div>
        <div class="vram-stat"><span class="vram-stat__label">平均</span><span class="vram-stat__value">${Utils.formatMB(avgVal)}</span></div>
        <div class="vram-stat"><span class="vram-stat__label">峰值</span><span class="vram-stat__value" style="color:var(--color-warning)">${Utils.formatMB(peakVal)}</span></div>
        <div class="vram-stat"><span class="vram-stat__label">最低</span><span class="vram-stat__value" style="color:var(--color-success)">${Utils.formatMB(minVal)}</span></div>
      `;
    }

    // 安全阈值线（14GB，超过显示红色警告区域）
    const SAFE_THRESHOLD_MB = 14336;
    let warningZone = '';
    let thresholdLine = '';
    if (SAFE_THRESHOLD_MB < yMax) {
      const thresholdY = padding.top + chartH - (SAFE_THRESHOLD_MB / yMax) * chartH;
      warningZone = `<rect x="${padding.left}" y="${padding.top}" width="${chartW}" height="${(thresholdY - padding.top).toFixed(1)}" fill="var(--color-danger)" opacity="0.05"/>`;
      thresholdLine = `<line x1="${padding.left}" y1="${thresholdY.toFixed(1)}" x2="${width - padding.right}" y2="${thresholdY.toFixed(1)}" stroke="var(--color-danger)" stroke-width="1" stroke-dasharray="6,3"/>
        <text x="${width - padding.right - 5}" y="${thresholdY - 4}" text-anchor="end" fill="var(--color-danger)" font-size="9" font-weight="600">安全阈值 ${Utils.formatMB(SAFE_THRESHOLD_MB)}</text>`;
    }

    // 平均线
    const avgY = padding.top + chartH - (avgVal / yMax) * chartH;
    const avgLine = `<line x1="${padding.left}" y1="${avgY.toFixed(1)}" x2="${width - padding.right}" y2="${avgY.toFixed(1)}" stroke="var(--color-text-tertiary)" stroke-width="1" stroke-dasharray="2,4"/>
      <text x="${padding.left + 5}" y="${avgY - 4}" fill="var(--color-text-tertiary)" font-size="9">平均 ${Utils.formatMB(avgVal)}</text>`;

    // 峰值标注
    const peakIdx = values.indexOf(peakVal);
    const peakPoint = points[peakIdx];
    // 如果峰值是最后一个点，标签向左偏移避免与当前值圆点重叠
    const isLastPoint = peakIdx === points.length - 1;
    const peakLabelX = isLastPoint ? peakPoint.x - 50 : peakPoint.x;
    const peakLabelAnchor = isLastPoint ? 'end' : 'middle';
    const peakMarker = `<g>
      <circle cx="${peakPoint.x.toFixed(1)}" cy="${peakPoint.y.toFixed(1)}" r="5" fill="var(--color-warning)" stroke="var(--color-bg-2)" stroke-width="2"/>
      <text x="${peakLabelX.toFixed(1)}" y="${(peakPoint.y - 10).toFixed(1)}" text-anchor="${peakLabelAnchor}" fill="var(--color-warning)" font-size="9" font-weight="600">峰值 ${Utils.formatMB(peakVal)}</text>
    </g>`;

    // 谷值标注（只在与峰值不同时显示）
    let valleyMarker = '';
    if (minVal < peakVal && minVal < avgVal) {
      const valleyIdx = values.indexOf(minVal);
      const valleyPoint = points[valleyIdx];
      // 标签放在圆点上方，确保不被底部截断
      const valleyLabelY = Math.max(valleyPoint.y - 12, padding.top + 10);
      valleyMarker = `<g>
        <circle cx="${valleyPoint.x.toFixed(1)}" cy="${valleyPoint.y.toFixed(1)}" r="5" fill="var(--color-success)" stroke="var(--color-bg-2)" stroke-width="2"/>
        <text x="${valleyPoint.x.toFixed(1)}" y="${valleyLabelY.toFixed(1)}" text-anchor="middle" fill="var(--color-success)" font-size="9" font-weight="600">最低 ${Utils.formatMB(minVal)}</text>
      </g>`;
    }

    // 悬停提示层
    const hoverLayer = `
      <rect id="vram-hover-rect" x="${padding.left}" y="${padding.top}" width="${chartW}" height="${chartH}" fill="transparent" style="cursor:crosshair"/>
      <g id="vram-hover-indicator" style="display:none">
        <line id="vram-hover-line" x1="0" y1="${padding.top}" x2="0" y2="${padding.top + chartH}" stroke="var(--color-brand-400)" stroke-width="1" stroke-dasharray="4,2"/>
        <circle id="vram-hover-dot" cx="0" cy="0" r="5" fill="var(--color-brand-500)" stroke="var(--color-bg-2)" stroke-width="2"/>
      </g>
      <g id="vram-hover-tooltip" style="display:none">
        <rect id="vram-tooltip-bg" x="0" y="0" width="120" height="40" rx="6" fill="var(--color-bg-3)" stroke="var(--color-border)" stroke-width="1"/>
        <text id="vram-tooltip-time" x="60" y="16" text-anchor="middle" fill="var(--color-text-secondary)" font-size="10"></text>
        <text id="vram-tooltip-value" x="60" y="32" text-anchor="middle" fill="var(--color-brand-500)" font-size="12" font-weight="600"></text>
      </g>
    `;

    el.innerHTML = `
      <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" id="vram-trend-svg">
        <defs>
          <linearGradient id="vramAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--color-brand-500)" stop-opacity="0.3"/>
            <stop offset="100%" stop-color="var(--color-brand-500)" stop-opacity="0.02"/>
          </linearGradient>
        </defs>
        ${yTicks}
        ${xTicks}
        ${warningZone}
        ${thresholdLine}
        ${avgLine}
        <path d="${areaD}" fill="url(#vramAreaGrad)"/>
        <path d="${pathD}" fill="none" stroke="var(--color-brand-500)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
        ${peakMarker}
        ${valleyMarker}
        <circle cx="${last.x.toFixed(1)}" cy="${last.y.toFixed(1)}" r="4" fill="var(--color-brand-500)" stroke="var(--color-bg-2)" stroke-width="2"/>
        ${hoverLayer}
      </svg>
    `;

    // 绑定悬停事件
    const svg = el.querySelector('#vram-trend-svg');
    const hoverRect = el.querySelector('#vram-hover-rect');
    const hoverIndicator = el.querySelector('#vram-hover-indicator');
    const hoverLine = el.querySelector('#vram-hover-line');
    const hoverDot = el.querySelector('#vram-hover-dot');
    const tooltip = el.querySelector('#vram-hover-tooltip');
    const tooltipBg = el.querySelector('#vram-tooltip-bg');
    const tooltipTime = el.querySelector('#vram-tooltip-time');
    const tooltipValue = el.querySelector('#vram-tooltip-value');

    if (hoverRect && svg) {
      hoverRect.addEventListener('mousemove', (e) => {
        const rect = svg.getBoundingClientRect();
        const scaleX = width / rect.width;
        const mouseX = (e.clientX - rect.left) * scaleX;
        // 找到最近的点
        let nearest = points[0];
        let minDist = Infinity;
        for (const p of points) {
          const dist = Math.abs(p.x - mouseX);
          if (dist < minDist) {
            minDist = dist;
            nearest = p;
          }
        }
        // 显示指示器
        hoverIndicator.style.display = 'block';
        hoverLine.setAttribute('x1', nearest.x);
        hoverLine.setAttribute('x2', nearest.x);
        hoverDot.setAttribute('cx', nearest.x);
        hoverDot.setAttribute('cy', nearest.y);
        // 显示提示
        tooltip.style.display = 'block';
        const timeAgo = Math.round((Date.now() - nearest.t) / 1000);
        let timeLabel;
        if (timeAgo < 60) timeLabel = timeAgo + '秒前';
        else if (timeAgo < 3600) timeLabel = Math.round(timeAgo / 60) + '分钟前';
        else timeLabel = Math.round(timeAgo / 3600) + '小时前';
        tooltipTime.textContent = timeLabel;
        tooltipValue.textContent = Utils.formatMB(nearest.used);
        // 提示位置（避免超出边界）
        let tooltipX = nearest.x + 10;
        if (tooltipX + 120 > width - padding.right) tooltipX = nearest.x - 130;
        let tooltipY = nearest.y - 50;
        if (tooltipY < padding.top) tooltipY = nearest.y + 10;
        tooltip.setAttribute('transform', `translate(${tooltipX}, ${tooltipY})`);
      });
      hoverRect.addEventListener('mouseleave', () => {
        hoverIndicator.style.display = 'none';
        tooltip.style.display = 'none';
      });
    }
  },

  // ===== 场景切换页 =====
  async scenes() {
    const container = Utils.$('#app-content');
    const scenes = [
      { id: 'dialogue', name: '对话态', icon: '💬', services: 'Ollama + OWUI', vram: '~6GB', desc: '聊天/编码/本地对话' },
      { id: 'generation', name: '生成态', icon: '🎬', services: 'ComfyUI + Fooocus', vram: '~12GB', desc: '图像生成/高质量出图' },
      { id: 'video', name: '视频态', icon: '🎥', services: 'ComfyUI (Wan2.2)', vram: '~11GB', desc: '视频生成/短片创作' },
      { id: 'music', name: '音乐态', icon: '🎵', services: 'ComfyUI (Music3)', vram: '~8GB', desc: '音乐生成/音频创作' },
      { id: 'idle', name: '空闲态', icon: '😴', services: '仅基础服务', vram: '~4GB', desc: '释放显存/低功耗' },
      { id: 'exclusive', name: '独占态', icon: '🔒', services: '单服务独占', vram: '~14GB', desc: '大模型推理/高性能' },
    ];
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">场景切换
          <div class="page-header__actions"><button class="btn btn--secondary btn--sm" id="btn-scene-refresh">${Icons.refresh} 刷新</button></div>
        </div>
        <div class="page-header__subtitle">6 个预设场景一键切换，自动启停对应服务</div>
      </div>
      <div id="scene-current" class="card mb-4"><div class="card__body"><div class="loading-overlay"><div class="spinner"></div></div></div></div>
      <div class="grid">
        ${scenes.map(s => `
          <div class="col-4 scene-card" data-scene="${s.id}">
            <div class="scene-card__header">
              <span style="font-size:28px">${s.icon}</span>
              <div class="scene-card__name">${s.name}</div>
            </div>
            <div class="scene-card__services">${s.services}</div>
            <div class="scene-card__vram">${Icons.cpu} 显存: ${s.vram}</div>
            <div class="scene-card__desc">${s.desc}</div>
            <button class="btn btn--primary w-full scene-switch-btn" data-scene="${s.id}">切换</button>
          </div>
        `).join('')}
      </div>
    `;
    Utils.$('#btn-scene-refresh').onclick = () => this._loadScenes();
    Utils.$$('.scene-switch-btn').forEach(btn => {
      btn.onclick = () => {
        const scene = btn.dataset.scene;
        Modal.confirm({ title: '切换场景', message: `切换到 ${scenes.find(s => s.id === scene)?.name} 将停止当前服务，确认？`, confirmText: '切换', onConfirm: async () => {
          const res = await API.switchScene({ scene });
          if (res.ok) { Toast.success('场景切换成功'); this._loadScenes(); }
          else Toast.error(res.error?.message || '切换失败');
        }});
      };
    });
    this._loadScenes();
  },

  async _loadScenes() {
    const res = await API.getScenes();
    const current = res.current || res.scene || 'unknown';
    const el = Utils.$('#scene-current');
    el.innerHTML = `
      <div class="card__body">
        <div class="flex items-center gap-4">
          <div>
            <div class="text-secondary" style="font-size:12px">当前场景</div>
            <div style="font-size:24px;font-weight:700">${Utils.escapeHtml(current)}</div>
          </div>
          <div class="flex items-center gap-2">
            <span class="status-dot status-dot--online status-dot--pulse"></span>
            <span class="text-secondary">运行中</span>
          </div>
        </div>
      </div>
    `;
    Utils.$$('.scene-card').forEach(card => {
      const isCurrent = card.dataset.scene === current || card.querySelector('.scene-card__name').textContent.includes(current);
      card.classList.toggle('scene-card--current', isCurrent);
      const btn = card.querySelector('.scene-switch-btn');
      if (isCurrent) { btn.textContent = '当前场景'; btn.disabled = true; btn.className = 'btn btn--success w-full'; }
    });
  },

  // ===== 任务队列页 =====
  async queue() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">任务队列
          <div class="page-header__actions"><button class="btn btn--secondary btn--sm" id="btn-queue-refresh">${Icons.refresh} 刷新</button></div>
        </div>
        <div class="page-header__subtitle">串行化生成任务队列，预算预检 + 进度反馈</div>
      </div>
      <div class="grid mb-4">
        <div class="col-5">
          <div class="card">
            <div class="card__header"><div class="card__title">提交新任务</div></div>
            <div class="card__body">
              <div class="form-group">
                <label class="form-label">模型</label>
                <select class="form-select" id="task-model">
                  <option value="flux_q5">Flux Q5 (图像)</option>
                  <option value="wan2_2">Wan2.2 5B (视频)</option>
                  <option value="sdxl">SDXL (图像)</option>
                  <option value="music3">Music3 (音频)</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">提示词</label>
                <textarea class="form-textarea" id="task-prompt" placeholder="输入生成提示词..."></textarea>
              </div>
              <div class="form-row">
                <div class="form-group"><label class="form-label">宽度</label><input class="form-input" id="task-width" type="number" value="1024"></div>
                <div class="form-group"><label class="form-label">高度</label><input class="form-input" id="task-height" type="number" value="1024"></div>
              </div>
              <div class="form-row">
                <div class="form-group"><label class="form-label">步数</label><input class="form-input" id="task-steps" type="number" value="30"></div>
                <div class="form-group"><label class="form-label">CFG</label><input class="form-input" id="task-cfg" type="number" value="7.0" step="0.5"></div>
              </div>
              <div class="mb-3"><span class="badge badge--success">✅ 显存充足</span></div>
              <button class="btn btn--primary w-full" id="btn-submit-task">提交任务</button>
            </div>
          </div>
        </div>
        <div class="col-7">
          <div class="card">
            <div class="card__header"><div class="card__title">队列状态</div></div>
            <div class="card__body">
              <div class="grid mb-4">
                <div class="col-4 stat-card"><div class="stat-card__label">运行中</div><div class="stat-card__value" id="q-running">0</div></div>
                <div class="col-4 stat-card"><div class="stat-card__label">等待中</div><div class="stat-card__value" id="q-waiting">0</div></div>
                <div class="col-4 stat-card"><div class="stat-card__label">已完成</div><div class="stat-card__value" id="q-done">0</div></div>
              </div>
              <div id="q-current"><div class="text-tertiary">暂无运行中任务</div></div>
            </div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card__header"><div class="card__title">任务列表</div>
          <div class="card__actions"><button class="btn btn--ghost btn--sm">清空已完成</button></div>
        </div>
        <div class="card__body--no-padding" id="task-list"><div class="loading-overlay"><div class="spinner"></div></div></div>
      </div>
    `;
    Utils.$('#btn-queue-refresh').onclick = () => this._loadQueue();
    Utils.$('#btn-submit-task').onclick = async () => {
      const body = {
        model: Utils.$('#task-model').value,
        prompt: Utils.$('#task-prompt').value,
        width: parseInt(Utils.$('#task-width').value),
        height: parseInt(Utils.$('#task-height').value),
        steps: parseInt(Utils.$('#task-steps').value),
        cfg: parseFloat(Utils.$('#task-cfg').value),
      };
      const res = await API.submitTask(body);
      if (res.ok) { Toast.success('任务已提交'); this._loadQueue(); }
      else Toast.error(res.error?.message || '提交失败');
    };
    this._loadQueue();
  },

  async _loadQueue() {
    const res = await API.getQueue();
    const tasks = res.tasks || res.queue || [];
    const running = tasks.filter(t => t.status === 'running' || t.state === 'running').length;
    const waiting = tasks.filter(t => t.status === 'pending' || t.state === 'waiting').length;
    const done = tasks.filter(t => t.status === 'completed' || t.state === 'done').length;
    Utils.$('#q-running').textContent = running;
    Utils.$('#q-waiting').textContent = waiting;
    Utils.$('#q-done').textContent = done;

    const list = Utils.$('#task-list');
    list.innerHTML = tasks.length > 0 ? `
      <table class="table">
        <thead><tr><th>#</th><th>模型</th><th>状态</th><th>进度</th><th>提交时间</th><th>操作</th></tr></thead>
        <tbody>
          ${tasks.map((t, i) => `
            <tr>
              <td class="text-mono">${String(i+1).padStart(3,'0')}</td>
              <td>${Utils.escapeHtml(t.model || t.workflow || '')}</td>
              <td><span class="badge badge--${t.status === 'running' ? 'info' : t.status === 'completed' ? 'success' : t.status === 'failed' ? 'danger' : 'neutral'}">${t.status || t.state || '未知'}</span></td>
              <td><div class="progress" style="width:100px"><div class="progress__fill" style="width:${t.progress || 0}%"></div></div></td>
              <td class="text-mono" style="font-size:11px">${Utils.formatTime(t.submitted_at || t.created_at)}</td>
              <td class="table__actions">${t.status === 'running' || t.status === 'pending' ? `<button class="btn btn--ghost btn--sm" onclick="Pages._cancelTask('${t.id || t.task_id}')">取消</button>` : '<button class="btn btn--ghost btn--sm">查看</button>'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    ` : '<div class="empty-state"><div class="empty-state__icon">'+Icons.list+'</div><div class="empty-state__title">暂无任务</div><div class="empty-state__desc">提交一个生成任务开始使用</div></div>';
  },

  async _cancelTask(id) {
    Modal.confirm({ title: '取消任务', message: '确认取消该任务？', confirmText: '取消任务', danger: true, onConfirm: async () => {
      const res = await API.cancelTask({ task_id: id });
      if (res.ok) { Toast.success('任务已取消'); this._loadQueue(); }
      else Toast.error(res.error?.message || '取消失败');
    }});
  },

  // ===== 门卫页 =====
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

  async _loadGuard() {
    const res = await API.getStatus();
    const status = res;
    const gp = status.gpu_processes || {};
    const guard = status.guard || {};
    const processes = gp.processes || [];
    const knownCount = processes.filter(p => p.known).length;
    const unknownCount = gp.unknown_pids?.length || 0;
    const body = Utils.$('#guard-body');
    body.innerHTML = `
      <div class="alert-banner" style="border-left-color:var(--color-brand-600);background:rgba(13,148,136,0.08)">
        <div class="alert-banner__icon" style="color:var(--color-brand-500)">${Icons.shield}</div>
        <div class="alert-banner__content">
          <div class="alert-banner__title">门卫状态: ${Utils.escapeHtml(guard.level || 'ok')}</div>
          <div class="alert-banner__meta">受管进程 ${knownCount} · 桌面进程 ${gp.desktop_count || 0} · 未登记 ${unknownCount} · 已知显存 ${Utils.formatMB(gp.known_total_mb || 0)}</div>
        </div>
      </div>
      <div class="card mt-4">
        <div class="card__header"><div class="card__title">进程列表</div>
          <div class="card__actions">
            <select class="form-select" style="width:120px;height:28px;font-size:11px"><option>全部</option><option>受管</option><option>桌面</option><option>未登记</option></select>
          </div>
        </div>
        <div class="card__body--no-padding">
          ${processes.length > 0 ? `
            <table class="table">
              <thead><tr><th>进程名</th><th>PID</th><th>类型</th><th>显存</th><th>保护</th><th>操作</th></tr></thead>
              <tbody>
                ${processes.map(p => `
                  <tr>
                    <td class="text-mono">${Utils.escapeHtml(p.name || '')}</td>
                    <td class="text-mono">${p.pid || '—'}</td>
                    <td><span class="badge badge--${p.known ? 'success' : 'warning'}">${Utils.escapeHtml(p.app || (p.known ? '受管' : '未登记'))}</span></td>
                    <td class="table__num text-mono">${Utils.formatMB(p.used_mb || 0)}</td>
                    <td>${p.known ? '<span class="badge badge--success">受管</span>' : '—'}</td>
                    <td class="table__actions">${p.known ? '' : `<button class="btn btn--ghost btn--sm" onclick="Pages._kickProcess(${p.pid})">驱逐</button>`}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          ` : '<div class="empty-state"><div class="empty-state__icon">'+Icons.shield+'</div><div class="empty-state__title">暂无进程数据</div></div>'}
        </div>
      </div>
    `;
  },

  async _kickProcess(pid) {
    Modal.confirm({ title: '驱逐进程', message: `确认驱逐进程 PID ${pid}？`, confirmText: '驱逐', danger: true, onConfirm: async () => {
      const res = await API.guardKick({ pid });
      if (res.ok) { Toast.success('进程已驱逐'); this._loadGuard(); }
      else Toast.error(res.error?.message || '驱逐失败');
    }});
  },

  // ===== Audit 操作审计页 =====
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
  },

  // ===== 设置页 =====
  settings() {
    const container = Utils.$('#app-content');
    const sections = [
      { id: 'system', name: '系统配置', icon: '⚙️' },
      { id: 'services', name: '服务管理', icon: '📦' },
      { id: 'qos', name: 'QoS 配置', icon: '🎚️' },
      { id: 'autoprotect', name: '自动防死机', icon: '🛡️' },
      { id: 'account', name: '账号管理', icon: '👤' },
      { id: 'watchdog', name: '看门狗', icon: '📋' },
      { id: 'about', name: '关于', icon: 'ℹ️' },
    ];
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">设置</div>
        <div class="page-header__subtitle">系统配置与管理</div>
      </div>
      <div class="settings-layout">
        <div class="settings-nav">
          ${sections.map((s, i) => `
            <div class="settings-nav__item ${i === 0 ? 'settings-nav__item--active' : ''}" data-section="${s.id}">
              <span>${s.icon}</span> ${s.name}
            </div>
          `).join('')}
        </div>
        <div class="settings-content" id="settings-content"></div>
      </div>
    `;
    Utils.$$('.settings-nav__item').forEach(item => {
      item.onclick = () => {
        Utils.$$('.settings-nav__item').forEach(i => i.classList.remove('settings-nav__item--active'));
        item.classList.add('settings-nav__item--active');
        this._renderSettingsSection(item.dataset.section);
      };
    });
    this._renderSettingsSection('system');
  },

  _renderSettingsSection(section) {
    const el = Utils.$('#settings-content');
    const content = {
      system: `
        <div class="card">
          <div class="card__header"><div class="card__title">系统配置</div></div>
          <div class="card__body">
            <div class="form-row">
              <div class="form-group"><label class="form-label">服务端口</label><input class="form-input" value="8787"></div>
              <div class="form-group"><label class="form-label">监听地址</label><select class="form-select"><option>0.0.0.0</option><option>127.0.0.1</option></select></div>
            </div>
            <div class="form-row">
              <div class="form-group"><label class="form-label">日志级别</label><select class="form-select"><option>info</option><option>debug</option><option>warning</option><option>error</option></select></div>
              <div class="form-group"><label class="form-label">日志保留</label><select class="form-select"><option>30 天</option><option>7 天</option><option>90 天</option></select></div>
            </div>
            <div class="form-row">
              <div class="form-group"><label class="form-label">状态缓存 TTL</label><input class="form-input" value="10 秒"></div>
              <div class="form-group"><label class="form-label">自动刷新间隔</label><input class="form-input" value="10 秒"></div>
            </div>
            <div class="flex gap-2 mt-4">
              <button class="btn btn--primary">保存更改</button>
              <button class="btn btn--secondary">恢复默认</button>
            </div>
          </div>
        </div>
      `,
      services: `
        <div class="card">
          <div class="card__header"><div class="card__title">服务管理</div></div>
          <div class="card__body--no-padding">
            <table class="table">
              <thead><tr><th>服务</th><th>容器</th><th>状态</th><th>端口</th><th>操作</th></tr></thead>
              <tbody>
                ${['Ollama|ollama|11434','ComfyUI|comfyui|8188','Open WebUI|open-webui|3000','Immich|immich|2283','SearXNG|searxng|8888'].map(s => {
                  const [name, container, port] = s.split('|');
                  return `<tr><td>${name}</td><td class="text-mono">${container}</td><td><span class="status-dot status-dot--online"></span> 在线</td><td class="text-mono">${port}</td><td class="table__actions"><button class="btn btn--ghost btn--sm">重启</button><button class="btn btn--ghost btn--sm">停止</button></td></tr>`;
                }).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `,
      qos: `
        <div class="card">
          <div class="card__header"><div class="card__title">QoS 配置</div></div>
          <div class="card__body">
            <div class="form-row">
              <div class="form-group"><label class="form-label">GREEN 阈值</label><input class="form-input" value="8 GB"></div>
              <div class="form-group"><label class="form-label">YELLOW 阈值</label><input class="form-input" value="4 GB"></div>
              <div class="form-group"><label class="form-label">RED 阈值</label><input class="form-input" value="2 GB"></div>
            </div>
            <div class="flex items-center gap-3 mt-4">
              <div class="toggle"></div>
              <span>自动降级（默认关闭）</span>
            </div>
            <button class="btn btn--primary mt-4">保存配置</button>
          </div>
        </div>
      `,
      autoprotect: `
        <div class="card">
          <div class="card__header"><div class="card__title">自动防死机</div></div>
          <div class="card__body">
            <div class="flex items-center gap-3 mb-4">
              <div class="toggle"></div>
              <span>总开关（用户授权后启用）</span>
            </div>
            <div class="form-group">
              <label class="form-label">保护模式</label>
              <div class="flex gap-4">
                <label class="flex items-center gap-2"><input type="radio" name="mode"> 保守</label>
                <label class="flex items-center gap-2"><input type="radio" name="mode" checked> 标准</label>
                <label class="flex items-center gap-2"><input type="radio" name="mode"> 激进</label>
              </div>
            </div>
            <div class="text-tertiary mt-4" style="font-size:12px">保护规则：永不杀桌面进程 / protect 容器（只读）</div>
            <button class="btn btn--primary mt-4">保存配置</button>
          </div>
        </div>
      `,
      account: `
        <div class="card">
          <div class="card__header"><div class="card__title">账号管理</div></div>
          <div class="card__body">
            <div class="form-group"><label class="form-label">当前密码</label><input type="password" class="form-input"></div>
            <div class="form-row">
              <div class="form-group"><label class="form-label">新密码</label><input type="password" class="form-input"></div>
              <div class="form-group"><label class="form-label">确认新密码</label><input type="password" class="form-input"></div>
            </div>
            <button class="btn btn--primary mt-4">修改密码</button>
          </div>
        </div>
      `,
      watchdog: `
        <div class="card">
          <div class="card__header"><div class="card__title">看门狗</div></div>
          <div class="card__body">
            <div class="flex items-center gap-3 mb-4">
              <span class="status-dot status-dot--online status-dot--pulse"></span>
              <span>运行中 · PID 12345 · 运行 2小时30分</span>
            </div>
            <div class="form-row">
              <div class="form-group"><label class="form-label">崩溃后延迟</label><input class="form-input" value="5 秒"></div>
              <div class="form-group"><label class="form-label">1小时最大重启</label><input class="form-input" value="5 次"></div>
              <div class="form-group"><label class="form-label">健康检查间隔</label><input class="form-input" value="30 秒"></div>
            </div>
            <button class="btn btn--primary mt-4">保存配置</button>
          </div>
        </div>
      `,
      about: `
        <div class="card">
          <div class="card__header"><div class="card__title">关于</div></div>
          <div class="card__body">
            <div class="text-center mb-4">
              <div style="font-size:32px;font-weight:700;color:var(--color-brand-500)">GMae</div>
              <div class="text-secondary mt-1">GPU Maestro - 显存指挥家</div>
            </div>
            <table class="table">
              <tbody>
                <tr><td>版本</td><td class="text-mono">v1.0.0</td></tr>
                <tr><td>子项目</td><td>16G-AI-Studio (16GAS)</td></tr>
                <tr><td>核心引擎</td><td>Prism Engine (P-Eng)</td></tr>
                <tr><td>标语</td><td>One GPU, Infinite Models</td></tr>
                <tr><td>许可证</td><td>MIT</td></tr>
                <tr><td>技术栈</td><td>Python / 原生 JS / Docker</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      `,
    };
    el.innerHTML = content[section] || '<div class="text-tertiary">该功能开发中</div>';
  },
};
