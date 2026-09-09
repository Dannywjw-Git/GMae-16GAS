/* ============================================================
 * API - core 模块
 * GMae 调度中心前端 API 封装层
 * 基于 2026-09-03 后端实测：22个GET + 19个POST 全部可用
 * ============================================================ */

const API = {
  baseUrl: '',
  /** 请求超时（毫秒）。显存释放等长操作单独覆盖 */
  defaultTimeout: 30000,

  async request(method, path, body = null, query = null, timeout = null) {
    let url = this.baseUrl + path;
    if (query) {
      const params = new URLSearchParams();
      Object.entries(query).forEach(([k, v]) => {
        if (v !== null && v !== undefined) params.append(k, v);
      });
      const qs = params.toString();
      if (qs) url += '?' + qs;
    }
    const options = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    const token = State.get('apiToken');
    if (token) options.headers['X-API-Key'] = token;
    if (body) options.body = JSON.stringify(body);

    // 超时控制：AbortController
    const effectiveTimeout = timeout || this.defaultTimeout;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), effectiveTimeout);
    options.signal = controller.signal;

    try {
      const res = await fetch(url, options);
      clearTimeout(timeoutId);
      const raw = await res.json();
      // 适配新的 API 响应格式：{ok, data, error, meta} -> 把 data 提升到顶层
      // 这样页面代码可以继续使用 response.gpu / response.freed_mb 等
      if (raw && raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data)) {
        return { ...raw, ...raw.data, _meta: raw.meta, _rawError: raw.error };
      }
      return raw;
    } catch (e) {
      clearTimeout(timeoutId);
      if (e.name === 'AbortError') {
        console.error('API timeout:', method, path, effectiveTimeout + 'ms');
        return { ok: false, error: { code: 'TIMEOUT', message: '请求超时（' + (effectiveTimeout / 1000) + '秒），请稍后重试' } };
      }
      console.error('API error:', method, path, e);
      return { ok: false, error: { code: 'NETWORK_ERROR', message: e.message } };
    }
  },
  get(path, query, timeout) { return this.request('GET', path, null, query, timeout); },
  post(path, body, timeout) { return this.request('POST', path, body, null, timeout); },
  put(path, body) { return this.request('PUT', path, body); },
  delete(path) { return this.request('DELETE', path); },

  // ======== 状态与硬件 ========
  getStatus() { return this.get('/api/status'); },
  getHealth() { return this.get('/api/health'); },
  getHardware() { return this.get('/api/hardware'); },
  freeVram(level = 'L1') {
    // 显存释放可能耗时较长，给 90 秒超时
    return this.post('/api/free', { level }, 90000);
  },

  // ======== 显存预算与建议 ========
  getBudget() { return this.get('/api/budget'); },
  getAdvice() { return this.get('/api/advice'); },
  checkAdmission(body) { return this.post('/api/admission', body); },

  // ======== 事件 ========
  getEvents(query) { return this.get('/api/events/timeline', query); },
  getEventStats() { return this.get('/api/events/stats'); },
  getComfyEvents() { return this.get('/api/comfy_events'); },
  getV1Events() { return this.get('/api/v1/events'); },

  // ======== 诊断 ========
  diagnose(body) { return this.post('/api/diagnose', body); },
  getDiagnoseRules() { return this.get('/api/diagnose/rules'); },

  // ======== 告警 ========
  getAlerts() { return this.get('/api/alerts'); },
  getAlertHistory(query) { return this.get('/api/alerts/history', query); },
  getSilencedAlerts() { return this.get('/api/alerts/silenced'); },
  silenceAlert(body) { return this.post('/api/alerts/silence', body); },
  resolveAlert(body) { return this.post('/api/alerts/resolve', body); },
  submitAlert(body) { return this.post('/api/alerts/submit', body); },

  // ======== 模型与注册表 ========
  getRegistry() { return this.get('/api/registry'); },
  scanModels() { return this.get('/api/scan'); },
  scanRegister(body) { return this.post('/api/scan/register', body); },
  loadModel(body) { return this.post('/api/model', { ...body, action: 'load' }); },
  unloadModel(body) { return this.post('/api/model', { ...body, action: 'unload' }); },

  // ======== 场景切换 ========
  /** 获取当前场景（从 status 派生，保留兼容） */
  getScenes() { return this.get('/api/status').then(r => ({ ok: r.ok, current: r.scene || 'unknown', ...r, error: r._rawError })); },
  /** 获取完整场景列表（含步骤定义，从 registry.scenes 获取） */
  getSceneList() {
    return this.get('/api/registry').then(r => ({
      ok: r.ok,
      scenes: r.scenes || {},
      current: r.scene || 'unknown',
      error: r._rawError,
    }));
  },
  switchScene(body) { return this.post('/api/scene', body); },
  /** 组合切换（如 ollama_combos） */
  switchCombo(body) { return this.post('/api/combo', body); },

  // ======== 任务队列 ========
  getQueue() { return this.get('/api/queue'); },
  submitTask(body) { return this.post('/api/queue', body); },
  cancelTask(body) { return this.post('/api/queue/cancel', body); },

  // ======== 门卫 ========
  getGuardStatus() { return this.get('/api/status').then(r => ({ ok: r.ok, ...(r.guard || {}), error: r._rawError })); },
  guardAction(body) { return this.post('/api/guard', body); },
  guardKick(body) { return this.post('/api/guard', { ...body, action: 'kick' }); },
  guardEvict(body) { return this.post('/api/guard', { ...body, action: 'evict' }); },

  // ======== 服务与容器 ========
  getServices() { return this.get('/api/status').then(r => ({ ok: r.ok, ...(r.containers || {}), error: r._rawError })); },
  serviceAction(body) { return this.post('/api/service', { name: body.name || body.service, action: body.action }); },
  stopContainer(body) { return this.post('/api/container/stop', body); },
  getHealthServices() { return this.get('/api/v1/health/services'); },

  // ======== QoS ========
  getQosStatus() { return this.get('/api/qos/status'); },
  /** 注意：后端无 /api/qos/check，用 executeQos 执行处置建议 */
  executeQos(body) { return this.post('/api/qos/execute', body); },

  // ======== 自动防死机 ========
  getAutoProtectStatus() { return this.get('/api/auto-protect/status'); },
  saveAutoProtectConfig(body) { return this.post('/api/auto-protect/config', body); },

  // ======== 桌面进程与助手 ========
  getDesktopVram() { return this.get('/api/desktop_vram'); },
  getDesktopHelperStatus() { return this.get('/api/desktop/helper/status'); },
  startDesktopHelper() { return this.post('/api/desktop/helper/start', {}); },
  stopDesktopHelper() { return this.post('/api/desktop/helper/stop', {}); },
  killDesktopProcess(body) { return this.post('/api/desktop/kill', body); },

  // ======== 拓扑与健康评分 ========
  getTopology() { return this.get('/api/topology'); },
  getHealthScore() { return this.get('/api/health/score'); },

  // ======== 日志 ========
  getLogs(query) { return this.get('/api/logs', query); },

  // ======== 认证 ========
  authStatus() { return this.get('/api/auth/status'); },
  authLogin(body) { return this.post('/api/auth/login', body); },
  authLogout() { return this.post('/api/auth/logout', {}); },
  changePassword(body) { return this.post('/api/auth/change-password', body); },
  authSetup(body) { return this.post('/api/auth/setup', body); },
  authForgot(body) { return this.post('/api/auth/forgot', body); },
  authReset(body) { return this.post('/api/auth/reset', body); },
};
