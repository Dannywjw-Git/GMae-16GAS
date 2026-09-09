/* ============================================================
 * Modal - components 模块
 * 从 app.js 拆分，保持原逻辑不变
 * ============================================================ */

const Modal = {
  overlay: null,
  modal: null,
  init() {
    this.overlay = Utils.createEl('div', 'modal-overlay');
    this.modal = Utils.createEl('div', 'modal');
    this.overlay.appendChild(this.modal);
    document.body.appendChild(this.overlay);
    this.overlay.onclick = (e) => { if (e.target === this.overlay) this.close(); };
  },
  open({ title, content, footer = '', size = '' }) {
    this.modal.className = 'modal' + (size ? ' modal--' + size : '');
    this.modal.innerHTML = `
      <div class="modal__header">
        <div class="modal__title">${Utils.escapeHtml(title)}</div>
        <div class="modal__close">✕</div>
      </div>
      <div class="modal__body">${content}</div>
      ${footer ? `<div class="modal__footer">${footer}</div>` : ''}
    `;
    this.modal.querySelector('.modal__close').onclick = () => this.close();
    this.overlay.classList.add('modal-overlay--open');
  },
  close() { this.overlay.classList.remove('modal-overlay--open'); },
  confirm({ title, message, confirmText = '确认', cancelText = '取消', danger = false, onConfirm }) {
    const footer = `
      <button class="btn btn--secondary" data-action="cancel">${cancelText}</button>
      <button class="btn ${danger ? 'btn--danger' : 'btn--primary'}" data-action="confirm">${confirmText}</button>
    `;
    this.open({ title, content: `<p>${Utils.escapeHtml(message)}</p>`, footer });
    this.modal.querySelector('[data-action="cancel"]').onclick = () => this.close();
    this.modal.querySelector('[data-action="confirm"]').onclick = () => {
      this.close();
      if (onConfirm) onConfirm();
    };
  },
  /** Promise 版确认框，用于 async/await 场景 */
  confirmAsync(title, message, options = {}) {
    return new Promise((resolve) => {
      let resolved = false;
      const doResolve = (val) => {
        if (resolved) return;
        resolved = true;
        this.close();
        resolve(val);
      };
      this.confirm({
        title,
        message,
        confirmText: options.confirmText || '确认',
        cancelText: options.cancelText || '取消',
        danger: options.danger || false,
        onConfirm: () => doResolve(true),
      });
      const cancelBtn = this.modal.querySelector('[data-action="cancel"]');
      if (cancelBtn) cancelBtn.onclick = () => doResolve(false);
      const closeBtn = this.modal.querySelector('.modal__close');
      if (closeBtn) closeBtn.onclick = () => doResolve(false);
      this.overlay.onclick = (e) => { if (e.target === this.overlay) doResolve(false); };
    });
  },
};
