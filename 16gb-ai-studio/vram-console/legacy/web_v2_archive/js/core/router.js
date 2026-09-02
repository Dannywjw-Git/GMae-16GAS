/**
 * GMae 指挥家 v2.0 - core/router.js
 * 哈希路由：页面切换、权限守卫、参数解析
 *
 * 约定：
 * - URL 格式：#/dashboard 或 #/models?filter=llm
 * - 页面通过 register() 注册，render 返回 DOM 或挂载到容器
 * - 未注册的路由 → 404 页面
 * - 权限守卫：guard 返回 false 时阻止进入并重定向
 */

import { events } from './events.js';

const DEFAULT_PAGE = 'dashboard';

/** 页面渲染容器（默认 #app，main.js 可改为布局内的 content 区） */
let containerSelector = '#app';

/** @type {Map<string, object>} */
const pages = new Map();

/** 设置页面渲染容器 */
export function setContainer(selector) {
  containerSelector = selector;
}

function getContainer() {
  return document.querySelector(containerSelector);
}

/**
 * 注册页面
 * @param {string} name
 * @param {object} def {
 *   title: string,          // 页面标题（顶栏显示）
 *   render: (ctx)=>HTMLElement|string,  // 渲染函数，ctx={params, query, container}
 *   guard: (ctx)=>boolean,  // 可选权限守卫
 *   onLeave: ()=>void,      // 可选离开回调
 * }
 */
export function register(name, def) {
  pages.set(name, def);
}

/** 是否已注册 */
export function has(name) {
  return pages.has(name);
}

/** 已注册页面列表 */
export function list() {
  return [...pages.keys()];
}

/** 解析当前 hash → { name, params, query } */
function parseHash(hash) {
  let h = hash || '';
  if (h.startsWith('#')) h = h.slice(1);
  if (!h || h === '/') h = DEFAULT_PAGE;
  // 去掉首尾 /
  h = h.replace(/^\/+|\/+$/g, '');

  const [pathPart, queryPart] = h.split('?');
  const segments = pathPart.split('/').filter(Boolean);
  const name = segments[0] || DEFAULT_PAGE;

  const params = {};
  for (let i = 1; i < segments.length; i++) params[i] = decodeURIComponent(segments[i]);

  const query = {};
  if (queryPart) {
    for (const pair of queryPart.split('&')) {
      if (!pair) continue;
      const [k, ...v] = pair.split('=');
      query[decodeURIComponent(k)] = decodeURIComponent(v.join('=') || '');
    }
  }
  return { name, params, query };
}

/** 当前路由上下文 */
export function current() {
  return parseHash(window.location.hash);
}

/**
 * 导航到指定页面
 * @param {string} name
 * @param {object} opts { params:[], query:{} }
 */
export function go(name, opts = {}) {
  let hash = `#/${name}`;
  const params = opts.params || [];
  for (const p of params) hash += `/${encodeURIComponent(String(p))}`;
  const q = opts.query || {};
  const qs = Object.entries(q)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');
  if (qs) hash += `?${qs}`;
  if (window.location.hash !== hash) {
    window.location.hash = hash;
  } else {
    // hash 相同也要触发一次（可能是刷新数据）
    dispatch();
  }
}

/** 返回上一页（无历史则去默认页） */
export function back() {
  if (window.history.length > 1) window.history.back();
  else go(DEFAULT_PAGE);
}

/** 当前活跃页面定义（用于 onLeave 回调） */
let activeDef = null;

/** 路由分发：根据当前 hash 渲染页面 */
function dispatch() {
  const ctx = parseHash(window.location.hash);
  const def = pages.get(ctx.name);

  // 未注册 → 404
  if (!def) {
    events.emit('route:change', { ...ctx, found: false });
    if (activeDef && typeof activeDef.onLeave === 'function') {
      try { activeDef.onLeave(); } catch (e) { console.error('[router] onLeave error', e); }
    }
    activeDef = null;
    render404(ctx);
    return;
  }

  // 权限守卫
  if (typeof def.guard === 'function' && !def.guard(ctx)) {
    events.emit('route:denied', { name: ctx.name });
    go(DEFAULT_PAGE);
    return;
  }

  // 离开当前页回调
  if (activeDef && activeDef !== def && typeof activeDef.onLeave === 'function') {
    try { activeDef.onLeave(); } catch (e) { console.error('[router] onLeave error', e); }
  }

  events.emit('route:change', { ...ctx, found: true, title: def.title });
  const container = getContainer();
  if (!container) return;

  container.innerHTML = '';
  try {
    const rendered = def.render(ctx);
    if (rendered instanceof Node) container.appendChild(rendered);
    else if (typeof rendered === 'string') container.innerHTML = rendered;
    // 渲染完成后调用页面进入钩子（数据加载/轮询等）
    if (typeof def.onEnter === 'function') {
      try { def.onEnter(ctx); } catch (e) { console.error(`[router] onEnter "${ctx.name}" error`, e); }
    }
    activeDef = def;
  } catch (err) {
    console.error(`[router] render "${ctx.name}" error`, err);
    container.innerHTML = `<div class="page-error">
      <h2>页面渲染失败</h2>
      <p>${String(err && err.message || err)}</p>
    </div>`;
    activeDef = null;
  }
}

/** 渲染 404 */
function render404(ctx) {
  const container = getContainer();
  if (!container) return;
  container.innerHTML = `<div class="page-error">
    <h2>页面不存在</h2>
    <p>路由 <code>${ctx.name}</code> 未注册</p>
    <button class="btn btn--primary" data-route="${DEFAULT_PAGE}">返回总览</button>
  </div>`;
  container.querySelector('[data-route]')?.addEventListener('click', () => go(DEFAULT_PAGE));
}

/** 启动路由（监听 hashchange） */
export function start() {
  window.addEventListener('hashchange', dispatch);
  // 等页面 DOM 就绪后首次分发
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', dispatch);
  } else {
    dispatch();
  }
  return () => window.removeEventListener('hashchange', dispatch);
}

export default { register, has, list, go, back, start, current, setContainer };
