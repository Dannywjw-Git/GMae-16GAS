/**
 * GMae 指挥家 v2.0 - components/modal.js
 * 弹窗 / 右侧抽屉 / 确认框
 * - open({ title, body, footer, width }) → 通用模态
 * - confirm({ title, message, okText, danger }) → Promise<boolean> 确认框
 * - drawer({ title, body, width }) → 右侧抽屉（模型详情等）
 * 所有方法返回关闭函数；按 ESC / 点遮罩关闭
 */

import { el, empty } from '../core/utils.js';

function ensureOverlay() {
  let overlay = document.querySelector('.modal-overlay');
  if (!overlay) {
    overlay = el('<div class="modal-overlay"></div>');
    document.body.appendChild(overlay);
  }
  return overlay;
}

function onKeydown(e) {
  if (e.key === 'Escape') {
    const active = document.querySelector('.modal-overlay:not([hidden]), .drawer--open');
    if (active) {
      closeTop();
    }
  }
}

function closeTop() {
  const overlay = document.querySelector('.modal-overlay');
  const drawer = document.querySelector('.drawer--open');
  if (drawer) {
    drawer.classList.remove('drawer--open');
    setTimeout(() => drawer.remove(), 300);
  }
  if (overlay && overlay.style.display !== 'none') {
    overlay.remove();
  }
}

/** 挂载键盘监听（只装一次） */
let keyBound = false;
function bindKey() {
  if (keyBound) return;
  keyBound = true;
  document.addEventListener('keydown', onKeydown);
}

/**
 * 通用弹窗
 * @param {object} opts { title, body(HTMLElement|string), footer(HTMLElement|string|Array), width }
 * @returns {Function} close
 */
export function open(opts = {}) {
  bindKey();
  const overlay = ensureOverlay();
  empty(overlay);

  const modal = el(`<div class="modal" style="${opts.width ? `width:${opts.width};max-width:${opts.width};` : ''}">
    <div class="modal__header">
      <div class="modal__title"></div>
      <button class="btn btn--icon" data-close aria-label="关闭">✕</button>
    </div>
    <div class="modal__body"></div>
    <div class="modal__footer"></div>
  </div>`);

  modal.querySelector('.modal__title').textContent = opts.title || '';
  const body = modal.querySelector('.modal__body');
  const footer = modal.querySelector('.modal__footer');

  if (opts.body instanceof Node) body.appendChild(opts.body);
  else if (opts.body) body.innerHTML = opts.body;

  // 组装 footer
  if (opts.footer) {
    if (Array.isArray(opts.footer)) {
      for (const item of opts.footer) footer.appendChild(item);
    } else if (opts.footer instanceof Node) {
      footer.appendChild(opts.footer);
    } else {
      footer.innerHTML = opts.footer;
    }
  } else {
    footer.remove();
  }

  overlay.appendChild(modal);

  const close = () => {
    overlay.remove();
  };
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  modal.querySelector('[data-close]').addEventListener('click', close);
  return close;
}

/**
 * 确认框
 * @param {object} opts { title, message, okText, cancelText, danger }
 * @returns {Promise<boolean>}
 */
export function confirm(opts = {}) {
  return new Promise((resolve) => {
    const okBtn = el(`<button class="btn ${opts.danger ? 'btn--danger' : 'btn--primary'}">${opts.okText || '确定'}</button>`);
    const cancelBtn = el(`<button class="btn btn--ghost">${opts.cancelText || '取消'}</button>`);
    const close = open({
      title: opts.title || '确认操作',
      body: el(`<div class="modal-confirm">${opts.message || '确定执行此操作吗？'}</div>`),
      footer: [cancelBtn, okBtn],
    });
    okBtn.addEventListener('click', () => { close(); resolve(true); });
    cancelBtn.addEventListener('click', () => { close(); resolve(false); });
  });
}

/**
 * 右侧抽屉
 * @param {object} opts { title, body, width }
 * @returns {Function} close
 */
export function drawer(opts = {}) {
  bindKey();
  const overlay = ensureOverlay();
  empty(overlay);
  overlay.style.alignItems = 'stretch';
  overlay.style.justifyContent = 'flex-end';

  const d = el(`<div class="drawer" style="${opts.width ? `width:${opts.width};` : ''}">
    <div class="modal__header">
      <div class="modal__title"></div>
      <button class="btn btn--icon" data-close aria-label="关闭">✕</button>
    </div>
    <div class="drawer__body"></div>
  </div>`);
  d.querySelector('.modal__title').textContent = opts.title || '';
  const body = d.querySelector('.drawer__body');
  if (opts.body instanceof Node) body.appendChild(opts.body);
  else if (opts.body) body.innerHTML = opts.body;

  overlay.appendChild(d);
  // 触发进入动画
  requestAnimationFrame(() => d.classList.add('drawer--open'));

  const close = () => {
    d.classList.remove('drawer--open');
    setTimeout(() => { overlay.remove(); }, 300);
  };
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  d.querySelector('[data-close]').addEventListener('click', close);
  return close;
}

export default { open, confirm, drawer };
