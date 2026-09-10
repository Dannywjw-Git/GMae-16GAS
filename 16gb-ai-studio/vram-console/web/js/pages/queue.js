/* ============================================================
 * Pages - 任务队列页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
  async queue() {
    this._stopQueuePolling();                 // 防重入：清掉上一次轮询
    this._hiddenTaskIds = new Set();          // 重置本地视图隐藏集合
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
                <select class="form-select" id="task-model"><option>加载中...</option></select>
              </div>
              <div class="form-group">
                <label class="form-label">提示词</label>
                <textarea class="form-textarea" id="task-prompt" placeholder="输入生成提示词..."></textarea>
              </div>
              <!-- 动态参数区：根据模型 category 显示不同字段 -->
              <div id="task-dynamic-params"></div>
              <div class="mb-3" id="task-budget"><span class="badge badge--neutral">⏳ 预算检测中...</span></div>
              <button class="btn btn--primary w-full" id="btn-submit-task" disabled>提交任务</button>
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
                <div class="col-4 stat-card"><div class="stat-card__value" id="q-done">0</div><div class="stat-card__label">已完成</div></div>
              </div>
              <div id="q-current"><div class="text-tertiary">暂无运行中任务</div></div>
            </div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card__header"><div class="card__title">任务列表</div>
          <div class="card__actions"><button class="btn btn--ghost btn--sm" id="btn-clear-done">清空已完成</button></div>
        </div>
        <div class="card__body--no-padding" id="task-list"><div class="loading-overlay"><div class="spinner"></div></div>
      </div>
    `;

    // 加载模型列表（从 registry 获取，带 category 信息）
    await this._loadTaskModels();
    if (Router.current !== '/queue') return;  // 切页竞态守卫

    // 模型变化时刷新动态参数
    Utils.$('#task-model').addEventListener('change', () => this._renderDynamicParams());
    this._renderDynamicParams();

    // 预算预检（debounce）
    this._queueBudgetTimer = null;
    const checkBudget = () => {
      clearTimeout(this._queueBudgetTimer);
      this._queueBudgetTimer = setTimeout(() => this._checkTaskBudget(), 400);
    };
    ['task-prompt', 'task-width', 'task-height', 'task-steps', 'task-cfg', 'task-frames', 'task-duration', 'task-temperature', 'task-max-tokens'].forEach(id => {
      const el = Utils.$('#' + id);
      if (el) {
        el.addEventListener('input', checkBudget);
        el.addEventListener('change', checkBudget);
      }
    });
    this._checkTaskBudget();

    // 按钮事件
    Utils.$('#btn-queue-refresh').onclick = () => this._loadQueue();
    Utils.$('#btn-clear-done').onclick = () => this._clearDoneTasks();
    Utils.$('#btn-submit-task').onclick = async () => {
      const model = Utils.$('#task-model').value;
      const modelInfo = this._modelInfoMap[model] || {};
      const category = modelInfo.category || this._detectModelType(model);
      const prompt = Utils.$('#task-prompt').value;
      if (!prompt || !prompt.trim()) { Toast.warning('请输入提示词'); return; }

      // 统一参数格式：{model, params: {...}}
      const params = { prompt };
      if (category === 'image' || category === 'video') {
        params.width = parseInt(Utils.$('#task-width')?.value) || 1024;
        params.height = parseInt(Utils.$('#task-height')?.value) || 1024;
        params.steps = parseInt(Utils.$('#task-steps')?.value) || 30;
        params.cfg = parseFloat(Utils.$('#task-cfg')?.value) || 7.0;
      }
      if (category === 'video') {
        params.frames = parseInt(Utils.$('#task-frames')?.value) || 17;
      }
      if (category === 'text') {
        params.temperature = parseFloat(Utils.$('#task-temperature')?.value) || 0.7;
        params.max_tokens = parseInt(Utils.$('#task-max-tokens')?.value) || 2048;
      }
      if (category === 'audio') {
        params.duration = parseInt(Utils.$('#task-duration')?.value) || 30;
      }

      const btn = Utils.$('#btn-submit-task');
      btn.disabled = true;
      btn.textContent = '提交中...';
      const res = await API.submitTask({ model, params });
      if (res.ok) {
        Toast.success('任务已提交');
        // 预算预警：显存可能不足时提示用户
        const bw = res.budget_warning;
        if (bw) {
          setTimeout(() => Toast.warning(bw.message || '显存可能不足，任务可能排队或触发自动释放'), 500);
        }
        Utils.$('#task-prompt').value = '';
        this._startQueuePolling();
        this._loadQueue();
      } else {
        Toast.error(res.error?.message || '提交失败');
      }
      btn.disabled = false;
      btn.textContent = '提交任务';
      this._checkTaskBudget();
    };

    // 初始加载 + 启动轮询
    await this._loadQueue();
    const q = await API.getQueue();
    const hasActive = (q.tasks || q.queue || []).some(t => ['running', 'pending'].includes(t.status || t.state));
    if (hasActive) this._startQueuePolling();
  },

  /** 模型信息缓存：{modelId: {category, name, vram_gb, ...}} */
  _modelInfoMap: {},
  _hiddenTaskIds: new Set(),   // 本地隐藏的已结束任务 id（视图层）
  _lastQueueTasks: [],         // 最近一次队列快照（供清空已完成使用）
  _queuePollTimer: null,       // 队列轮询定时器

  /** 从 registry 加载模型列表（带 category，过滤 embedding） */
  async _loadTaskModels() {
    const reg = await API.getRegistry();
    const ollamaModels = reg.ollama_models || [];
    const comfyModels = reg.comfyui_models || [];
    const select = Utils.$('#task-model');
    if (!select) return;

    this._modelInfoMap = {};
    const options = [];

    // ComfyUI 模型（image/video）
    comfyModels.forEach(m => {
      const id = m.id || m.name || '';
      if (!id || m.installed === false) return;
      const category = m.category || 'image';
      this._modelInfoMap[id] = m;
      const label = m.full_name || m.name || id;
      const catLabel = category === 'video' ? '视频' : '图像';
      options.push(`<option value="${Utils.escapeHtml(id)}" data-category="${category}">${Utils.escapeHtml(label)} (${catLabel})</option>`);
    });

    // Ollama 模型（text，过滤 embedding）
    ollamaModels.forEach(m => {
      const id = m.id || m.name || '';
      if (!id || m.installed === false) return;
      const category = m.category || 'text';
      if (category === 'embedding') return; // 过滤向量化模型
      this._modelInfoMap[id] = m;
      const label = m.full_name || m.name || id;
      options.push(`<option value="${Utils.escapeHtml(id)}" data-category="${category}">${Utils.escapeHtml(label)} (对话)</option>`);
    });

    select.innerHTML = options.length > 0
      ? options.join('')
      : '<option value="">未检测到生成模型</option>';
  },

  /** 从模型信息获取 category（优先用 registry 数据，兜底用关键词） */
  _getModelCategory(modelName) {
    const info = this._modelInfoMap[modelName];
    if (info?.category) return info.category;
    // 兜底：关键词匹配（仅当 registry 无 category 时）
    return this._detectModelType(modelName);
  },

  /** 兜底关键词匹配（registry 无 category 时使用） */
  _detectModelType(modelName) {
    const name = (modelName || '').toLowerCase();
    if (/wan|video|cogvideo|hunyuan|hailuo/.test(name)) return 'video';
    if (/music|ace|audio|suno|udio/.test(name)) return 'audio';
    if (/qwen|llama|mistral|gemma|phi|deepseek|glm|yi|chat|instruct/.test(name)) return 'text';
    return 'image';
  },

  /** 根据模型 category 渲染动态参数区 */
  _renderDynamicParams() {
    const model = Utils.$('#task-model')?.value || '';
    const category = this._getModelCategory(model);
    const container = Utils.$('#task-dynamic-params');
    if (!container) return;
    const typeLabels = { image: '图像生成', video: '视频生成', text: '对话生成', audio: '音乐生成' };
    let html = `<div class="text-tertiary mb-2" style="font-size:11px">模型类型：${typeLabels[category] || category}</div>`;

    if (category === 'image' || category === 'video') {
      html += `
        <div class="form-row">
          <div class="form-group"><label class="form-label">宽度</label><input class="form-input" id="task-width" type="number" value="${category === 'video' ? 832 : 1024}"></div>
          <div class="form-group"><label class="form-label">高度</label><input class="form-input" id="task-height" type="number" value="${category === 'video' ? 480 : 1024}"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">步数</label><input class="form-input" id="task-steps" type="number" value="${category === 'video' ? 20 : 30}"></div>
          <div class="form-group"><label class="form-label">CFG</label><input class="form-input" id="task-cfg" type="number" value="7.0" step="0.5"></div>
        </div>
      `;
    }
    if (category === 'video') {
      html += `<div class="form-row"><div class="form-group"><label class="form-label">帧数</label><input class="form-input" id="task-frames" type="number" value="17"></div></div>`;
    }
    if (category === 'text') {
      html += `
        <div class="form-row">
          <div class="form-group"><label class="form-label">温度</label><input class="form-input" id="task-temperature" type="number" value="0.7" step="0.1" min="0" max="2"></div>
          <div class="form-group"><label class="form-label">最大 Token</label><input class="form-input" id="task-max-tokens" type="number" value="2048"></div>
        </div>
      `;
    }
    if (category === 'audio') {
      html += `<div class="form-row"><div class="form-group"><label class="form-label">时长（秒）</label><input class="form-input" id="task-duration" type="number" value="30" min="5" max="120"></div></div>`;
    }
    container.innerHTML = html;

    // 重新绑定预算预检事件
    const checkBudget = () => {
      clearTimeout(this._queueBudgetTimer);
      this._queueBudgetTimer = setTimeout(() => this._checkTaskBudget(), 400);
    };
    ['task-width', 'task-height', 'task-steps', 'task-cfg', 'task-frames', 'task-duration', 'task-temperature', 'task-max-tokens'].forEach(id => {
      const el = Utils.$('#' + id);
      if (el) {
        el.addEventListener('input', checkBudget);
        el.addEventListener('change', checkBudget);
      }
    });
  },

  /** 预算预检（后端格式：{action, args: {model, params: {...}}}） */
  async _checkTaskBudget() {
    const badge = Utils.$('#task-budget');
    const submitBtn = Utils.$('#btn-submit-task');
    if (!badge || !submitBtn) return;
    const model = Utils.$('#task-model')?.value;
    if (!model) { badge.innerHTML = '<span class="badge badge--neutral">请选择模型</span>'; submitBtn.disabled = true; return; }
    badge.innerHTML = '<span class="badge badge--neutral">⏳ 检测中...</span>';
    try {
      const category = this._getModelCategory(model);
      // 统一参数格式
      const params = { prompt: Utils.$('#task-prompt')?.value || '' };
      if (category === 'image' || category === 'video') {
        params.width = parseInt(Utils.$('#task-width')?.value) || 1024;
        params.height = parseInt(Utils.$('#task-height')?.value) || 1024;
        params.steps = parseInt(Utils.$('#task-steps')?.value) || 30;
        params.cfg = parseFloat(Utils.$('#task-cfg')?.value) || 7.0;
      }
      if (category === 'video') {
        params.frames = parseInt(Utils.$('#task-frames')?.value) || 17;
      }
      if (category === 'text') {
        params.temperature = parseFloat(Utils.$('#task-temperature')?.value) || 0.7;
        params.max_tokens = parseInt(Utils.$('#task-max-tokens')?.value) || 2048;
      }
      if (category === 'audio') {
        params.duration = parseInt(Utils.$('#task-duration')?.value) || 30;
      }

      // 后端 admission 需要 {action, args: {model, params}}
      const res = await API.checkAdmission({ action: 'submit_task', args: { model, params } });
      const allowed = res.allowed ?? false;
      const reason = res.reason || res.error?.message || '';
      if (allowed) {
        const needGb = res.required_free_gb || res.checks?.budget?.required_free_gb || '?';
        const detail = res.checks?.budget?.detail || '';
        badge.innerHTML = `<span class="badge badge--success">✅ 显存充足${needGb !== '?' ? `（需保留 ${needGb}GB）` : ''}</span>`;
        submitBtn.disabled = false;
      } else {
        badge.innerHTML = `<span class="badge badge--danger">❌ ${Utils.escapeHtml(reason || '显存不足')}</span>`;
        submitBtn.disabled = true;
      }
    } catch (e) {
      badge.innerHTML = '<span class="badge badge--neutral">⚠️ 预算检测不可用</span>';
      submitBtn.disabled = false;
    }
  },

  /** 加载队列：统计 + 当前运行 + 任务列表。
   *  后端真实字段：status = queued/precheck/freeing/running/done/failed/canceled；
   *  progress 为字符串；created 为秒级时间戳；snapshot 返回 {tasks, queue, worker_alive}。 */
  async _loadQueue() {
    let res;
    try {
      res = await API.getQueue();
    } catch (e) {
      const errList = Utils.$('#task-list');
      if (errList) errList.innerHTML = '<div class="empty-state"><div class="empty-state__title">队列接口不可用</div></div>';
      return;
    }
    const all = res.tasks || res.queue || [];
    this._lastQueueTasks = all;
    const visible = all.filter(t => !this._hiddenTaskIds.has(t.id || t.task_id));
    const STATUS_ACTIVE = ['queued', 'precheck', 'freeing', 'running'];
    const STATUS_DONE = ['done', 'completed', 'failed', 'canceled'];
    const st = t => t.status || t.state || '';
    const running = visible.filter(t => ['precheck', 'freeing', 'running'].includes(st(t))).length;
    const waiting = visible.filter(t => st(t) === 'queued').length;
    const doneCnt = visible.filter(t => STATUS_DONE.includes(st(t))).length;
    const setText = (id, v) => { const el = Utils.$('#' + id); if (el) el.textContent = v; };
    setText('q-running', running);
    setText('q-waiting', waiting);
    setText('q-done', doneCnt);

    // 当前运行任务
    const current = visible.filter(t => ['precheck', 'freeing', 'running'].includes(st(t)));
    const curEl = Utils.$('#q-current');
    if (curEl) {
      curEl.innerHTML = current.length ? current.map(t => `
        <div class="flex items-center justify-between" style="padding:8px;background:var(--color-bg-2);border-radius:6px;margin-bottom:6px">
          <span class="text-mono" style="font-size:12px;font-weight:600">${Utils.escapeHtml(t.model || '')}</span>
          <span class="badge badge--info">${Utils.escapeHtml(st(t))}${t.progress ? ' · ' + Utils.escapeHtml(t.progress) : ''}</span>
        </div>`).join('') : '<div class="text-tertiary">暂无运行中任务</div>';
    }

    // 任务列表（DOM 不存在说明已切走页面，停止轮询自愈）
    const list = Utils.$('#task-list');
    if (!list) { this._stopQueuePolling(); return; }
    const badgeCls = x => ({ running: 'info', precheck: 'info', freeing: 'info', queued: 'neutral', done: 'success', completed: 'success', failed: 'danger', canceled: 'neutral' }[x] || 'neutral');
    list.innerHTML = visible.length ? `
      <table class="table">
        <thead><tr><th>#</th><th>模型</th><th>状态</th><th>进度/信息</th><th>提交时间</th><th>操作</th></tr></thead>
        <tbody>
          ${visible.map((t, i) => {
            const id = t.id || t.task_id;
            const ts = t.created || t.submitted_at || t.created_at;
            const timeStr = ts ? (typeof ts === 'number' ? new Date(ts * 1000).toLocaleString() : Utils.formatTime(ts)) : '—';
            const info = t.progress || (t.error ? t.error : '');
            return `
            <tr>
              <td class="text-mono">${String(i + 1).padStart(3, '0')}</td>
              <td>${Utils.escapeHtml(t.model || t.workflow || '')}</td>
              <td><span class="badge badge--${badgeCls(st(t))}">${Utils.escapeHtml(st(t) || '未知')}</span></td>
              <td style="font-size:11px">${Utils.escapeHtml(info) || '—'}</td>
              <td class="text-mono" style="font-size:11px">${timeStr}</td>
              <td class="table__actions">${STATUS_ACTIVE.includes(st(t)) ? `<button class="btn btn--ghost btn--sm" onclick="Pages._cancelTask('${id}')">取消</button>` : '—'}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>` : '<div class="empty-state"><div class="empty-state__icon">' + (Icons.list || '') + '</div><div class="empty-state__title">暂无任务</div><div class="empty-state__desc">提交一个生成任务开始使用</div></div>';
  },

  /** 取消任务（queued 立即取消；运行中标记请求取消） */
  async _cancelTask(id) {
    Modal.confirm({
      title: '取消任务', message: '确认取消该任务？', confirmText: '取消任务', danger: true,
      onConfirm: async () => {
        const res = await API.cancelTask({ task_id: id });
        if (res.ok) { Toast.success('任务已取消'); this._loadQueue(); }
        else Toast.error(res.error?.message || '取消失败');
      },
    });
  },

  /** 清空已结束任务：后端暂无清理接口，先从当前视图隐藏（重新进入页面会重置） */
  _clearDoneTasks() {
    let n = 0;
    this._lastQueueTasks.forEach(t => {
      if (['done', 'completed', 'failed', 'canceled'].includes(t.status || t.state)) {
        this._hiddenTaskIds.add(t.id || t.task_id); n++;
      }
    });
    if (!n) { Toast.info('没有已结束的任务'); return; }
    Toast.success('已隐藏 ' + n + ' 个已结束任务');
    this._loadQueue();
  },

  /** 启动队列轮询（幂等：先清旧定时器；切页后 DOM 消失自动停止） */
  _startQueuePolling() {
    this._stopQueuePolling();
    this._queuePollTimer = setInterval(() => {
      if (!Utils.$('#task-list')) { this._stopQueuePolling(); return; }
      this._loadQueue();
    }, 3000);
  },

  _stopQueuePolling() {
    if (this._queuePollTimer) { clearInterval(this._queuePollTimer); this._queuePollTimer = null; }
  }
});
