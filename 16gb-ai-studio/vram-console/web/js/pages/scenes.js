/**
 * GMae 指挥家 v2.0 - pages/scenes.js
 * 场景页（阶段 3）：一键切换整套容器状态（蓝图 §11.2 场景化）
 * - 场景卡片网格：图标 + 名称 + 显存预算 + 模式 + 独占标记 + 当前高亮
 * - 点击切换 → POST /api/scene，逐步渲染 actions 日志，120s 超时保护
 * - 对话态下显示模型组合切换（ollama combos）
 * 数据源：/api/registry（scenes/ollama_combos）+ /api/status（当前场景）
 */

import { store } from '../core/state.js';
import { api } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, escapeHtml } from '../core/utils.js';

const POLL_INTERVAL = 15000;
let pollTimer = null;
let unsubscribe = null;

/* 场景展示元数据（registry 只存 label/budget/containers，图标/模式/提示前端补充） */
const SCENE_ICONS = { dialogue: '💬', comfy: '🎨', h3: '🎬', fooocus: '🖼️', music: '🎵', game: '🎮' };
const SCENE_MODES = { comfy: '🎨画图 · 🎵写歌 · 🎬视频', fooocus: '零门槛画图 · 用毕必停' };
const SCENE_TIPS = {
  dialogue: '停 Fooocus + 停 ComfyUI → 9B 按需自动加载',
  comfy: 'ComfyUI 一个容器干三件事：画图/写歌/视频，换活就换模型',
  h3: '视频生成态（Wan2.2），独占全卡',
  fooocus: '停 ComfyUI → 启 Fooocus（预加载 1-2 分钟）→ 用毕必停',
  music: '音乐生成态（Music3），独占全卡',
  game: '停 ComfyUI/Fooocus → 释放显存给游戏',
};

/* 组合展示名 / 上下文窗口 */
const COMBO_NAMES = {
  '9b': '9B 主力', '0.6b': '0.6B 轻量', 'qwythos-9b': 'Qwythos 9B',
  'darkidol-8b': 'Darkidol 8B', none: '休眠',
};
const COMBO_CTX = { '9b': '16K', '0.6b': '16K', 'qwythos-9b': '8K', 'darkidol-8b': '8K', none: '-' };
const COMBO_REC = { '9b': true };

let page = null;
let registry = null;
let busy = false;
let switchTimer = null;

/* ========== 场景切换 ========== */

function setBusy(v) {
  busy = v;
  if (!page) return;
  page.querySelectorAll('[data-scene]').forEach((c) => c.classList.toggle('is-busy', v));
}

function showStatus(html) {
  const s = page?.querySelector('[data-scene-status]');
  if (s) s.innerHTML = html;
}

function renderLog(actions) {
  const slot = page?.querySelector('[data-scene-log]');
  if (!slot) return;
  empty(slot);
  if (!Array.isArray(actions) || !actions.length) {
    slot.appendChild(el('<div class="scene-log__item text-muted">无执行步骤</div>'));
    return;
  }
  for (const a of actions) {
    const ok = a.rc === 0;
    const out = (a.output || '').split('\n').pop();
    slot.appendChild(el(`<div class="scene-log__item ${ok ? '' : 'is-err'}">
      <span class="scene-log__mark">${ok ? '✔' : '✘'}</span>
      <span class="scene-log__step">${escapeHtml(a.step)}</span>
      <span class="scene-log__rc text-muted">rc=${a.rc}${out ? ` · ${escapeHtml(out)}` : ''}</span>
    </div>`));
  }
  slot.scrollTop = slot.scrollHeight;
}

async function switchScene(id) {
  if (busy) return;
  const s = registry?.scenes?.[id];
  if (!s) return;
  setBusy(true);
  showStatus(`<span class="text-warn">⏳ 正在切换到「${s.label}」…（停止/启动容器，约 15-60 秒）</span>`);
  page.querySelector('[data-scene-log]') && empty(page.querySelector('[data-scene-log]'));

  // 超时保护：120 秒后强制重置，防止 API 挂起
  switchTimer = setTimeout(() => {
    setBusy(false);
    showStatus('<span class="text-bad">✘ 切换超时（>120秒），已重置状态，可重试</span>');
    events.emit('toast', { type: 'error', message: '场景切换超时，请重试' });
  }, 120000);

  try {
    const d = await api.scene(id);
    clearTimeout(switchTimer);
    renderLog(d.actions);
    if (d.ok) {
      showStatus(`<span class="text-ok">✅ 已切换到「${s.label}」</span>`);
      renderScenes(id);  // 立即更新"当前"标记，不依赖 store 订阅延迟
      renderCombos(id);
    } else {
      showStatus(`<span class="text-bad">❌ 切换异常：${s.label}</span>`);
      events.emit('toast', { type: 'error', message: `场景切换失败：${s.label}` });
    }
    await refresh();
  } catch (err) {
    clearTimeout(switchTimer);
    showStatus(`<span class="text-bad">✘ 请求失败：${escapeHtml(err.message)}</span>`);
  } finally {
    setBusy(false);
  }
}

/* ========== 组合切换（仅对话态） ========== */

function currentCombo(models) {
  const names = (models || []).map((m) => (m.model || m.name || ''));
  const hit = (key) => names.some((n) => n.includes(key));
  if (hit('qwen3.5:9b') || hit('qwen3.5-9b')) return '9b';
  if (hit('qwythos-9b')) return 'qwythos-9b';
  if (hit('darkidol-8b')) return 'darkidol-8b';
  if (hit('qwen3:0.6b')) return '0.6b';
  return 'none';
}

async function switchCombo(id) {
  if (busy) return;
  const combos = registry?.ollama_combos || {};
  const c = combos[id];
  if (!c) return;
  setBusy(true);
  const label = COMBO_NAMES[id] || id;
  showStatus(`<span class="text-warn">⏳ 切换组合「${label}」…</span>`);
  try {
    const d = await api.combo(id);
    renderLog(d.actions);
    showStatus(d.ok
      ? `<span class="text-ok">✅ 组合完成：${label}</span>`
      : `<span class="text-bad">❌ 组合异常：${label}</span>`);
    if (d.ok) renderCombos(store.get('status')?.scene);  // 立即刷新组合状态
    await refresh();
  } catch (err) {
    showStatus(`<span class="text-bad">✘ 请求失败：${escapeHtml(err.message)}</span>`);
  } finally {
    setBusy(false);
  }
}

/* ========== 渲染 ========== */

function renderScenes(currentScene) {
  const grid = page.querySelector('[data-scenes]');
  if (!grid) return;
  empty(grid);
  const scenes = registry?.scenes || {};
  const entries = Object.entries(scenes);
  if (!entries.length) {
    grid.appendChild(el('<div class="text-muted">暂无场景配置（registry.scenes 为空）</div>'));
    return;
  }
  for (const [id, s] of entries) {
    const icon = SCENE_ICONS[id] || '📦';
    const label = s.label || id;
    const vram = s.vram_budget_gb != null ? `~${s.vram_budget_gb}G` : '?';
    const modes = SCENE_MODES[id] || '';
    const tip = SCENE_TIPS[id] || (s.containers?.length ? `容器：${s.containers.join(', ')}` : '');
    const active = id === currentScene;
    const card = el(`<button class="scene-card ${active ? 'scene-card--active' : ''}" data-scene="${id}" title="${escapeHtml(tip)}">
      <div class="scene-card__icon">${icon}</div>
      <div class="scene-card__name">${escapeHtml(label)}</div>
      ${modes ? `<div class="scene-card__modes">${escapeHtml(modes)}</div>` : ''}
      <div class="scene-card__foot">
        <span class="scene-card__vram">${vram}</span>
        ${s.exclusive ? '<span class="tag tag--bad">独占全卡</span>' : ''}
        ${active ? '<span class="tag tag--ok">当前</span>' : ''}
      </div>
    </button>`);
    grid.appendChild(card);
  }
}

function renderCombos(scene) {
  const slot = page.querySelector('[data-combos]');
  if (!slot) return;
  const isDialogue = scene === 'dialogue';
  slot.classList.toggle('hidden', !isDialogue);
  if (!isDialogue) return;
  empty(slot);
  const combos = registry?.ollama_combos || {};
  const models = store.get('status')?.ollama?.models || [];
  const cur = currentCombo(models);
  const pills = el('<div class="combo-pills flex gap-sm"></div>');
  for (const [id, c] of Object.entries(combos)) {
    const name = COMBO_NAMES[id] || id;
    const ctx = COMBO_CTX[id] || '-';
    const rec = COMBO_REC[id] ? ' ★' : '';
    const active = id === cur;
    pills.appendChild(el(`<button class="combo-pill ${active ? 'combo-pill--active' : ''}" data-combo="${id}"
        title="${escapeHtml(`加载：${(c.load || []).join(', ') || '全部卸载'} · ctx ${ctx}`)}">
      ${escapeHtml(name)}${rec}<span class="combo-pill__ctx">${ctx}</span>
    </button>`));
  }
  slot.appendChild(el('<div class="scene-combos__label text-xs text-muted mb-sm">对话模型组合（仅对话态）</div>'));
  slot.appendChild(pills);
  pills.addEventListener('click', (e) => {
    const p = e.target.closest('[data-combo]');
    if (p && !busy) switchCombo(p.dataset.combo);
  });
}

/* ========== 页面骨架 ========== */

function render() {
  page = el(`<div class="page scenes-page">
    <div class="page-header flex justify-between items-center">
      <div>
        <div class="page-title">场景</div>
        <div class="page-subtitle">一套场景 = 一套容器状态 + 显存预算，一键切换</div>
      </div>
      <div class="text-xs text-muted font-mono" data-scene-status></div>
    </div>
    <div class="flex-col gap-lg">
      <div class="scene-grid" data-scenes></div>
      <div data-combos class="scene-combos"></div>
      <div class="scene-log" data-scene-log></div>
    </div>
  </div>`);
  const grid = page.querySelector('[data-scenes]');
  grid.addEventListener('click', (e) => {
    const card = e.target.closest('[data-scene]');
    if (card) switchScene(card.dataset.scene);
  });
  return page;
}

/* ========== 数据加载 ========== */

async function refresh() {
  try {
    const status = await api.status();
    store.set('status', status);
  } catch { /* api:error 已广播 */ }
}

async function load() {
  try {
    registry = await api.registry();
  } catch { registry = null; }
  const status = store.get('status');
  renderScenes(status?.scene);
  renderCombos(status?.scene);
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(refresh, POLL_INTERVAL);
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/* ========== 页面注册 ========== */

export default {
  title: '场景',
  render,
  onEnter: () => {
    load();
    refresh();
    startPolling();
    unsubscribe = store.subscribe('status', (status) => {
      renderScenes(status?.scene);
      renderCombos(status?.scene);
    });
  },
  onLeave: () => {
    stopPolling();
    if (unsubscribe) { unsubscribe(); unsubscribe = null; }
    if (switchTimer) { clearTimeout(switchTimer); switchTimer = null; }
  },
};
