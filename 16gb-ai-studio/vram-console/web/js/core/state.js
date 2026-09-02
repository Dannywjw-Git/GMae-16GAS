/* ============================================================
 * State - core 模块
 * 从 app.js 拆分，保持原逻辑不变
 * ============================================================ */

const State = {
  _data: {
    status: null,
    alerts: [],
    events: [],
    models: [],
    currentScene: null,
    user: null,
    apiToken: null,
  },
  get(key) { return this._data[key]; },
  set(key, value) {
    this._data[key] = value;
    EventBus.emit('state:' + key, value);
  },
  getAll() { return { ...this._data }; },
  vramHistory: [],
  vramHistoryMax: 60,
  recordVram(used_mb, free_mb, total_mb) {
    this.vramHistory.push({ t: Date.now(), used: used_mb, free: free_mb, total: total_mb });
    if (this.vramHistory.length > this.vramHistoryMax) this.vramHistory.shift();
  },
};
