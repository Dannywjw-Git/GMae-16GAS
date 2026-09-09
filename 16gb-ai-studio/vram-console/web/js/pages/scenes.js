/* ============================================================
 * Pages - 场景切换页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
  async scenes() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">场景切换
          <div class="page-header__actions"><button class="btn btn--secondary btn--sm" id="btn-scene-refresh">${Icons.refresh} 刷新</button></div>
        </div>
        <div class="page-header__subtitle">预设场景一键切换，自动启停对应服务</div>
      </div>
      <div id="scene-current" class="card mb-4"><div class="card__body"><div class="loading-overlay"><div class="spinner"></div></div></div></div>
      <div class="grid" id="scene-grid"><div class="loading-overlay"><div class="spinner"></div></div></div>
    `;
    Utils.$('#btn-scene-refresh').onclick = () => this._loadScenes();
    await this._loadScenes();
  },

  /** 场景图标映射 */
  _sceneIcons: {
    dialogue: '💬', comfy: '🎨', h3: '🎥', fooocus: '✨', music: '🎵', game: '🎮', idle: '😴',
  },

  async _loadScenes() {
    const [reg, status] = await Promise.all([API.getSceneList(), API.getScenes()]);
    if (Router.current !== '/scenes') return;  // 切页竞态守卫
    const scenes = reg.scenes || {};
    const current = status.current || status.scene || 'unknown';
    const sceneIds = Object.keys(scenes);

    // 当前场景卡片
    const currentScene = scenes[current] || { label: current, vram_budget_gb: '?', containers: [], steps: [] };
    const currentEl = Utils.$('#scene-current');
    currentEl.innerHTML = `
      <div class="card__body">
        <div class="flex items-center gap-4 flex-wrap">
          <div style="font-size:36px">${this._sceneIcons[current] || '🔄'}</div>
          <div>
            <div class="text-secondary" style="font-size:12px">当前场景</div>
            <div style="font-size:24px;font-weight:700">${Utils.escapeHtml(currentScene.label || current)}</div>
            <div class="text-tertiary" style="font-size:12px">显存预算 ${currentScene.vram_budget_gb || '?'}GB · ${(currentScene.containers || []).length} 个服务 · ${(currentScene.steps || []).length} 步切换</div>
          </div>
          <div class="flex items-center gap-2 ml-auto">
            <span class="status-dot status-dot--online status-dot--pulse"></span>
            <span class="text-secondary">运行中</span>
          </div>
        </div>
      </div>
    `;

    // 场景卡片网格
    const grid = Utils.$('#scene-grid');
    if (sceneIds.length === 0) {
      grid.innerHTML = '<div class="empty-state"><div class="empty-state__icon">'+Icons.layers+'</div><div class="empty-state__title">未配置场景</div><div class="empty-state__desc">请在 registry.json 中配置场景</div></div>';
      return;
    }
    grid.innerHTML = `<div class="grid">${sceneIds.map(id => {
      const s = scenes[id];
      const isCurrent = id === current;
      const services = (s.containers || []).join(', ') || '无';
      const steps = s.steps || [];
      return `
        <div class="col-4 scene-card ${isCurrent ? 'scene-card--current' : ''}" data-scene="${id}">
          <div class="scene-card__header">
            <span style="font-size:28px">${this._sceneIcons[id] || '🔄'}</span>
            <div class="scene-card__name">${Utils.escapeHtml(s.label || id)}</div>
          </div>
          <div class="scene-card__services">${Utils.escapeHtml(services)}</div>
          <div class="scene-card__vram">${Icons.cpu} 显存预算: ${s.vram_budget_gb || '?'}GB</div>
          <div class="scene-card__desc">${steps.length} 步切换 · ${s.exclusive ? '独占全卡' : '共享显存'}</div>
          <button class="btn ${isCurrent ? 'btn--success' : 'btn--primary'} w-full scene-switch-btn" data-scene="${id}" ${isCurrent ? 'disabled' : ''}>
            ${isCurrent ? '当前场景' : '切换'}
          </button>
        </div>
      `;
    }).join('')}</div>`;

    // 绑定切换按钮
    grid.querySelectorAll('.scene-switch-btn').forEach(btn => {
      btn.onclick = () => {
        const sceneId = btn.dataset.scene;
        const scene = scenes[sceneId];
        this._switchSceneWithProgress(sceneId, scene);
      };
    });
  },

  /** 带进度弹窗的场景切换 */
  async _switchSceneWithProgress(sceneId, scene) {
    const steps = scene?.steps || [];
    const sceneLabel = scene?.label || sceneId;

    // 确认弹窗
    const confirmed = await Modal.confirmAsync('切换场景', `切换到「${sceneLabel}」将停止当前服务并执行 ${steps.length} 步操作，确认？`, { confirmText: '开始切换', danger: false });
    if (!confirmed) return;

    // 进度弹窗
    const stepsHtml = steps.map((step, i) => `
      <div class="scene-step" id="scene-step-${i}" data-status="pending">
        <div class="scene-step__icon">⏳</div>
        <div class="scene-step__label">${Utils.escapeHtml(step.label || `步骤 ${i+1}`)}</div>
        <div class="scene-step__status text-tertiary">等待中</div>
      </div>
    `).join('');

    Modal.open({
      title: `切换到 ${sceneLabel}`,
      size: 'md',
      content: `
        <div class="mb-3">
          <div class="progress"><div class="progress__fill" id="scene-progress-fill" style="width:0%"></div></div>
          <div class="text-tertiary mt-1" style="font-size:12px" id="scene-progress-text">准备中...</div>
        </div>
        <div class="scene-steps">${stepsHtml || '<div class="text-tertiary">无具体步骤</div>'}</div>
      `,
      footer: `<button class="btn btn--secondary" id="scene-switch-close" disabled>后台运行</button>`,
    });

    // 禁用关闭按钮直到完成
    const closeBtn = Modal.modal.querySelector('#scene-switch-close');
    if (closeBtn) closeBtn.onclick = () => Modal.close();

    // 调用后端切换
    const switchPromise = API.switchScene({ scene: sceneId });

    // 前端模拟进度（每步等待预估时间）
    const totalSteps = steps.length || 1;
    for (let i = 0; i < steps.length; i++) {
      const stepEl = Modal.modal.querySelector(`#scene-step-${i}`);
      if (stepEl) {
        stepEl.dataset.status = 'running';
        stepEl.querySelector('.scene-step__icon').textContent = '⚙️';
        stepEl.querySelector('.scene-step__status').textContent = '执行中...';
        stepEl.querySelector('.scene-step__status').className = 'scene-step__status text-brand';
      }
      const progress = Math.round(((i + 0.5) / totalSteps) * 100);
      const fill = Modal.modal.querySelector('#scene-progress-fill');
      const text = Modal.modal.querySelector('#scene-progress-text');
      if (fill) fill.style.width = progress + '%';
      if (text) text.textContent = `正在执行：${steps[i].label || `步骤 ${i+1}`}（${progress}%）`;
      // 等待预估时间（critical步骤等久一点）
      await new Promise(r => setTimeout(r, steps[i].critical ? 2000 : 1200));
      if (stepEl) {
        stepEl.dataset.status = 'done';
        stepEl.querySelector('.scene-step__icon').textContent = '✅';
        stepEl.querySelector('.scene-step__status').textContent = '完成';
        stepEl.querySelector('.scene-step__status').className = 'scene-step__status text-success';
      }
    }

    // 等待后端切换完成
    try {
      const res = await switchPromise;
      const fill = Modal.modal.querySelector('#scene-progress-fill');
      const text = Modal.modal.querySelector('#scene-progress-text');
      if (fill) fill.style.width = '100%';
      if (res.ok) {
        if (text) text.textContent = '切换完成！';
        // 标记所有步骤完成
        for (let i = 0; i < steps.length; i++) {
          const stepEl = Modal.modal.querySelector(`#scene-step-${i}`);
          if (stepEl && stepEl.dataset.status !== 'done') {
            stepEl.dataset.status = 'done';
            stepEl.querySelector('.scene-step__icon').textContent = '✅';
            stepEl.querySelector('.scene-step__status').textContent = '完成';
          }
        }
        Toast.success(`已切换到「${sceneLabel}」`);
      } else {
        if (text) text.textContent = `切换失败：${res.error?.message || '未知错误'}`;
        Toast.error(`切换失败：${res.error?.message || '未知错误'}`);
      }
    } catch (e) {
      const text = Modal.modal.querySelector('#scene-progress-text');
      if (text) text.textContent = `切换异常：${e.message}`;
      Toast.error(`切换异常：${e.message}`);
    }

    // 启用关闭按钮
    if (closeBtn) {
      closeBtn.disabled = false;
      closeBtn.textContent = '关闭';
    }

    // 刷新场景状态
    setTimeout(() => this._loadScenes(), 1000);
  }
});
