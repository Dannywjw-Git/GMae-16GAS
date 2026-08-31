/**
 * GMae 指挥家 v2.0 - pages/models.js
 * 模型登记台（阶段 2）：卡片式展示 + 分类筛选 + 详情抽屉 + 扫描/登记
 * 蓝图 §11.4：模型信息分层（简称/简介/全称 tooltip/详情抽屉）
 */

import { store } from '../core/state.js';
import { api } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, escapeHtml, fmtMb } from '../core/utils.js';
import { drawer } from '../components/modal.js';

const CATEGORY_META = {
  llm: { label: '对话', icon: '💬' },
  image: { label: '出图', icon: '🎨' },
  video: { label: '视频', icon: '🎬' },
  audio: { label: '音乐', icon: '🎵' },
  embedding: { label: '嵌入', icon: '🔗' },
  reranker: { label: '重排', icon: '⚖️' },
  other: { label: '其他', icon: '📦' },
};

let currentFilter = 'all';

/* ========== 详情抽屉 ========== */

function showDetail(model) {
  const rows = [
    ['名称', model.full_name || model.name || model.id],
    ['出品方', model.vendor],
    ['发布时间', model.release],
    ['模态', model.modality || model.category],
    ['显存占用', fmtMb((model.vram_gb || 0) * 1024)],
    ['独占标记', model.exclusive ? '是（独占 GPU）' : '否'],
    ['工作流', model.workflow || '—'],
    ['Context', model.ctx ? `${model.ctx}` : '—'],
    ['安装状态', model.installed ? '已安装' : '未安装'],
  ];
  const body = el('<div class="model-detail"></div>');
  const list = el('<table class="table"></table>');
  list.innerHTML = `<thead><tr><th>属性</th><th>值</th></tr></thead><tbody></tbody>`;
  const tbody = list.querySelector('tbody');
  for (const [k, v] of rows) {
    const tr = el(`<tr><td class="text-muted">${escapeHtml(k)}</td><td>${v ? escapeHtml(String(v)) : '—'}</td></tr>`);
    tbody.appendChild(tr);
  }
  body.appendChild(list);
  if (model.detail) {
    body.appendChild(el(`<div class="model-detail__desc mt-md">${escapeHtml(model.detail)}</div>`));
  }
  drawer({ title: model.name || model.id, body, width: '440px' });
}

/* ========== 模型卡片 ========== */

function buildCard(model) {
  const meta = CATEGORY_META[model.category] || CATEGORY_META.other;
  const card = el(`<div class="model-card" title="${escapeHtml(model.full_name || model.name || '')}">
    <div class="model-card__head">
      <span class="model-card__icon">${meta.icon}</span>
      <span class="model-card__name"></span>
      <span class="tag tag--${model.installed ? 'ok' : 'muted'}">${model.installed ? '已装' : '未装'}</span>
    </div>
    <div class="model-card__desc"></div>
    <div class="model-card__foot">
      <span class="tag tag--muted">${meta.label}</span>
      <span class="model-card__vram">${fmtMb((model.vram_gb || 0) * 1024)}</span>
    </div>
  </div>`);
  card.querySelector('.model-card__name').textContent = model.name || model.id;
  card.querySelector('.model-card__desc').textContent = model.desc || model.detail || '';
  card.addEventListener('click', () => showDetail(model));
  return card;
}

/* ========== 筛选 ========== */

function buildFilterBar(models) {
  const cats = new Set(models.map((m) => m.category || 'other'));
  const bar = el('<div class="filter-bar flex gap-sm"></div>');
  const all = el(`<button class="btn btn--sm ${currentFilter === 'all' ? 'btn--primary' : 'btn--ghost'}" data-cat="all">全部 (${models.length})</button>`);
  all.addEventListener('click', () => { currentFilter = 'all'; rerenderCards(); });
  bar.appendChild(all);
  for (const c of cats) {
    const meta = CATEGORY_META[c] || CATEGORY_META.other;
    const count = models.filter((m) => m.category === c).length;
    const btn = el(`<button class="btn btn--sm ${currentFilter === c ? 'btn--primary' : 'btn--ghost'}" data-cat="${escapeHtml(c)}">${meta.icon} ${meta.label} (${count})</button>`);
    btn.addEventListener('click', () => { currentFilter = c; rerenderCards(); });
    bar.appendChild(btn);
  }
  return bar;
}

function renderCardGrid(models) {
  const grid = el('<div class="models-grid"></div>');
  const filtered = currentFilter === 'all' ? models : models.filter((m) => m.category === currentFilter);
  if (!filtered.length) {
    grid.appendChild(el(`<div class="card chart__empty">该分类暂无模型登记</div>`));
    return grid;
  }
  for (const m of filtered) grid.appendChild(buildCard(m));
  return grid;
}

/* ========== 页面主体 ========== */

function render() {
  const page = el(`<div class="page models-page">
    <div class="page-header flex justify-between items-center">
      <div>
        <div class="page-title">模型登记台</div>
        <div class="page-subtitle">一处登记，全局生效——点卡片看详情，扫新模型自动登记</div>
      </div>
      <div class="flex gap-sm">
        <button class="btn btn--primary" data-scan>🔍 扫描新模型</button>
        <button class="btn btn--ghost" data-refresh>刷新</button>
      </div>
    </div>
    <div class="flex-col gap-md">
      <div class="models-toolbar" data-toolbar></div>
      <div class="models-summary text-xs text-muted" data-summary></div>
      <div class="models-grid-wrap" data-grid></div>
    </div>
  </div>`);

  page.querySelector('[data-scan]').addEventListener('click', onScan);
  page.querySelector('[data-refresh]').addEventListener('click', load);
  load(page);
  return page;
}

async function load(page) {
  try {
    const data = await api.registry();
    store.set('registry', data);
    renderData(page, data);
  } catch (e) {
    const grid = page?.querySelector('[data-grid]');
    if (grid) grid.appendChild(el('<div class="card chart__empty">加载模型列表失败</div>'));
  }
}

function renderData(page, data) {
  if (!page.isConnected) return;
  const models = [...(data.ollama_models || []), ...(data.comfyui_models || [])];
  const toolbar = page.querySelector('[data-toolbar]');
  const summary = page.querySelector('[data-summary]');
  const gridWrap = page.querySelector('[data-grid]');
  empty(toolbar); empty(gridWrap);
  toolbar.appendChild(buildFilterBar(models));
  summary.textContent = `共 ${models.length} 个模型 · ${data.ollama_models?.length ?? 0} 对话/嵌入（ollama）+ ${data.comfyui_models?.length ?? 0} 生成（comfyui）· 更新 ${data.last_updated || '—'}`;
  gridWrap.appendChild(renderCardGrid(models));
}

/** 重新渲染卡片（筛选切换用） */
function rerenderCards() {
  const data = store.get('registry');
  if (!data) return;
  const gridWrap = document.querySelector('.models-grid-wrap');
  if (!gridWrap) return;
  const models = [...(data.ollama_models || []), ...(data.comfyui_models || [])];
  empty(gridWrap);
  gridWrap.appendChild(renderCardGrid(models));
  // 高亮筛选按钮
  document.querySelectorAll('.filter-bar [data-cat]').forEach((b) => {
    b.classList.toggle('btn--primary', b.dataset.cat === currentFilter);
    b.classList.toggle('btn--ghost', b.dataset.cat !== currentFilter);
  });
}

async function onScan() {
  const btn = document.querySelector('[data-scan]');
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = '扫描中…';
  try {
    const result = await api.scan();
    const found = result?.found || [];
    events.emit('toast', {
      type: found.length ? 'success' : 'info',
      message: found.length ? `发现 ${found.length} 个新模型，已自动登记` : '未发现新模型',
    });
    await load(document.querySelector('.models-page'));
  } catch (e) {
    events.emit('toast', { type: 'error', message: e.message });
  } finally {
    btn.disabled = false;
    btn.textContent = '🔍 扫描新模型';
  }
}

export default {
  title: '模型登记台',
  render,
};
