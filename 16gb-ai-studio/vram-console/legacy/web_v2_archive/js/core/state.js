/**
 * GMae 指挥家 v2.0 - core/state.js
 * 集中式状态管理：subscribe/notify 模式
 *
 * 约定：
 * - 状态按域（domain）组织，每个域一个命名空间
 * - set/update 后自动广播事件 `state:{domain}`，payload = 该域最新状态
 * - 组件通过 subscribe 订阅所需域，页面卸载时返回的取消函数解绑
 * - 读取用 get/snapshot，写入用 set/update；禁止直接改内部对象
 */

import { events } from './events.js';
import { clone } from './utils.js';

/** 状态域清单（新增域时在此声明默认值） */
const DEFAULT_STATE = {
  auth: { status: 'unknown', email: '', hasAdmin: false },
  status: null,          // /api/status 聚合数据
  registry: null,        // /api/registry 模型登记台
  budget: null,          // /api/budget 预算引擎
  scenes: null,          // 场景列表/当前场景
  queue: null,           // /api/queue 任务队列
  guard: null,           // /api/guard 门卫
  desktop: null,         // /api/desktop_vram 桌面进程
  desktopHelper: null,   // /api/desktop/helper/status
  qos: null,             // QoS 状态
  comfyEvents: null,     // ComfyUI 事件
  logs: null,            // 操作日志
  ui: {                  // 纯 UI 状态（不持久化到后端）
    sidebarCollapsed: false,
    activePage: 'dashboard',
    version: 'v2.0.0-alpha',
    loading: new Set(),  // 正在进行的加载 key
    toasts: [],
  },
};

class Store {
  constructor() {
    /** @type {Record<string, any>} */
    this._state = clone(DEFAULT_STATE);
  }

  /**
   * 读取某域状态
   * @param {string} domain
   */
  get(domain) {
    return this._state[domain] ?? null;
  }

  /** 读取整份快照（深拷贝） */
  snapshot() {
    return clone(this._state);
  }

  /**
   * 整体替换某域状态并广播
   * @param {string} domain
   * @param {*} value
   */
  set(domain, value) {
    this._state[domain] = value;
    events.emit(`state:${domain}`, value);
  }

  /**
   * 合并更新某域（浅合并，适用于对象域）
   * @param {string} domain
   * @param {object} patch
   */
  update(domain, patch) {
    const cur = this._state[domain];
    const next = (cur && typeof cur === 'object' && !Array.isArray(cur))
      ? { ...cur, ...patch }
      : patch;
    this.set(domain, next);
    return next;
  }

  /**
   * 订阅某域变化
   * @param {string} domain
   * @param {(value:any)=>void} fn
   * @returns {Function} 取消订阅
   */
  subscribe(domain, fn) {
    return events.on(`state:${domain}`, fn);
  }

  /** 订阅全部状态变化（调试用） */
  subscribeAll(fn) {
    return events.on('*', (payload, event) => {
      if (event && event.startsWith('state:')) fn(event.slice(6), payload);
    });
  }

  /* ---- UI 状态快捷方法 ---- */

  /** 标记一个加载中 key */
  loadingStart(key) {
    this._state.ui.loading.add(key);
    events.emit('state:ui', this._state.ui);
  }

  /** 结束一个加载中 key */
  loadingEnd(key) {
    this._state.ui.loading.delete(key);
    events.emit('state:ui', this._state.ui);
  }

  /** 某 key 是否加载中 */
  isLoading(key) {
    return this._state.ui.loading.has(key);
  }
}

/** 全局单例 */
export const store = new Store();

export default store;
