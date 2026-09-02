/* ============================================================
 * EventBus - core 模块
 * 从 app.js 拆分，保持原逻辑不变
 * ============================================================ */

const EventBus = {
  _listeners: {},
  on(event, fn) {
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(fn);
  },
  off(event, fn) {
    if (!this._listeners[event]) return;
    this._listeners[event] = this._listeners[event].filter(f => f !== fn);
  },
  emit(event, data) {
    if (!this._listeners[event]) return;
    this._listeners[event].forEach(fn => {
      try { fn(data); } catch (e) { console.error('EventBus error:', e); }
    });
  },
};
