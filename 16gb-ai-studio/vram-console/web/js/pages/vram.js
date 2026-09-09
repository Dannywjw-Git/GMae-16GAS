/* ============================================================
 * Pages - 显存账本页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
  // 显存账本页入口：渲染骨架后交由 _loadVram 加载数据
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
    // 显存账本页5秒局部轮询（全局是10秒，趋势图需要更高刷新率）
    if (this._vramPollTimer) clearInterval(this._vramPollTimer);
    this._vramPollTimer = setInterval(() => {
      if (location.hash === '#/vram') this._loadVram();
    }, 5000);
    this._loadVram();
  },

  async _loadVram() {
    // 优先使用全局状态（统一数据源，避免多次请求和数据不一致）
    let status = State.get('status');
    if (!status) {
      const res = await API.getStatus();
      status = res;
      State.set('status', status);
    }
    // 【统一显存帐本】使用统一的 _getVramBreakdown，确保所有页面数据一致
    if (Router.current !== '/vram') return;  // 切页竞态守卫
    const breakdown = this._getVramBreakdown(status);
    const gpu = status.gpu || {};
    const gp = status.gpu_processes || {};
    const total = breakdown.total;
    const used = breakdown.used;
    const free = breakdown.free;
    // 可释放显存 = 真实空闲 - 2G安全余量（如果空闲<2G则为0）
    const releasable = Math.max(0, free - 2048);
    const segments = breakdown.segments;
    const processes = gp.processes || [];
    // 桌面进程（Windows 图形进程，来自 PowerShell 性能计数器）
    const desktopProcs = (gp.desktop_processes || []).filter(p => (p.used_mb || 0) >= 20);
    // 系统关键进程（不允许结束）
    const SYSTEM_PROCS = ['system', 'registry', 'smss', 'csrss', 'wininit', 'services', 'lsass', 'svchost', 'dwm', 'explorer', 'winlogon', 'fontdrvhost', 'sihost', 'taskhostw', 'textinputhost', 'searchhost', 'shellhost', 'shellexperiencehost', 'startmenuexperiencehost', 'applicationframehost', 'msmpeng', 'securityhealthservice', 'vmmem', 'vmmemwsl', 'vmwp', 'wudfhost', 'spoolsv', 'audiodg'];
    const isSystemProc = (name) => SYSTEM_PROCS.some(s => (name || '').toLowerCase().includes(s));
    // 合并所有进程到明细表格
    const allProcesses = [
      ...processes.map(p => ({...p, _category: 'known'})),
      ...desktopProcs.map(p => ({...p, _category: 'desktop', name: p.name, app: p.name, pid: String(p.pid), used_mb: p.used_mb, known: false})),
    ];
    this._gpuProcessList = allProcesses;  // 缓存供进程行停止操作按 pid 反查
    // 使用统一计算结果，避免重复计算导致不一致
    const baseNoise = breakdown.base.mb;
    const knownMb = breakdown.known.mb;
    const desktopMb = breakdown.desktop.mb;
    const expectedUsed = baseNoise + knownMb + desktopMb;
    const diffMb = breakdown.other.mb;  // 未登记显存 = 差异

    // 内存数据（2026-09-05 新增系统资源监控）
    const sys = status.system || {};
    const memTotal = sys.total_mb || 0;
    const memUsed = sys.used_mb || 0;
    const memFree = sys.free_mb || 0;
    const memPct = sys.percent || 0;
    const memColor = memPct > 90 ? 'var(--color-danger)' : memPct > 75 ? 'var(--color-warning)' : 'var(--color-success)';

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
          <div class="flex justify-between items-center mb-2">
            <span class="text-secondary" style="font-size:12px">显存占用</span>
            <span class="text-mono" style="font-size:12px">${Utils.formatMB(used)} / ${Utils.formatMB(total)} (${(used/total*100).toFixed(1)}%)</span>
          </div>
          <div class="vram-bar" style="height:20px">
            ${segments.map(s => `<div class="vram-bar__segment vram-bar__segment--${s.type}" style="width:${s.pct}%"></div>`).join('')}
          </div>
          <div class="vram-legend mt-3">
            ${segments.map(s => `<div class="vram-legend__item"><span class="vram-legend__color vram-legend__color--${s.type}"></span>${s.name} ${Utils.formatMB(s.mb)}</div>`).join('')}
          </div>
        </div>
      </div>
      ${memTotal > 0 ? `
      <div class="card mb-4">
        <div class="card__body">
          <div class="flex justify-between items-center mb-2">
            <span class="text-secondary" style="font-size:12px">内存占用</span>
            <span class="text-mono" style="font-size:12px;color:${memColor}">${Utils.formatMB(memUsed)} / ${Utils.formatMB(memTotal)} (${memPct}%)</span>
          </div>
          <div style="height:12px;background:var(--color-bg-tertiary);border-radius:6px;overflow:hidden">
            <div style="height:100%;width:${memPct}%;background:${memColor};transition:width 0.3s"></div>
          </div>
          <div class="flex justify-between mt-2" style="font-size:11px;color:var(--color-text-tertiary)">
            <span>空闲 ${Utils.formatMB(memFree)}</span>
            <span>${memPct > 90 ? '⚠️ 内存打满会导致 docker exec 失效，已触发自动保护' : memPct > 75 ? '内存偏高，注意关闭不必要程序' : '内存正常'}</span>
          </div>
        </div>
      </div>` : ''}
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
          <div class="card__actions">
            <span class="badge badge--neutral">${processes.length} 受管 · ${desktopProcs.length} 桌面 · 合计 ${Utils.formatMB(knownMb + (gp.desktop_used_mb || 0))}</span>
          </div>
        </div>
        <div class="card__body--no-padding">
          ${allProcesses.length > 0 ? `
            <table class="table">
              <thead><tr><th>进程</th><th>PID</th><th>类型</th><th>显存</th><th>首次出现</th><th>操作</th></tr></thead>
              <tbody>
                ${allProcesses.map(p => {
                  const pUsed = p.used_mb || 0;
                  const isIdle = pUsed < 100;
                  const pName = p.name || p.app || 'unknown';
                  const isDesktop = p._category === 'desktop';
                  const isSys = isDesktop && isSystemProc(pName);
                  const KIND_LABEL = { checkpoint: '主模型', unet: 'UNet', vae: 'VAE', clip: '文本编码器', clip_vision: '视觉编码器', lora: 'LoRA', controlnet: 'ControlNet', upscale: '放大模型', style: '风格模型' };
                  const typeLabel = isDesktop ? '桌面' : (p.overhead ? '框架/缓存' : (p.kind ? (KIND_LABEL[p.kind] || p.kind) : (p.app || (p.known ? '受管' : '未登记'))));
                  const badgeClass = isDesktop ? (isSys ? 'neutral' : 'info') : (p.known ? 'success' : 'warning');
                  const firstSeen = p.first_seen ? new Date(p.first_seen * 1000).toLocaleTimeString() : '—';
                  let actionBtn = '';
                  if (isDesktop) {
                    actionBtn = isSys
                      ? '<span class="text-tertiary" style="font-size:11px">系统进程</span>'
                      : `<button class="btn btn--danger btn--sm" onclick="Pages._killDesktopProcess(${p.pid}, '${Utils.escapeHtml(pName).replace(/'/g, "\\'")}')">结束</button>`;
                  } else if (p.known) {
                    actionBtn = `<button class="btn btn--ghost btn--sm" onclick="Pages._stopGpuProcess('${p.pid}')">停止</button>`;
                  } else {
                    actionBtn = `<button class="btn btn--danger btn--sm" onclick="Pages._kickProcess(${p.pid})">驱逐</button>`;
                  }
                  return `
                  <tr style="${isIdle ? 'opacity:0.5' : ''}">
                    <td class="text-mono">${Utils.escapeHtml(pName)}</td>
                    <td class="text-mono">${p.pid || '—'}</td>
                    <td><span class="badge badge--${badgeClass}">${Utils.escapeHtml(typeLabel)}</span></td>
                    <td class="table__num text-mono" style="font-weight:600">${Utils.formatMB(pUsed)}${p.estimated ? ' <span class="text-tertiary" style="font-size:10px">(估)</span>' : (isIdle ? ' <span class="text-tertiary" style="font-size:10px">(空闲)</span>' : '')}</td>
                    <td class="text-mono text-tertiary" style="font-size:11px">${firstSeen}</td>
                    <td class="table__actions">${actionBtn}</td>
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

  // 进程级显存明细：停止单个受管进程，按 app 类型分发到对应后端能力
  async _stopGpuProcess(pid) {
    const p = (this._gpuProcessList || []).find(x => String(x.pid) === String(pid));
    if (!p) { Toast.error('未找到该进程，请刷新后重试'); return; }
    // Ollama：按模型精准卸载（只释放该模型显存，不停容器、不影响其他模型）
    if (p.app === 'ollama') {
      const model = p.model || '';
      if (!model) { Toast.error('该进程缺少模型标识，无法单独卸载'); return; }
      const ok = await Modal.confirmAsync('卸载模型', '确定卸载「' + model + '」以释放显存吗？不会停止 Ollama 容器本身。');
      if (!ok) return;
      Toast.info('正在卸载模型 ' + model + ' ...');
      const res = await API.unloadModel({ name: model });
      if (res.ok) {
        Toast.success('模型「' + model + '」已卸载');
        State.set('status', null);
        if (typeof updateHeader === 'function') updateHeader();
        this._loadVram();
      } else {
        Toast.error('卸载失败：' + (res.output || (res.error && res.error.message) || '未知错误'));
      }
      return;
    }
    // ComfyUI / Fooocus：容器级停止（复用公共服务操作，带确认与刷新）
    this._serviceAction(p.container || p.app, 'stop');
  },

  // 结束桌面进程（安全范围：非系统进程，带确认）
  async _killDesktopProcess(pid, name) {
    const ok = await Modal.confirmAsync('结束进程', '确定结束进程「' + name + '」（PID ' + pid + '）以释放显存吗？\n\n注意：这会强制关闭该应用，未保存的数据可能丢失。');
    if (!ok) return;
    Toast.info('正在结束进程 ' + name + ' ...');
    try {
      const res = await API.post('/api/process/kill', { pid: parseInt(pid) });
      if (res.ok) {
        Toast.success('进程「' + name + '」已结束');
        State.set('status', null);
        if (typeof updateHeader === 'function') updateHeader();
        this._loadVram();
      } else {
        Toast.error('结束失败：' + (res.error?.message || '未知错误'));
      }
    } catch (e) {
      Toast.error('结束失败：' + e.message);
    }
  },

  _renderVramTrend() {
    const el = Utils.$('#vram-trend-chart');
    if (!el) return;
    const history = State.vramHistory;
    const width = 700, height = 200, padding = { top: 15, right: 15, bottom: 30, left: 55 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;
    const WINDOW_MS = 5 * 60 * 1000;  // 固定5分钟窗口

    if (history.length < 2) {
      el.innerHTML = '<div style="height:200px;display:flex;align-items:center;justify-content:center;color:var(--color-text-tertiary);font-size:12px">正在收集显存数据...（至少需要2个采样点）</div>';
      return;
    }

    // 只取最近5分钟内的数据点
    const now = Date.now();
    const windowStart = now - WINDOW_MS;
    const recent = history.filter(h => h.t >= windowStart);
    if (recent.length < 2) {
      el.innerHTML = '<div style="height:200px;display:flex;align-items:center;justify-content:center;color:var(--color-text-tertiary);font-size:12px">5分钟内数据不足，正在收集...</div>';
      return;
    }

    // 统计信息（基于全部历史，不只是窗口内）
    const values = history.map(h => h.used);
    const currentVal = values[values.length - 1];
    const avgVal = Math.round(values.reduce((a, b) => a + b, 0) / values.length);
    const peakVal = Math.max(...values);
    const minVal = Math.min(...values);
    const total = history[history.length - 1].total || 16384;

    // Y轴：至少为总显存，超过总显存时向上扩展到2G倍数
    const rawMax = Math.max(total, peakVal * 1.05);
    const yMax = Math.ceil(rawMax / 2048) * 2048;
    const niceTicks = [];
    for (let t = 0; t <= yMax; t += 2048) niceTicks.push(t);
    const visibleTicks = niceTicks;

    // X坐标：按实际时间戳分布（固定5分钟窗口）
    const points = recent.map(h => {
      const x = padding.left + ((h.t - windowStart) / WINDOW_MS) * chartW;
      const y = padding.top + chartH - (h.used / yMax) * chartH;
      return { x, y, ...h };
    });

    const pathD = points.map((p, i) => (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1)).join(' ');
    const areaD = pathD + ` L${points[points.length-1].x.toFixed(1)},${(padding.top + chartH).toFixed(1)} L${points[0].x.toFixed(1)},${(padding.top + chartH).toFixed(1)} Z`;

    // Y轴刻度
    const yTicks = visibleTicks.map(val => {
      const y = padding.top + chartH - (val / yMax) * chartH;
      return `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="var(--color-border-light)" stroke-width="1" stroke-dasharray="${val === 0 ? '0' : '3,3'}"/><text x="${padding.left - 8}" y="${y + 4}" text-anchor="end" fill="var(--color-text-tertiary)" font-size="10">${Utils.formatMB(val)}</text>`;
    }).join('');

    // X轴：绝对时间标签（固定5个刻度，按时间均匀分布）
    const xTickCount = 5;
    const xTicks = Array.from({ length: xTickCount }, (_, i) => {
      const tickTime = windowStart + (i / (xTickCount - 1)) * WINDOW_MS;
      const x = padding.left + (i / (xTickCount - 1)) * chartW;
      const d = new Date(tickTime);
      const label = String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0') + ':' + String(d.getSeconds()).padStart(2,'0');
      return `<text x="${x.toFixed(1)}" y="${height - 8}" text-anchor="middle" fill="var(--color-text-tertiary)" font-size="10">${label}</text>`;
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
  }
});
