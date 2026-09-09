/* ============================================================
 * Pages - 设置页
 * 从 pages.js 拆分，通过 Object.assign 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

Object.assign(Pages, {
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
        <div class="settings-content" id="settings-content">
          <div class="text-tertiary text-center" style="padding:40px">加载中...</div>
        </div>
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

  /** 服务元信息映射（容器名 -> 显示名/端口，固定配置） */
  _serviceMeta: {
    ollama: { name: 'Ollama', port: 11434 },
    comfyui: { name: 'ComfyUI', port: 8188 },
    'open-webui': { name: 'Open WebUI', port: 3000 },
    fooocus: { name: 'Fooocus', port: 7865 },
    immich: { name: 'Immich', port: 2283 },
    searxng: { name: 'SearXNG', port: 8888 },
  },

  async _renderSettingsSection(section) {
    const el = Utils.$('#settings-content');
    if (!el) return;
    el.innerHTML = '<div class="text-tertiary text-center" style="padding:40px">加载中...</div>';

    switch (section) {
      case 'system': await this._renderSettingsSystem(el); break;
      case 'services': await this._renderSettingsServices(el); break;
      case 'qos': await this._renderSettingsQos(el); break;
      case 'autoprotect': await this._renderSettingsAutoProtect(el); break;
      case 'account': this._renderSettingsAccount(el); break;
      case 'watchdog': await this._renderSettingsWatchdog(el); break;
      case 'about': await this._renderSettingsAbout(el); break;
      default: el.innerHTML = '<div class="text-tertiary">该功能开发中</div>';
    }
  },

  async _renderSettingsSystem(el) {
    const [status, hardware] = await Promise.all([API.getStatus(), API.getHardware()]);
    if (!el || !document.contains(el)) return;  // 切页竞态守卫：容器已脱离文档则中止
    const profile = hardware?.profile || {};
    const gpu = profile.gpus?.[0] || status?.gpu || {};
    const thresholds = hardware?.thresholds || {};
    const gpuName = gpu.name || '未知';
    const totalGb = (gpu.vram_total_mb || status?.gpu?.total_mb || 16384) / 1024;
    const driver = gpu.driver_version || '-';
    const cuda = gpu.cuda_version || '-';
    const noiseGb = (profile.base_noise_mb || 0) / 1024;
    const osType = profile.os_type || 'Windows';
    const dockerOk = profile.docker_available ? '✅ 可用' : '❌ 不可用';
    const ramGb = profile.ram_total_mb > 0 ? (profile.ram_total_mb / 1024).toFixed(1) + ' GB' : '未检测';

    el.innerHTML = `
      <div class="card mb-4">
        <div class="card__header"><div class="card__title">系统配置</div></div>
        <div class="card__body">
          <div class="form-row">
            <div class="form-group"><label class="form-label">服务端口</label><input class="form-input" id="cfg-port" value="8787" disabled><div class="text-tertiary" style="font-size:11px;margin-top:4px">修改需重启生效</div></div>
            <div class="form-group"><label class="form-label">监听地址</label><select class="form-select" id="cfg-host" disabled><option selected>0.0.0.0</option><option>127.0.0.1</option></select><div class="text-tertiary" style="font-size:11px;margin-top:4px">修改需重启生效</div></div>
          </div>
          <div class="form-row">
            <div class="form-group"><label class="form-label">日志级别</label><select class="form-select" id="cfg-log-level"><option value="info" selected>info</option><option value="debug">debug</option><option value="warning">warning</option><option value="error">error</option></select></div>
            <div class="form-group"><label class="form-label">状态缓存 TTL</label><input class="form-input" id="cfg-cache-ttl" value="10 秒"><div class="text-tertiary" style="font-size:11px;margin-top:4px">运行时配置保存待后端支持</div></div>
          </div>
          <div class="flex gap-2 mt-4">
            <button class="btn btn--primary" id="btn-save-system">保存更改</button>
            <button class="btn btn--secondary" id="btn-reset-system">恢复默认</button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card__header"><div class="card__title">硬件信息</div><div class="text-tertiary" style="font-size:12px">检测于 ${profile.detected_at ? new Date(profile.detected_at * 1000).toLocaleString() : '-'}</div></div>
        <div class="card__body">
          <div class="grid">
            <div class="col-6">
              <div class="form-group"><label class="form-label">GPU 型号</label><input class="form-input" value="${Utils.escapeHtml(gpuName)}" disabled></div>
            </div>
            <div class="col-6">
              <div class="form-group"><label class="form-label">显存总量</label><input class="form-input" value="${totalGb.toFixed(1)} GB" disabled></div>
            </div>
          </div>
          <div class="grid">
            <div class="col-6">
              <div class="form-group"><label class="form-label">驱动版本</label><input class="form-input" value="${Utils.escapeHtml(driver)}" disabled></div>
            </div>
            <div class="col-6">
              <div class="form-group"><label class="form-label">CUDA 版本</label><input class="form-input" value="${Utils.escapeHtml(cuda)}" disabled></div>
            </div>
          </div>
          <div class="grid">
            <div class="col-4">
              <div class="form-group"><label class="form-label">基础噪声</label><input class="form-input" value="${noiseGb.toFixed(2)} GB" disabled><div class="text-tertiary" style="font-size:11px;margin-top:4px">系统+桌面占用</div></div>
            </div>
            <div class="col-4">
              <div class="form-group"><label class="form-label">系统内存</label><input class="form-input" value="${Utils.escapeHtml(ramGb)}" disabled></div>
            </div>
            <div class="col-4">
              <div class="form-group"><label class="form-label">操作系统</label><input class="form-input" value="${Utils.escapeHtml(osType)}" disabled></div>
            </div>
          </div>
          <div class="grid">
            <div class="col-4">
              <div class="form-group"><label class="form-label">Docker</label><input class="form-input" value="${dockerOk}" disabled></div>
            </div>
            <div class="col-4">
              <div class="form-group"><label class="form-label">GREEN 阈值</label><input class="form-input" value="${thresholds.green_gb || thresholds.green || '-'} GB" disabled></div>
            </div>
            <div class="col-4">
              <div class="form-group"><label class="form-label">RED 阈值</label><input class="form-input" value="${thresholds.red_gb || thresholds.red || '-'} GB" disabled></div>
            </div>
          </div>
        </div>
      </div>
    `;
    Utils.$('#btn-save-system').onclick = () => {
      Toast.show('运行时配置保存功能待后端支持，当前修改仅前端生效', 'info');
    };
    Utils.$('#btn-reset-system').onclick = () => {
      Modal.confirm('恢复默认配置', '确定要恢复所有系统配置为默认值吗？', () => {
        Utils.$('#cfg-log-level').value = 'info';
        Utils.$('#cfg-cache-ttl').value = '10 秒';
        Toast.show('已恢复默认值', 'success');
      });
    };
  },

  async _renderSettingsServices(el) {
    const status = await API.getStatus();
    if (!el || !document.contains(el)) return;  // 切页竞态守卫：容器已脱离文档则中止
    const runningNames = new Set(status?.containers?.all || []);
    const allNames = new Set([...Object.keys(this._serviceMeta), ...runningNames]);
    const services = Array.from(allNames).map(container => {
      const meta = this._serviceMeta[container] || { name: container, port: '-' };
      return { container, name: meta.name, port: meta.port, running: runningNames.has(container) };
    });
    const runningCount = services.filter(s => s.running).length;
    el.innerHTML = `
      <div class="card">
        <div class="card__header"><div class="card__title">服务管理</div><div class="text-tertiary" style="font-size:12px">运行中 ${runningCount} / ${services.length}</div></div>
        <div class="card__body--no-padding">
          <table class="table">
            <thead><tr><th>服务</th><th>容器</th><th>状态</th><th>端口</th><th>操作</th></tr></thead>
            <tbody>
              ${services.map(s => `
                <tr>
                  <td>${Utils.escapeHtml(s.name)}</td>
                  <td class="text-mono">${Utils.escapeHtml(s.container)}</td>
                  <td><span class="status-dot ${s.running ? 'status-dot--online' : 'status-dot--offline'}"></span> ${s.running ? '运行中' : '已停止'}</td>
                  <td class="text-mono">${s.port}</td>
                  <td class="table__actions">
                    ${s.running
                      ? `<button class="btn btn--ghost btn--sm" data-action="restart" data-container="${s.container}">重启</button>
                         <button class="btn btn--ghost btn--sm btn--danger" data-action="stop" data-container="${s.container}">停止</button>`
                      : `<button class="btn btn--ghost btn--sm" data-action="start" data-container="${s.container}">启动</button>`
                    }
                  </td>
                </tr>
              `).join('') || '<tr><td colspan="5" class="text-center text-tertiary">暂无服务</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    `;
    el.querySelectorAll('button[data-action]').forEach(btn => {
      btn.onclick = async () => {
        const action = btn.dataset.action;
        const container = btn.dataset.container;
        const actionLabel = { start: '启动', stop: '停止', restart: '重启' }[action];
        if (action === 'stop') {
          const ok = await Modal.confirmAsync(`${actionLabel}服务`, `确定要${actionLabel}「${container}」吗？`);
          if (!ok) return;
        }
        btn.disabled = true;
        btn.textContent = '处理中...';
        try {
          const res = await API.serviceAction({ service: container, action });
          if (res.ok) {
            Toast.show(`服务「${container}」${actionLabel}成功`, 'success');
            setTimeout(() => this._renderSettingsServices(el), 2000);
          } else {
            Toast.show(`${actionLabel}失败：${res?.error?.message || '未知错误'}`, 'error');
            btn.disabled = false;
            btn.textContent = actionLabel;
          }
        } catch (e) {
          Toast.show(`${actionLabel}失败：${e.message}`, 'error');
          btn.disabled = false;
          btn.textContent = actionLabel;
        }
      };
    });
  },

  async _renderSettingsQos(el) {
    const qos = await API.getQosStatus();
    if (!el || !document.contains(el)) return;  // 切页竞态守卫：容器已脱离文档则中止
    const level = qos?.level || 'ok';
    const thresholds = qos?.thresholds || { green: 8, yellow: 4, red: 2 };
    const autoDegrade = qos?.auto_degrade || false;
    el.innerHTML = `
      <div class="card">
        <div class="card__header"><div class="card__title">QoS 配置</div><div class="text-tertiary" style="font-size:12px">当前等级：${level.toUpperCase()}</div></div>
        <div class="card__body">
          <div class="form-row">
            <div class="form-group"><label class="form-label">GREEN 阈值（GB）</label><input class="form-input" id="qos-green" type="number" value="${thresholds.green}"></div>
            <div class="form-group"><label class="form-label">YELLOW 阈值（GB）</label><input class="form-input" id="qos-yellow" type="number" value="${thresholds.yellow}"></div>
            <div class="form-group"><label class="form-label">RED 阈值（GB）</label><input class="form-input" id="qos-red" type="number" value="${thresholds.red}"></div>
          </div>
          <div class="flex items-center gap-3 mt-4">
            <div class="toggle ${autoDegrade ? 'toggle--active' : ''}" id="qos-auto-toggle" role="switch" aria-checked="${autoDegrade}" tabindex="0"></div>
            <span>自动降级（${autoDegrade ? '已启用' : '默认关闭'}）</span>
          </div>
          <div class="text-tertiary mt-2" style="font-size:12px">QoS 配置保存待后端支持，当前为只读展示</div>
          <button class="btn btn--primary mt-4" id="btn-save-qos" disabled>保存配置</button>
        </div>
      </div>
    `;
    const toggle = Utils.$('#qos-auto-toggle');
    if (toggle) {
      toggle.onclick = () => {
        toggle.classList.toggle('toggle--active');
        const active = toggle.classList.contains('toggle--active');
        toggle.setAttribute('aria-checked', active);
        toggle.nextElementSibling.textContent = `自动降级（${active ? '已启用' : '默认关闭'}）`;
      };
    }
    Utils.$('#btn-save-qos').onclick = () => {
      Toast.show('QoS 配置保存功能待后端支持', 'info');
    };
  },

  async _renderSettingsAutoProtect(el) {
    const ap = await API.getAutoProtectStatus();
    if (!el || !document.contains(el)) return;  // 切页竞态守卫：容器已脱离文档则中止
    const enabled = ap?.enabled ?? true;
    const mode = ap?.mode || 'standard';
    el.innerHTML = `
      <div class="card">
        <div class="card__header"><div class="card__title">自动防死机</div><div class="text-tertiary" style="font-size:12px">${enabled ? '已启用' : '已停用'}</div></div>
        <div class="card__body">
          <div class="flex items-center gap-3 mb-4">
            <div class="toggle ${enabled ? 'toggle--active' : ''}" id="ap-toggle" role="switch" aria-checked="${enabled}" tabindex="0"></div>
            <span>总开关（${enabled ? '运行中' : '已停用'}）</span>
          </div>
          <div class="form-group">
            <label class="form-label">保护模式</label>
            <div class="flex gap-4">
              <label class="flex items-center gap-2"><input type="radio" name="ap-mode" value="conservative" ${mode==='conservative'?'checked':''}> 保守</label>
              <label class="flex items-center gap-2"><input type="radio" name="ap-mode" value="standard" ${mode==='standard'?'checked':''}> 标准</label>
              <label class="flex items-center gap-2"><input type="radio" name="ap-mode" value="aggressive" ${mode==='aggressive'?'checked':''}> 激进</label>
            </div>
          </div>
          <div class="text-tertiary mt-4" style="font-size:12px">保护规则：永不杀桌面进程 / protect 容器（只读）</div>
          <button class="btn btn--primary mt-4" id="btn-save-ap">保存配置</button>
          ${ap?.last_trigger ? `
          <div class="mt-4" style="border-top:1px solid var(--border);padding-top:12px">
            <div class="text-tertiary" style="font-size:12px;margin-bottom:8px">最近触发：${new Date(ap.last_trigger.ts * 1000).toLocaleString('zh-CN')} · ${ap.last_trigger.level} · 空闲 ${(ap.last_trigger.free_mb/1024).toFixed(1)}G</div>
            <div style="font-size:12px;line-height:1.8">
              ${ap.last_trigger.actions.map(a => `<span class="tag tag--${a.level === 'L4' ? 'danger' : a.level === 'L3' ? 'warning' : 'info'}" style="margin-right:6px">${a.level}</span>${a.action}`).join('<br>')}
            </div>
          </div>` : ''}
          ${ap?.history?.length ? `
          <div class="mt-3 text-tertiary" style="font-size:11px">历史触发 ${ap.history.length} 次</div>
          ` : ''}
        </div>
      </div>
    `;
    const toggle = Utils.$('#ap-toggle');
    if (toggle) {
      toggle.onclick = () => {
        toggle.classList.toggle('toggle--active');
        const active = toggle.classList.contains('toggle--active');
        toggle.setAttribute('aria-checked', active);
        toggle.nextElementSibling.textContent = `总开关（${active ? '运行中' : '已停用'}）`;
      };
    }
    Utils.$('#btn-save-ap').onclick = async () => {
      const apEnabled = Utils.$('#ap-toggle').classList.contains('toggle--active');
      const apMode = document.querySelector('input[name="ap-mode"]:checked')?.value || 'standard';
      const btn = Utils.$('#btn-save-ap');
      btn.disabled = true;
      btn.textContent = '保存中...';
      try {
        const res = await API.saveAutoProtectConfig({ enabled: apEnabled, mode: apMode });
        if (res.ok) {
          Toast.show('自动防死机配置已保存', 'success');
        } else {
          Toast.show(`保存失败：${res?.error?.message || '未知错误'}`, 'error');
        }
      } catch (e) {
        Toast.show(`保存失败：${e.message}`, 'error');
      }
      btn.disabled = false;
      btn.textContent = '保存配置';
    };
  },

  _renderSettingsAccount(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card__header"><div class="card__title">账号管理</div></div>
        <div class="card__body">
          <div class="form-group"><label class="form-label">当前密码</label><input type="password" class="form-input" id="pwd-old" placeholder="输入当前密码"></div>
          <div class="form-row">
            <div class="form-group"><label class="form-label">新密码</label><input type="password" class="form-input" id="pwd-new" placeholder="至少6位"></div>
            <div class="form-group"><label class="form-label">确认新密码</label><input type="password" class="form-input" id="pwd-confirm" placeholder="再次输入新密码"></div>
          </div>
          <button class="btn btn--primary mt-4" id="btn-change-pwd">修改密码</button>
        </div>
      </div>
    `;
    Utils.$('#btn-change-pwd').onclick = async () => {
      const oldPwd = Utils.$('#pwd-old').value;
      const newPwd = Utils.$('#pwd-new').value;
      const confirmPwd = Utils.$('#pwd-confirm').value;
      if (!oldPwd) { Toast.show('请输入当前密码', 'warning'); return; }
      if (!newPwd || newPwd.length < 6) { Toast.show('新密码至少6位', 'warning'); return; }
      if (newPwd !== confirmPwd) { Toast.show('两次输入的新密码不一致', 'warning'); return; }
      const btn = Utils.$('#btn-change-pwd');
      btn.disabled = true;
      btn.textContent = '修改中...';
      try {
        const res = await API.changePassword({ old_password: oldPwd, new_password: newPwd });
        if (res.ok) {
          Toast.show('密码修改成功，请重新登录', 'success');
          Utils.$('#pwd-old').value = '';
          Utils.$('#pwd-new').value = '';
          Utils.$('#pwd-confirm').value = '';
          setTimeout(() => { State.clear(); location.hash = '#/login'; }, 1500);
        } else {
          Toast.show(`修改失败：${res?.error?.message || '当前密码不正确'}`, 'error');
        }
      } catch (e) {
        Toast.show(`修改失败：${e.message}`, 'error');
      }
      btn.disabled = false;
      btn.textContent = '修改密码';
    };
  },

  async _renderSettingsWatchdog(el) {
    const status = await API.getStatus();
    if (!el || !document.contains(el)) return;  // 切页竞态守卫：容器已脱离文档则中止
    const watchdogRunning = status?.ok === true;
    el.innerHTML = `
      <div class="card">
        <div class="card__header"><div class="card__title">看门狗</div></div>
        <div class="card__body">
          <div class="flex items-center gap-3 mb-4">
            <span class="status-dot ${watchdogRunning ? 'status-dot--online status-dot--pulse' : 'status-dot--offline'}"></span>
            <span>${watchdogRunning ? '运行中（通过 start.bat / 调度中心启动.bat 启动）' : '未运行'}</span>
          </div>
          <div class="form-row">
            <div class="form-group"><label class="form-label">崩溃后延迟</label><input class="form-input" value="5 秒" disabled></div>
            <div class="form-group"><label class="form-label">1小时最大重启</label><input class="form-input" value="10 次" disabled></div>
            <div class="form-group"><label class="form-label">健康检查间隔</label><input class="form-input" value="5 秒" disabled></div>
          </div>
          <div class="text-tertiary mt-4" style="font-size:12px">
            看门狗配置需手动修改 <code>engine/watchdog.py</code> 中的常量后重启服务。<br>
            启动：双击桌面「调度中心启动.bat」｜ 停止：双击项目目录 <code>stop.bat</code>
          </div>
        </div>
      </div>
    `;
  },

  async _renderSettingsAbout(el) {
    const [status, hardware] = await Promise.all([API.getStatus(), API.getHardware()]);
    if (!el || !document.contains(el)) return;  // 切页竞态守卫：容器已脱离文档则中止
    const uptimeSec = status?._meta?.uptime || 0;
    const uptimeStr = uptimeSec > 0
      ? `${Math.floor(uptimeSec / 3600)}小时${Math.floor((uptimeSec % 3600) / 60)}分`
      : '运行中';
    const gpuName = hardware?.gpu?.name || status?.gpu?.name || '未知';
    const totalGb = (status?.gpu?.total_mb / 1024 || 16).toFixed(1);
    el.innerHTML = `
      <div class="card">
        <div class="card__header"><div class="card__title">关于</div></div>
        <div class="card__body">
          <div class="text-center mb-4">
            <div style="font-size:32px;font-weight:700;color:var(--color-brand-500)">GMae</div>
            <div class="text-secondary mt-1">GPU Maestro - 显存指挥家</div>
          </div>
          <table class="table">
            <tbody>
              <tr><td>版本</td><td class="text-mono">v2.0 (16GAS)</td></tr>
              <tr><td>子项目</td><td>16G-AI-Studio (16GAS)</td></tr>
              <tr><td>核心引擎</td><td>Prism Engine (P-Eng)</td></tr>
              <tr><td>标语</td><td>One GPU, Infinite Models</td></tr>
              <tr><td>运行时间</td><td>${uptimeStr}</td></tr>
              <tr><td>GPU</td><td>${Utils.escapeHtml(gpuName)}</td></tr>
              <tr><td>显存</td><td>${totalGb} GB</td></tr>
              <tr><td>技术栈</td><td>Python / 原生 JS / Docker</td></tr>
              <tr><td>许可证</td><td>MIT</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    `;
  },
});
