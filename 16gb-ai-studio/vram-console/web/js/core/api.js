/* ============================================================
 * API - core 模块
 * 从 app.js 拆分，保持原逻辑不变
 * ============================================================ */

const API = {
  baseUrl: '',
  async request(method, path, body = null, query = null) {
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
    try {
      const res = await fetch(url, options);
      const raw = await res.json();
      // 适配新的 API 响应格式：{ok, data, error, meta} -> 把 data 提升到顶层
      // 这样页面代码可以继续使用 response.gpu / response.freed_mb 等
      if (raw && raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data)) {
        return { ...raw, ...raw.data, _meta: raw.meta, _rawError: raw.error };
      }
      return raw;
    } catch (e) {
      console.error('API error:', e);
      return { ok: false, error: { code: 'NETWORK_ERROR', message: e.message } };
    }
  },
  get(path, query) { return this.request('GET', path, null, query); },
  post(path, body) { return this.request('POST', path, body); },
  put(path, body) { return this.request('PUT', path, body); },
  delete(path) { return this.request('DELETE', path); },

  // Status
  getStatus() { return this.get('/api/status'); },
  getHealth() { return this.get('/api/health'); },
  freeVram(level = 'L1') { return this.post('/api/free', { level }); },

  // Events
  getEvents(query) { return this.get('/api/events/timeline', query); },
  getEventStats() { return this.get('/api/events/stats'); },

  // Diagnose
  diagnose(body) { return this.post('/api/diagnose', body); },
  getDiagnoseRules() { return this.get('/api/diagnose/rules'); },

  // Alerts
  getAlerts() { return this.get('/api/alerts'); },
  getAlertHistory(query) { return this.get('/api/alerts/history', query); },
  getSilencedAlerts() { return this.get('/api/alerts/silenced'); },
  silenceAlert(body) { return this.post('/api/alerts/silence', body); },
  resolveAlert(body) { return this.post('/api/alerts/resolve', body); },
  submitAlert(body) { return this.post('/api/alerts/submit', body); },

  // Models
  getRegistry() { return this.get('/api/registry'); },
  scanModels() { return this.get('/api/scan'); },
  loadModel(body) { return this.post('/api/model', { ...body, action: 'load' }); },
  unloadModel(body) { return this.post('/api/model', { ...body, action: 'unload' }); },

  // Scenes
  getScenes() { return this.get('/api/status').then(r => ({ ok: r.ok, current: r.scene || 'unknown', ...r, error: r._rawError })); },
  switchScene(body) { return this.post('/api/scene', body); },

  // Queue
  getQueue() { return this.get('/api/queue'); },
  submitTask(body) { return this.post('/api/queue', body); },
  cancelTask(body) { return this.post('/api/queue/cancel', body); },

  // Guard
  getGuardStatus() { return this.get('/api/status').then(r => ({ ok: r.ok, ...(r.guard || {}), error: r._rawError })); },
  guardKick(body) { return this.post('/api/guard', { ...body, action: 'kick' }); },
  guardEvict(body) { return this.post('/api/guard', { ...body, action: 'evict' }); },

  // Services
  getServices() { return this.get('/api/status').then(r => ({ ok: r.ok, ...(r.containers || {}), error: r._rawError })); },
  serviceAction(body) { return this.post('/api/service', body); },

  // QoS
  getQosStatus() { return this.get('/api/qos/status'); },

  // Auth
  authStatus() { return this.get('/api/auth/status'); },
  authLogin(body) { return this.post('/api/auth/login', body); },
  authLogout() { return this.post('/api/auth/logout', {}); },
};
