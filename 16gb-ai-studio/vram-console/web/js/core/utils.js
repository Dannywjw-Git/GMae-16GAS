/* ============================================================
 * Utils - core 模块
 * 从 app.js 拆分，保持原逻辑不变
 * ============================================================ */

const Utils = {
  formatBytes(bytes) {
    if (bytes === null || bytes === undefined) return '—';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' GB';
    return bytes + ' MB';
  },
  formatMB(mb) {
    if (mb === null || mb === undefined) return '—';
    if (mb >= 1024) return (mb / 1024).toFixed(1) + 'G';
    return Math.round(mb) + 'M';
  },
  formatTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts);
    return d.toLocaleTimeString('zh-CN', { hour12: false });
  },
  formatDateTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts);
    return d.toLocaleString('zh-CN', { hour12: false });
  },
  formatDuration(seconds) {
    if (!seconds || seconds < 0) return '—';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    if (m > 0) return `${m}分${s}秒`;
    return `${s}秒`;
  },
  escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },
  debounce(fn, delay = 300) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  },
  $(selector, parent = document) { return parent.querySelector(selector); },
  $$(selector, parent = document) { return Array.from(parent.querySelectorAll(selector)); },
  createEl(tag, className = '', html = '') {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (html) el.innerHTML = html;
    return el;
  },
};
