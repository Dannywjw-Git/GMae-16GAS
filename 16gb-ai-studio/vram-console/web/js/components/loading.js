/**
 * GMae 指挥家 v2.0 - components/loading.js
 * 加载状态组件：Spinner、按钮加载、区块骨架屏
 */

import { el } from '../core/utils.js';

/** 行内 Spinner（用于按钮内部） */
export function spinner(size = 16) {
  return el(`<span class="spinner" style="width:${size}px;height:${size}px;border-width:${Math.max(2, Math.round(size / 8))}px"></span>`);
}

/**
 * 全屏/区块加载层
 * @param {string} text 提示文字
 * @returns {HTMLElement} 加载层节点（移除它即结束）
 */
export function overlay(text = '加载中…') {
  return el(`<div class="loading-overlay">
    <div class="loading-overlay__inner">
      ${spinner(32).outerHTML}
      <div class="loading-overlay__text"></div>
    </div>
  </div>`).querySelector('.loading-overlay');
}

/**
 * 骨架屏卡片（数据加载前的占位）
 * @param {number} count 卡片数量
 */
export function skeletonCards(count = 4) {
  const wrap = el('<div class="skeleton-grid"></div>');
  for (let i = 0; i < count; i++) {
    wrap.appendChild(el(`<div class="skeleton-card">
      <div class="skeleton skeleton--line" style="width:40%"></div>
      <div class="skeleton skeleton--title" style="width:70%"></div>
      <div class="skeleton skeleton--line" style="width:90%"></div>
      <div class="skeleton skeleton--line" style="width:60%"></div>
    </div>`));
  }
  return wrap;
}

/** 按钮加载态：禁用 + 显示 spinner */
export function btnLoading(btn, loadingText = '处理中…') {
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `${spinner(14).outerHTML} ${loadingText}`;
  return () => {
    btn.disabled = false;
    btn.innerHTML = original;
  };
}

export default { spinner, overlay, skeletonCards, btnLoading };
