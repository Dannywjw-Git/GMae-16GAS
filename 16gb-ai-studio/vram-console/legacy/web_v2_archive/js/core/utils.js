/**
 * GMae 指挥家 v2.0 - core/utils.js
 * 通用工具函数：格式化、防抖节流、DOM 操作、数值处理
 * ES Module，无全局变量，无副作用
 */

/* ========== 数值与格式化 ========== */

/** 数值钳制到 [min, max] */
export function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

/** 显存字节数 → 可读字符串（自动 MB/GB） */
export function fmtBytes(bytes, digits = 1) {
  if (bytes === null || bytes === undefined || isNaN(bytes)) return '—';
  const gb = bytes / 1024;
  if (gb >= 1) return `${gb.toFixed(digits)} GB`;
  return `${bytes.toFixed(0)} MB`;
}

/** 显存 MB 数 → 可读字符串（自动 MB/GB） */
export function fmtMb(mb, digits = 1) {
  if (mb === null || mb === undefined || isNaN(mb)) return '—';
  if (mb >= 1024) return `${(mb / 1024).toFixed(digits)} GB`;
  return `${Math.round(mb)} MB`;
}

/** 百分比 → 字符串（保留 0 位小数，自动带 %） */
export function fmtPct(value, digits = 0) {
  if (value === null || value === undefined || isNaN(value)) return '—';
  return `${value.toFixed(digits)}%`;
}

/**
 * Unix 时间戳 → 本地时间字符串
 * @param {number} ts 秒级时间戳
 * @param {boolean} withSeconds
 */
export function fmtTs(ts, withSeconds = true) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  if (isNaN(d.getTime())) return '—';
  const pad = (n) => String(n).padStart(2, '0');
  const base = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return withSeconds ? `${base}:${pad(d.getSeconds())}` : base;
}

/** 相对时间描述（"刚刚 / 5 分钟前 / 昨天 14:03"） */
export function fmtRelative(ts) {
  if (!ts) return '—';
  const diff = Date.now() / 1000 - ts;
  if (diff < 0) return fmtTs(ts, false);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 172800) return `昨天 ${fmtTs(ts, false).slice(11)}`;
  if (diff < 604800) return `${Math.floor(diff / 86400)} 天前`;
  return fmtTs(ts, false);
}

/** 秒数 → "mm:ss" 或 "h:mm:ss" */
export function fmtDuration(sec) {
  if (sec === null || sec === undefined || isNaN(sec) || sec < 0) return '—';
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

/* ========== 防抖 / 节流 ========== */

/**
 * 防抖：延迟执行，连续触发会重置计时
 * @param {Function} fn
 * @param {number} wait ms
 */
export function debounce(fn, wait = 300) {
  let timer = null;
  const debounced = function (...args) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn.apply(this, args);
    }, wait);
  };
  debounced.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return debounced;
}

/**
 * 节流：限制执行频率（leading + trailing）
 * @param {Function} fn
 * @param {number} wait ms
 */
export function throttle(fn, wait = 300) {
  let last = 0;
  let timer = null;
  let lastArgs = null;
  const throttled = function (...args) {
    const now = Date.now();
    const remaining = wait - (now - last);
    lastArgs = args;
    if (remaining <= 0) {
      if (timer) { clearTimeout(timer); timer = null; }
      last = now;
      fn.apply(this, args);
    } else if (!timer) {
      timer = setTimeout(() => {
        timer = null;
        last = Date.now();
        fn.apply(this, lastArgs);
      }, remaining);
    }
  };
  throttled.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return throttled;
}

/** 延迟 promise */
export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/* ========== DOM 工具 ========== */

/** HTML 转义（XSS 防护，所有插入用户/后端文本必须经过） */
export function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * 从 HTML 字符串创建单个元素
 * @param {string} html
 * @returns {HTMLElement}
 */
export function el(html) {
  const template = document.createElement('template');
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
}

/**
 * 创建元素（声明式）
 * @param {string} tag
 * @param {object} opts {class, text, html, attrs:{}, style:{}, dataset:{}, children:[]}
 */
export function createEl(tag, opts = {}) {
  const node = document.createElement(tag);
  if (opts.class) node.className = opts.class;
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.html !== undefined) node.innerHTML = opts.html;
  if (opts.attrs) {
    for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, v);
  }
  if (opts.dataset) {
    for (const [k, v] of Object.entries(opts.dataset)) node.dataset[k] = v;
  }
  if (opts.style) {
    for (const [k, v] of Object.entries(opts.style)) node.style[k] = v;
  }
  if (opts.children) {
    for (const child of opts.children) {
      node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    }
  }
  return node;
}

/** 清空元素子节点 */
export function empty(node) {
  if (!node) return;
  while (node.firstChild) node.removeChild(node.firstChild);
}

/* ========== 其它 ========== */

/** 生成短 id */
export function uid(prefix = 'id') {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * 解析后端统一返回 { ok, ... } | { ok:false, error }
 * 失败时抛错（带 message）
 */
export function unwrap(resp, fallback = '操作失败') {
  if (resp && resp.ok === false) {
    throw new Error((resp && resp.error) || resp.message || fallback);
  }
  return resp;
}

/** 获取元素值（兼容 checkbox/select/input） */
export function inputVal(node) {
  if (!node) return '';
  if (node.type === 'checkbox') return node.checked;
  return node.value;
}

/** 深拷贝（用于状态快照，避免引用泄漏） */
export function clone(obj) {
  if (obj === null || typeof obj !== 'object') return obj;
  return JSON.parse(JSON.stringify(obj));
}
