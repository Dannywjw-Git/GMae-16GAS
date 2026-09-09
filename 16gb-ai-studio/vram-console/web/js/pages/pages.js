/* ============================================================
 * Pages - 页面渲染模块入口
 * 结构：
 *   pages.js          - 入口，定义 Pages 对象 + 公共方法
 *   dashboard.js      - 总览页
 *   diagnose.js       - 诊断中心页
 *   alerts.js         - 告警中心页
 *   models.js         - 模型登记台页
 *   vram.js           - 显存账本页
 *   scenes.js         - 场景切换页
 *   queue.js          - 任务队列页
 *   guard.js          - 门卫页
 *   audit.js          - 操作审计页
 *   settings.js       - 设置页
 * 各页面文件通过 Object.assign(Pages, {...}) 扩展 Pages 对象
 * 依赖全局对象：Utils, EventBus, State, API, Toast, Modal, Icons, Router
 * ============================================================ */

const Pages = {
  // ===== 事件说明字典（公共） =====
  _eventDescriptions: {
    'comfy ws connected': 'ComfyUI WebSocket 连接成功，可实时接收生成进度',
    'comfy ws error': 'ComfyUI WebSocket 连接异常，可能影响实时进度显示',
    'comfy ws disconnected': 'ComfyUI WebSocket 断开连接',
    'comfy model loaded': 'ComfyUI 模型加载完成',
    'comfy model unloaded': 'ComfyUI 模型已卸载，释放显存',
    'comfy queue empty': 'ComfyUI 任务队列已清空',
    'comfy prompt queued': 'ComfyUI 任务已加入队列',
    'comfy prompt completed': 'ComfyUI 任务完成',
    'comfy prompt failed': 'ComfyUI 任务失败',
    'ollama model loaded': 'Ollama 模型加载完成，可进行对话',
    'ollama model unloaded': 'Ollama 模型已卸载，释放显存',
    'ollama running': 'Ollama 正在运行推理',
    'ollama idle': 'Ollama 空闲，模型仍在显存中',
    'ollama stopped': 'Ollama 服务已停止',
    'vram warning': '显存使用率超过 70%，注意监控',
    'vram critical': '显存使用率超过 85%，可能触发 OOM',
    'vram recovered': '显存已恢复正常水平',
    'vram released': '显存已释放，可安全加载新模型',
    'vram auto cleanup': '自动显存清理已执行',
    'container started': '容器已启动',
    'container stopped': '容器已停止',
    'container crashed': '容器异常崩溃，建议检查日志',
    'container restarted': '容器已重启',
    'api request': 'API 请求已处理',
    'api error': 'API 请求出错',
    'auto scan full': '自动扫描完成，更新了资源状态',
    'service started': '服务已启动',
    'service stopped': '服务已停止',
    'watchdog restart': '看门狗检测到服务异常，已自动重启',
    'user login': '用户登录',
    'user logout': '用户登出',
    'scene changed': '场景已切换，显存配置已更新',
    'manual release': '用户手动执行显存释放',
  },

  _getEventDescription(event) {
    const key = (event || '').toLowerCase().trim();
    if (this._eventDescriptions[key]) return this._eventDescriptions[key];
    for (const [k, desc] of Object.entries(this._eventDescriptions)) {
      if (key.includes(k) || k.includes(key)) return desc;
    }
    return null;
  },

  // ===== 公共方法：一键释放显存（总览页/显存账本页共用） =====
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
          await new Promise(r => setTimeout(r, 2000));
          State.set('status', null);
          const statusRes = await API.getStatus();
          const status = statusRes;
          State.set('status', status);
          if (typeof updateHeader === 'function') updateHeader();
          const successActions = actions.filter(a => a.ok);
          const failActions = actions.filter(a => !a.ok);
          let releasedHtml = '';
          if (successActions.length > 0) {
            releasedHtml = '<div style="margin-bottom:12px"><div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:6px">已释放的进程/服务：</div>';
            successActions.forEach(a => {
              const freedMb = a.freed_mb || 0;
              releasedHtml += '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--color-border-light);font-size:12px"><span style="color:var(--color-success)">✓ ' + Utils.escapeHtml(a.name || 'unknown') + '</span><span class="text-mono">' + a.action + (freedMb > 0 ? ' · 释放 ' + Utils.formatMB(freedMb) : '') + '</span></div>';
            });
            releasedHtml += '</div>';
          } else {
            releasedHtml = '<div style="margin-bottom:12px;padding:8px;background:rgba(245,158,11,0.08);border-radius:6px;font-size:12px;color:var(--color-warning)">未释放任何进程（当前没有可释放的空闲模型/服务）</div>';
          }
          if (failActions.length > 0) {
            releasedHtml += '<div style="margin-bottom:12px"><div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:6px">释放失败：</div>';
            failActions.forEach(a => {
              releasedHtml += '<div style="padding:4px 0;font-size:12px;color:var(--color-danger)">✗ ' + Utils.escapeHtml(a.name || 'unknown') + ' - ' + Utils.escapeHtml(a.output || a.action || '未知错误') + '</div>';
            });
            releasedHtml += '</div>';
          }
          const remainingProcs = (status.gpu_processes?.processes || []).filter(p => (p.used_mb || 0) > 100);
          const desktopUsed = status.gpu_processes?.desktop_used_mb || 0;
          const gpuUsed = status.gpu?.used_mb || 0;
          let remainingHtml = '<div><div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:6px">当前仍在占用显存的进程：</div>';
          if (remainingProcs.length > 0) {
            remainingProcs.forEach(p => {
              const pName = p.app ? p.app + ' (' + (p.name || 'python') + ')' : (p.name || 'unknown');
              remainingHtml += '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--color-border-light);font-size:12px"><span>' + Utils.escapeHtml(pName) + '</span><span class="text-mono" style="font-weight:600">' + Utils.formatMB(p.used_mb || 0) + '</span></div>';
            });
          } else {
            remainingHtml += '<div style="padding:4px 0;font-size:12px;color:var(--color-text-tertiary)">无 GPU 计算进程</div>';
          }
          if (desktopUsed > 0) {
            remainingHtml += '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--color-border-light);font-size:12px"><span style="color:var(--color-text-tertiary)">Windows 桌面进程（合计）</span><span class="text-mono">' + Utils.formatMB(desktopUsed) + '</span></div>';
          }
          remainingHtml += '<div style="display:flex;justify-content:space-between;padding:6px 0;margin-top:4px;font-size:12px;font-weight:600;border-top:2px solid var(--color-border)"><span>GPU 总占用</span><span class="text-mono" style="color:var(--color-brand-500)">' + Utils.formatMB(gpuUsed) + ' / ' + Utils.formatMB(status.gpu?.total_mb || 16384) + '</span></div></div>';
          Modal.open({
            title: '显存释放结果',
            size: 'md',
            content: '<div style="margin-bottom:16px;padding:12px;background:rgba(13,148,136,0.08);border-radius:8px"><div style="font-size:13px;font-weight:600;color:var(--color-brand-500);margin-bottom:4px">释放完成</div><div style="font-size:12px;color:var(--color-text-secondary)">空闲 ' + Utils.formatMB(before) + ' → ' + Utils.formatMB(after) + (freed > 0 ? ' · 释放 ' + Utils.formatMB(freed) : '') + '</div></div>' + releasedHtml + remainingHtml,
            footer: '<button class="btn btn--primary" data-action="close">确定</button>',
          });
          Modal.modal.querySelector('[data-action="close"]').onclick = () => {
            Modal.close();
            const hash = window.location.hash;
            if (hash === '#/vram' && typeof this._loadVram === 'function') this._loadVram();
            else if (hash === '#/dashboard' && typeof this._loadDashboard === 'function') this._loadDashboard();
          };
        } else {
          Toast.error(res.error?.message || '释放失败');
        }
      },
    });
  },

  // ===== 公共方法：服务操作（总览页/显存账本页共用） =====
  async _serviceAction(service, action) {
    const actionLabel = { start: '启动', stop: '停止', restart: '重启' }[action] || action;
    if (action === 'stop') {
      const ok = await Modal.confirmAsync(actionLabel + '服务', '确定要' + actionLabel + '「' + service + '」吗？');
      if (!ok) return;
    }
    Toast.info('正在' + actionLabel + ' ' + service + '...');
    const res = await API.serviceAction({ service, action });
    if (res.ok) {
      Toast.success('服务「' + service + '」' + actionLabel + '成功');
      State.set('status', null);
      if (typeof updateHeader === 'function') updateHeader();
      const hash = window.location.hash;
      if (hash === '#/dashboard' && typeof this._loadDashboard === 'function') this._loadDashboard();
      else if (hash === '#/vram' && typeof this._loadVram === 'function') this._loadVram();
    } else {
      Toast.error(actionLabel + '失败：' + (res?.error?.message || '未知错误'));
    }
  },
};
