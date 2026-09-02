/* ============================================================
 * Toast - components 模块
 * 从 app.js 拆分，保持原逻辑不变
 * ============================================================ */

const Toast = {
  container: null,
  init() {
    this.container = Utils.createEl('div', 'toast-container');
    document.body.appendChild(this.container);
  },
  show(message, type = 'info', title = '', duration = 4000) {
    const icons = { success: '✓', warning: '⚠', danger: '✕', info: 'ℹ' };
    const toast = Utils.createEl('div', `toast toast--${type}`);
    toast.innerHTML = `
      <div class="toast__icon">${icons[type] || 'ℹ'}</div>
      <div class="toast__content">
        ${title ? `<div class="toast__title">${Utils.escapeHtml(title)}</div>` : ''}
        <div class="toast__message">${Utils.escapeHtml(message)}</div>
      </div>
      <div class="toast__close">✕</div>
    `;
    this.container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('toast--show'));
    const close = () => {
      toast.classList.remove('toast--show');
      setTimeout(() => toast.remove(), 300);
    };
    toast.querySelector('.toast__close').onclick = close;
    if (duration > 0) setTimeout(close, duration);
  },
  success(msg, title = '') { this.show(msg, 'success', title); },
  warning(msg, title = '') { this.show(msg, 'warning', title, 8000); },
  error(msg, title = '') { this.show(msg, 'danger', title, 8000); },
  info(msg, title = '') { this.show(msg, 'info', title); },
};
