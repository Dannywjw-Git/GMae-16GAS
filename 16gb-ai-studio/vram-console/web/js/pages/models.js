/* ============================================================
 * Pages - 模型登记台页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
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
          <select class="form-select" id="model-category" style="width:120px"><option value="">全部</option><option value="image">图像</option><option value="video">视频</option><option value="text">对话</option><option value="embedding">向量化</option><option value="audio">音频</option></select>
        </div>
        <div class="filter-bar__item"><span class="filter-bar__label">来源</span>
          <select class="form-select" id="model-source" style="width:120px"><option value="">全部</option><option value="ollama">Ollama</option><option value="comfyui">ComfyUI</option></select>
        </div>
        <div class="filter-bar__item"><span class="filter-bar__label">状态</span>
          <select class="form-select" id="model-status" style="width:120px"><option value="">全部</option><option value="loaded">运行中</option><option value="installed">已安装</option><option value="not_installed">未安装</option></select>
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
    ['model-category', 'model-source', 'model-status', 'model-search'].forEach(id => {
      const el = Utils.$('#' + id);
      if (el) el.addEventListener('input', () => this._filterModels());
      if (el) el.addEventListener('change', () => this._filterModels());
    });
    this._loadModels();
  },

  _allModels: [],
  _loadedModels: [],
  _gpuProcesses: [],

  async _loadModels() {
    const [reg, status] = await Promise.all([API.getRegistry(), API.getStatus()]);
    if (Router.current !== '/models') return;  // 切页竞态守卫
    // 获取 GPU 进程，用于推断 ComfyUI 模型加载状态
    this._gpuProcesses = status.gpu_processes?.processes || [];
    const comfyProcessNames = this._gpuProcesses
      .filter(p => (p.used_mb || 0) > 500)
      .map(p => (p.name || '').toLowerCase());
    const hasComfyRunning = comfyProcessNames.some(n => n.includes('comfy') || n.includes('python'));

    // 获取已加载模型列表（含实际显存占用）
    this._loadedModels = reg.loaded_models || [];
    const loadedNames = new Set(this._loadedModels.map(m => m.name));
    const loadedVramMap = {};
    this._loadedModels.forEach(m => { loadedVramMap[m.name] = m.size_gb || 0; });

    // Ollama 模型
    const ollamaModels = (reg.ollama_models || []).map(m => {
      const id = m.id || m.name || '';
      const isLoaded = loadedNames.has(id);
      return {
        ...m,
        source: 'ollama',
        vram_mb: isLoaded ? Math.round((loadedVramMap[id] || 0) * 1024) : Math.round((m.vram_gb || 0) * 1024),
        loaded: isLoaded,
        installed: m.installed || false,
        actual_vram_gb: isLoaded ? (loadedVramMap[id] || 0) : null,
      };
    });

    // ComfyUI 模型：如果有 ComfyUI 进程在运行且占用显存，标记为已加载
    const comfyModels = (reg.comfyui_models || []).map(m => {
      const id = m.id || m.name || '';
      // ComfyUI 是单进程多模型，无法精确判断哪个模型加载，用进程存在推断
      const isLoaded = hasComfyRunning && m.installed;
      return {
        ...m,
        source: 'comfyui',
        vram_mb: Math.round((m.vram_gb || 0) * 1024),
        loaded: isLoaded,
        installed: m.installed || false,
        actual_vram_gb: isLoaded ? (m.vram_gb || null) : null,
      };
    });

    this._allModels = [...ollamaModels, ...comfyModels];
    const loadedCount = this._allModels.filter(m => m.loaded).length;
    const loadedVram = reg.loaded_vram_gb || status.gpu?.used_gb || 0;
    Utils.$('#model-subtitle').textContent = `已登记 ${this._allModels.length} 个模型（Ollama ${ollamaModels.length} · ComfyUI ${comfyModels.length}）· 运行中 ${loadedCount} 个 · 占用 ${loadedVram}GB`;
    this._filterModels();
  },

  _filterModels() {
    const cat = Utils.$('#model-category')?.value || '';
    const src = Utils.$('#model-source')?.value || '';
    const st = Utils.$('#model-status')?.value || '';
    const q = (Utils.$('#model-search')?.value || '').toLowerCase();
    const filtered = this._allModels.filter(m => {
      if (cat && (m.category || '') !== cat) return false;
      if (src && (m.source || '') !== src) return false;
      if (st === 'loaded' && !m.loaded) return false;
      if (st === 'installed' && (!m.installed || m.loaded)) return false;
      if (st === 'not_installed' && m.installed) return false;
      if (q && !(m.name || m.id || '').toLowerCase().includes(q)) return false;
      return true;
    });
    const grid = Utils.$('#models-grid');
    if (!grid) return;
    grid.innerHTML = filtered.length > 0 ? filtered.map((m, idx) => {
      const modelName = m.id || m.model || m.name || '';
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
      const categoryLabel = { image: '图像', video: '视频', text: '对话', embedding: '向量化', audio: '音频' }[m.category] || m.category || '未知';
      return `
      <div class="col-3 model-card ${isLoaded ? 'model-card--loaded' : ''}">
        <div class="model-card__header">
          <span class="model-card__icon">${Icons.box}</span>
          <span class="model-card__name" title="${Utils.escapeHtml(modelName)}">${Utils.escapeHtml(modelName)}</span>
        </div>
        <div class="model-card__tags">
          <span class="badge badge--neutral">${categoryLabel}</span>
          <span class="badge badge--neutral">${Utils.escapeHtml(m.source || '')}</span>
          ${statusBadge}
          ${m.exclusive ? '<span class="badge badge--warning">独占</span>' : ''}
        </div>
        <div class="model-card__specs">
          <span>${vramText}</span>
          ${m.quantization ? `<span>量化: ${Utils.escapeHtml(m.quantization)}</span>` : ''}
        </div>
        <div class="model-card__actions">
          <button class="btn btn--ghost btn--sm" onclick="Pages._showModelDetail(${idx})">详情</button>
          ${actionBtn}
        </div>
      </div>`;
    }).join('') : '<div class="empty-state col-12"><div class="empty-state__icon">'+Icons.box+'</div><div class="empty-state__title">暂无匹配模型</div><div class="empty-state__desc">调整筛选条件或扫描新模型</div></div>';
  },

  /** 模型详情弹窗 */
  _showModelDetail(index) {
    const m = this._allModels[index];
    if (!m) return;
    const modelName = m.id || m.name || '';
    const categoryLabel = { image: '图像生成', video: '视频生成', text: '对话推理', embedding: '向量化', audio: '音频生成' }[m.category] || m.category || '未知';
    const fields = [
      ['模型ID', modelName],
      ['显示名称', m.full_name || m.name || '—'],
      ['类别', categoryLabel],
      ['来源', m.source === 'ollama' ? 'Ollama' : 'ComfyUI'],
      ['状态', m.loaded ? '运行中' : (m.installed ? '已安装' : '未安装')],
      ['预估显存', `${m.vram_gb || (m.vram_mb / 1024).toFixed(1)} GB`],
      ['实际占用', m.actual_vram_gb ? `${m.actual_vram_gb.toFixed(1)} GB` : '—'],
      ['是否独占', m.exclusive ? '是（全卡独占）' : '否（共享显存）'],
      ['量化方式', m.quantization || '—'],
      ['参数规模', m.params || '—'],
      ['支持的分辨率', m.resolutions ? m.resolutions.join(', ') : '—'],
      ['备注', m.note || m.description || '—'],
    ];
    Modal.open({
      title: `模型详情 - ${Utils.escapeHtml(modelName)}`,
      size: 'md',
      content: `
        <table class="table" style="margin:0">
          <tbody>
            ${fields.map(([k, v]) => `<tr><td style="width:120px;font-weight:600;color:var(--color-text-secondary)">${k}</td><td>${Utils.escapeHtml(String(v))}</td></tr>`).join('')}
          </tbody>
        </table>
      `,
      footer: `<button class="btn btn--secondary" data-action="close">关闭</button>`,
    });
    Modal.modal.querySelector('[data-action="close"]').onclick = () => Modal.close();
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
          await new Promise(r => setTimeout(r, 3000));
          State.set('status', null);
          const statusRes = await API.getStatus();
          const status = statusRes;
          State.set('status', status);
          if (typeof updateHeader === 'function') updateHeader();
          this._loadModels();
          const afterUsed = status.gpu?.used_mb || 0;
          const freed = Math.max(0, beforeUsed - afterUsed);
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
  }
});
