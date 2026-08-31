/**
 * GMae 指挥家 v2.0 - components/toast.js
 * Toast 通知组件
 * - 订阅 'toast' 事件：{ type: 'success'|'error'|'info'|'warn', message, duration }
 * - 订阅 'api:error' 事件：自动弹出后端错误
 * - 手动调用：toast.show('保存成功', 'success')
 */

import { events } from '../core/events.js';
import { el, sleep } from '../core/utils.js';

const DEFAULT_DURATION = 3500;
let container = null;

function getContainer() {
  if (!container) {
    container = el('<div class="toast-container"></div>');
    document.body.appendChild(container);
  }
  return container;
}

const ICONS = {
  success: '✓',
  error: '✕',
  info: 'ℹ',
  warn: '!',
};

/**
 * 显示一条 toast
 * @param {string} message
 * @param {'success'|'error'|'info'|'warn'} type
 * @param {number} duration ms
 */
export async function show(message, type = 'info', duration = DEFAULT_DURATION) {
  if (!message) return;
  const icon = ICONS[type] || 'ℹ';
  const node = el(`<div class="toast toast--${type}" role="alert">
    <span class="toast__icon">${icon}</span>
    <span class="toast__msg"></span>
  </div>`);
  node.querySelector('.toast__msg').textContent = message;
  getContainer().appendChild(node);

  await sleep(duration);
  node.classList.add('toast--leave');
  await sleep(300);
  node.remove();
}

/** 快捷方法 */
export const success = (m, d) => show(m, 'success', d);
export const error = (m, d) => show(m, 'error', d);
export const info = (m, d) => show(m, 'info', d);
export const warn = (m, d) => show(m, 'warn', d);

/** 在 main.js 调用一次：接线事件总线 */
export function init() {
  events.on('toast', ({ type = 'info', message, duration } = {}) => {
    if (message) show(message, type, duration);
  });
  // api.js 的错误事件 → 自动弹错误 toast（silent 请求除外）
  events.on('api:error', ({ message }) => {
    if (message && !message.includes('未认证')) show(message, 'error');
  });
}

export default { show, success, error, info, warn, init };
