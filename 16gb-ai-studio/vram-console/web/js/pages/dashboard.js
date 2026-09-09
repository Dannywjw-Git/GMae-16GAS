/* ============================================================
 * Pages - 总览页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
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
    if (Router.current !== '/dashboard') return;  // 切页竞态守卫
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
    const baseNoise = status.gpu_processes?.baseline_mb || status.gpu_processes?.system_baseline_mb || status.vram_ledger?.noise_mb || 400;

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
            ${segments.map(s => `<div class="vram-bar__segment vram-bar__segment--${s.type}" style="width:${s.pct}%" title="${s.name}: ${Utils.formatMB(s.mb)}">${s.pct > 3 ? `<span class="vram-bar__label" title="${
    s.type === 'base' ? '系统底噪：GPU驱动 + WDDM + WSL2/Docker基础开销（动态测量，随系统状态变化）' :
    s.type === 'known' ? '已知进程：受管AI服务的显存占用（Ollama/ComfyUI/Fooocus等，运行在WSL2 Docker容器中）' :
    s.type === 'desktop' ? '桌面进程：Windows桌面应用的GPU显存（浏览器/微信/dwm等，通过性能计数器采集）' :
    s.type === 'other' ? '未登记显存：无法归因到具体进程的显存，可能包含WSL2中未追踪的进程、驱动开销、计算误差等。点击显存账本查看进程明细。' :
    s.name + ': ' + Utils.formatMB(s.mb)
}" style="cursor:help">${s.name} ${Utils.formatMB(s.mb)}</span>` : ''}</div>`).join('')}
          </div>
          <div class="flex items-center gap-4 mt-3 flex-wrap">
            <span class="badge badge--${qosColor}"><span class="status-dot status-dot--${qosColor}"></span> QoS ${qosLevel.toUpperCase()}</span>
            ${segments.filter(s => s.type !== 'free').map(s => `<span class="vram-mini-tag" style="cursor:help" title="${
    s.type === 'base' ? '系统底噪：GPU驱动 + WDDM + WSL2/Docker基础开销（动态测量）' :
    s.type === 'known' ? '已知进程：受管AI服务显存（Ollama/ComfyUI/Fooocus，运行在WSL2 Docker中）' :
    s.type === 'desktop' ? '桌面进程：Windows桌面应用GPU显存（浏览器/微信/dwm等）' :
    s.type === 'other' ? '未登记显存：无法归因的显存，可能包含WSL2中未追踪的进程。点击显存账本查看明细。' :
    s.name
}"><span class="vram-mini-tag__dot vram-mini-tag__dot--${s.type}"></span>${s.name} <b>${Utils.formatMB(s.mb)}</b></span>`).join('')}
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
          <div class="stat-card__footer" title="${Utils.escapeHtml(loadedModelNames)}">${Utils.escapeHtml(loadedModelNames.length > 20 ? loadedModelNames.substring(0, 18) + '...' : loadedModelNames)}</div>
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
                  ${(Object.entries(status.activity?.services || {}).map(([name, s]) => {
                    const pausedList = status.containers?.paused || [];
                    const isPaused = pausedList.includes(name);
                    return {
                    name: name,
                    running: s.busy !== undefined ? true : status.containers?.[name] !== false,
                    busy: s.busy || false,
                    idle_s: s.idle_s || 0,
                    paused: isPaused,
                    };
                  }) || []).slice(0, 6).map(s => `
                    <tr>
                      <td>${Utils.escapeHtml(s.name)}</td>
                      <td><span class="status-dot status-dot--${s.paused ? 'warning' : s.running ? 'online' : 'offline'}"></span> ${s.paused ? '已暂停' : s.running ? (s.busy ? '忙碌' : '在线') : '离线'}</td>
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
                <div class="flex items-start gap-3" style="padding:8px 0;border-bottom:1px solid var(--color-border-light)">
                  <span class="text-mono text-tertiary" style="font-size:11px;min-width:70px;padding-top:2px" title="${Utils.formatTime(e.timestamp)}">${(() => {
                        const t = e.timestamp ? new Date(e.timestamp * 1000).getTime() : Date.now();
                        const diff = Math.floor((Date.now() - t) / 1000);
                        if (diff < 60) return diff + '秒前';
                        if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
                        if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
                        return Utils.formatTime(e.timestamp);
                      })()}</span>
                  <span class="badge badge--${(() => {
                    const cat = e.category || '';
                    if (cat === 'vram' || cat === 'gpu') return 'danger';
                    if (cat === 'container' || cat === 'docker') return 'warning';
                    if (cat === 'model' || cat === 'service') return 'info';
                    if (cat === 'user_action' || cat === 'system') return 'success';
                    return 'neutral';
                  })()}" style="font-size:10px;flex-shrink:0;margin-top:1px">${Utils.escapeHtml(e.category || '')}</span>
                  <div style="flex:1;min-width:0">
                    <div style="font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(e.message || e.event || '')}</div>
                    ${(() => {
                      const desc = Pages._getEventDescription(e.message || e.event || '');
                      return desc ? `<div style="font-size:11px;color:var(--color-text-tertiary);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${desc}</div>` : '';
                    })()}
                  </div>
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
    // 【统一显存帐本】全系统唯一的显存分类计算函数
    // 数据源：status.gpu（权威）+ status.gpu_processes（分类明细）
    // 计算逻辑：已用 = 底噪 + 已知进程 + 桌面 + 未登记；空闲 = 总量 - 已用
    // 约束：分类之和 = 已用；已用 + 空闲 = 总量
    const gpu = status.gpu || {};
    const gp = status.gpu_processes || {};
    const total = gpu.total_mb || 16384;
    const used = gpu.used_mb || 0;
    // 空闲以总量-已用为准（不依赖后端返回的free_mb，避免不一致）
    const free = Math.max(0, total - used);

    // 已知分类（从 gpu_processes 提取，字段名兼容）
    const baseMb = gp.baseline_mb || gp.system_baseline_mb || (status.vram_ledger?.noise_mb) || 400;
    const knownMb = gp.known_total_mb || (gp.processes || []).reduce((sum, p) => sum + (p.used_mb || 0), 0);
    const desktopMb = gp.desktop_used_mb || (gp.desktop_processes || []).reduce((sum, p) => sum + (p.used_mb || 0), 0);

    // 未登记 = 已用 - 底噪 - 已知进程 - 桌面（确保不为负）
    // 注意：不使用后端返回的 unknown_mb，因为它的定义可能与前端计算不一致
    const accounted = baseMb + knownMb + desktopMb;
    let otherMb = Math.max(0, used - accounted);

    // 如果已知分类之和超过已用，按比例缩放（确保分类之和 = 已用）
    let scaledBase = baseMb, scaledKnown = knownMb, scaledDesktop = desktopMb;
    if (accounted > used && accounted > 0) {
      const scale = used / accounted;
      scaledBase = Math.round(baseMb * scale);
      scaledKnown = Math.round(knownMb * scale);
      scaledDesktop = Math.round(desktopMb * scale);
      otherMb = 0;
    }

    const segs = [
      { type: 'base', name: '底噪', mb: scaledBase, colorIdx: 1 },
      { type: 'known', name: '已知进程', mb: scaledKnown, colorIdx: 2 },
      { type: 'desktop', name: '桌面', mb: scaledDesktop, colorIdx: 3 },
      { type: 'other', name: '未登记', mb: Math.round(otherMb), colorIdx: 7 },
      { type: 'free', name: '空闲', mb: Math.round(free), colorIdx: 0 },
    ].filter(s => s.mb > 0);
    segs.forEach(s => s.pct = (s.mb / total) * 100);
    return segs;
  },

  // 【统一显存帐本】获取显存分类的详细数据（供所有页面使用，避免重复计算）
  _getVramBreakdown(status) {
    const segs = this._calcVramSegments(status);
    const find = (type) => (segs.find(s => s.type === type) || { mb: 0, pct: 0 });
    return {
      total: status.gpu?.total_mb || 16384,
      used: status.gpu?.used_mb || 0,
      free: Math.max(0, (status.gpu?.total_mb || 16384) - (status.gpu?.used_mb || 0)),
      base: find('base'),
      known: find('known'),
      desktop: find('desktop'),
      other: find('other'),
      segments: segs,
      // 问题归因：未登记显存占比过高时标记
      hasUnknownIssue: find('other').mb > (status.gpu?.total_mb || 16384) * 0.1,
      // 处置建议：根据显存状态给出统一的处置建议
      getSuggestions: function() {
        const suggestions = [];
        if (this.used / this.total > 0.85) {
          suggestions.push({ type: 'critical', action: 'release', text: '显存危险，建议立即一键释放' });
        } else if (this.used / this.total > 0.7) {
          suggestions.push({ type: 'warning', action: 'release', text: '显存较高，建议释放空闲模型' });
        }
        if (this.hasUnknownIssue) {
          suggestions.push({ type: 'info', action: 'inspect', text: '未登记显存较多，建议检查进程明细' });
        }
        if (this.known.mb > 0) {
          suggestions.push({ type: 'info', action: 'models', text: `已加载 ${Math.round(this.known.mb / 1024)}G 模型，可卸载释放显存` });
        }
        return suggestions;
      }
    };
  },
});
