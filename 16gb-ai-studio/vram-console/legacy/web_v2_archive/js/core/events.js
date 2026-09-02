/**
 * GMae 指挥家 v2.0 - core/events.js
 * 事件总线：组件间通信的松耦合通道
 * 支持：on/off/once/emit、命名空间订阅、通配符事件
 * 用法：events.on('scene:switch', fn)；events.emit('scene:switch', payload)
 */

class EventBus {
  constructor() {
    /** @type {Map<string, Set<Function>>} */
    this._listeners = new Map();
    /** 带 once 标记的监听器 */
    this._once = new WeakSet();
  }

  /**
   * 订阅事件
   * @param {string} event 事件名，支持命名空间如 'scene:switch'
   * @param {Function} fn
   * @returns {Function} 取消订阅函数
   */
  on(event, fn) {
    if (!this._listeners.has(event)) this._listeners.set(event, new Set());
    this._listeners.get(event).add(fn);
    return () => this.off(event, fn);
  }

  /** 只订阅一次 */
  once(event, fn) {
    this._once.add(fn);
    return this.on(event, fn);
  }

  /** 取消订阅（不传 fn 则取消该事件全部监听） */
  off(event, fn) {
    const set = this._listeners.get(event);
    if (!set) return;
    if (fn) {
      set.delete(fn);
    } else {
      set.clear();
    }
    if (set.size === 0) this._listeners.delete(event);
  }

  /**
   * 触发事件
   * @param {string} event
   * @param {*} payload
   * @param {object} opts { wildcard: true } 触发 '*' 通配监听（默认开）
   */
  emit(event, payload, opts = {}) {
    const target = this._listeners.get(event);
    if (target) {
      for (const fn of [...target]) {
        try {
          if (this._once.has(fn)) {
            this._once.delete(fn);
            target.delete(fn);
          }
          fn(payload, event);
        } catch (err) {
          console.error(`[events] listener error on "${event}"`, err);
        }
      }
      if (target.size === 0) this._listeners.delete(event);
    }
    // 通配监听 '*'：收到所有事件
    if (opts.wildcard !== false) {
      const wildcard = this._listeners.get('*');
      if (wildcard && wildcard.size) {
        for (const fn of [...wildcard]) {
          try {
            fn(payload, event);
          } catch (err) {
            console.error('[events] wildcard listener error', err);
          }
        }
      }
    }
  }

  /** 清空全部监听（主要用于测试/热重置） */
  clear() {
    this._listeners.clear();
  }

  /** 某事件的监听数量 */
  count(event) {
    return this._listeners.get(event)?.size || 0;
  }
}

/** 全局单例 */
export const events = new EventBus();

export default events;
