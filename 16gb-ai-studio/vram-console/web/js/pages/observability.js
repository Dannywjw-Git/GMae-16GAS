/**
 * GMae v2.0 - pages/observability.js
 * 观测中心：显存账本 / 服务健康 / 事件日志（三个Tab）
 *
 * 显存账本设计（恢复自 v2.1）：
 * - 8层显存分布：底噪→WSL2基础→桌面应用→Ollama→ComfyUI→Fooocus→其他→空闲
 * - 点击分段/图例可下钻展开对应进程组
 * - 进程分组：Ollama(可停模型) / ComfyUI(全量释放) / Fooocus(停容器) / 底噪(含桌面进程)
 * - vmwp(WSL2) 特殊处理：合并到容器基础开销
 * - desktop_vram API 获取 Windows 桌面进程显存
 */

import { api } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, escapeHtml, fmtMb, fmtPct } from '../core/utils.js';
import TabNav from '../components/TabNav.js';
import { confirm } from '../components/modal.js';

// 通用 API 请求（新 v1 端点直接用 fetch）
async function apiGet(path) {
  const token = localStorage.getItem('gm_api_token') || '';
  const headers = { 'X-API-Key': token };
  const resp = await fetch(path, { headers });
  const data = await resp.json();
  return data.data || data;
}

async function apiPost(path, body = {}) {
  const token = localStorage.getItem('gm_api_token') || '';
  const headers = { 'X-API-Key': token, 'Content-Type': 'application/json' };
  const resp = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) });
  const data = await resp.json();
  return data.data || data;
}

let page = null;
let currentTab = 'vram';
let pollTimer = null;
let healthData = null;
let eventsData = null;
let statusData = null;
let desktopVramData = null;

/* ========== 页面渲染 ========== */

export function render() {
  page = el(`<div class="page observability-page">
    <div class="page-header">
      <h1 class="page-title">观测中心</h1>
      <p class="page-subtitle">全栈可观测：显存账本 · 服务健康 · 事件日志</p>
    </div>
    <div data-tab-nav></div>
    <div data-tab-content></div>
  </div>`);

  const tab = TabNav.render({
    tabs: [
      { id: 'vram', label: '显存账本', icon: '📈' },
      { id: 'health', label: '服务健康', icon: '💚' },
      { id: 'events', label: '事件日志', icon: '📜' },
    ],
    default: 'vram',
    onChange: (id) => {
      currentTab = id;
      renderTab();
    },
  });
  page.querySelector('[data-tab-nav]').appendChild(tab.nav);
  return page;
}

export function onEnter() {
  startPolling();
  refresh();
}

export function onLeave() {
  stopPolling();
}

/* ========== 数据刷新 ========== */

async function refresh() {
  try {
    const [status, health, evts, desktop] = await Promise.all([
      api.status().catch(() => null),
      apiGet('/api/v1/health/services').catch(() => null),
      apiGet('/api/v1/events?limit=50').catch(() => null),
      api.desktopVram().catch(() => null),
    ]);
    statusData = status;
    healthData = health;
    eventsData = evts;
    desktopVramData = desktop;
    renderTab();
  } catch (err) {
    console.error('[observability] refresh error', err);
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(refresh, 10000);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/* ========== Tab 渲染 ========== */

function renderTab() {
  const slot = page?.querySelector('[data-tab-content]');
  if (!slot) return;
  empty(slot);

  if (currentTab === 'vram') renderVramTab(slot);
  else if (currentTab === 'health') renderHealthTab(slot);
  else if (currentTab === 'events') renderEventsTab(slot);
}

/* ========== Tab1: 显存账本（完整分层下钻） ========== */

function renderVramTab(slot) {
  if (!statusData?.gpu) {
    slot.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><p>加载中...</p></div>';
    return;
  }

  const container = el('<div class="observability-vram"></div>');

  // 1. 显存分布（8层分段，点击可下钻）
  container.appendChild(renderVramDistribution());

  // 2. 进程级显存明细（分组+可展开）
  container.appendChild(renderProcTable());

  slot.appendChild(container);
}

/* ---------- 显存分布（8层分段） ---------- */

function renderVramDistribution() {
  const gpu = statusData.gpu;
  const ledger = statusData.vram_ledger || {};
  const total = gpu.total_mb || 0;
  if (!total) return el('<div class="card">未检测到 GPU</div>');

  const ollamaMb = ledger.ollama_loaded_mb || 0;
  const comfyMb = ledger.comfy_loaded_mb || 0;
  const fooocusMb = statusData.containers?.fooocus ? 6.9 * 1024 : 0;
  const noiseMb = ledger.noise_mb || 1200;
  const actualUsed = ledger.actual_used_mb || gpu.used_mb || 0;

  // 从 helper 数据中拆分 vmwp（WSL2/Docker GPU直通）和桌面应用
  // 关键口径：
  // - vmwp 显存 = WSL2 内所有 GPU 进程总和（已包含 Ollama/ComfyUI/Fooocus）
  // - ollama/comfy/fooocus 的 mb 是从容器 API 获取的模型大小声明值
  // - 以 nvidia-smi 的 actualUsed 为唯一基准，各层声明值只用于细分归因
  let vmwpMb = 0;
  let desktopAppMb = 0;
  if (desktopVramData?.processes) {
    for (const p of desktopVramData.processes) {
      const mb = Number(p.MB) || 0;
      const pname = (p.Name || '').toLowerCase();
      if (pname.includes('vmwp')) {
        vmwpMb += mb;
      } else if (mb >= 1) {
        desktopAppMb += mb;
      }
    }
  }

  // WSL2 内部细分：如果模型声明值 > vmwp 实际显存，按比例缩放
  const knownContainerMb = ollamaMb + comfyMb + fooocusMb;
  let wsl2BaseMb, displayOllamaMb, displayComfyMb, displayFooocusMb;
  if (knownContainerMb <= 0) {
    wsl2BaseMb = vmwpMb;
    displayOllamaMb = displayComfyMb = displayFooocusMb = 0;
  } else if (knownContainerMb <= vmwpMb) {
    wsl2BaseMb = vmwpMb - knownContainerMb;
    displayOllamaMb = ollamaMb;
    displayComfyMb = comfyMb;
    displayFooocusMb = fooocusMb;
  } else {
    // 模型声明值 > vmwp 实际显存（如 Ollama 模型未全量加载），按比例缩放
    const scale = vmwpMb / knownContainerMb;
    wsl2BaseMb = 0;
    displayOllamaMb = ollamaMb * scale;
    displayComfyMb = comfyMb * scale;
    displayFooocusMb = fooocusMb * scale;
  }

  // 8层声明值（不含空闲）
  const declaredLayers = [
    { label: '底噪/系统', mb: noiseMb, color: 'var(--txt-tertiary)', group: '底噪 / 系统' },
    { label: 'WSL2/Docker基础', mb: wsl2BaseMb, color: '#795548', group: null },
    { label: '桌面应用', mb: desktopAppMb, color: '#607d8b', group: '底噪 / 系统' },
    { label: '对话模型', mb: displayOllamaMb, color: 'var(--primary)', group: 'Ollama · 对话模型' },
    { label: '生成引擎', mb: displayComfyMb, color: 'var(--ok)', group: 'ComfyUI · 生成引擎' },
    { label: 'Fooocus', mb: displayFooocusMb, color: '#9c27b0', group: 'Fooocus · Flux 出图' },
  ];

  // 以 actualUsed 为基准：声明值超额则按比例缩放，不足则差额放入"其他"
  const sumDeclared = declaredLayers.reduce((s, l) => s + l.mb, 0);
  let otherMb = 0;
  if (sumDeclared > actualUsed && actualUsed > 0) {
    const scale = actualUsed / sumDeclared;
    declaredLayers.forEach(l => l.mb *= scale);
  } else {
    otherMb = Math.max(actualUsed - sumDeclared, 0);
  }
  const freeMb = Math.max(total - actualUsed, 0);

  // 最终分段（加上其他和空闲）
  const segs = [
    ...declaredLayers,
    { label: '其他', mb: otherMb, color: 'var(--warn)', group: null },
    { label: '空闲', mb: freeMb, color: 'var(--line)', group: null },
  ];

  const util = gpu.utilization || 0;
  const utilColor = util > 80 ? 'var(--bad)' : util > 50 ? 'var(--warn)' : 'var(--ok)';

  const card = el(`<div class="card">
    <div class="card__header">
      <div class="card__title">显存分布</div>
      <div class="flex items-center gap-md">
        <div class="text-sm text-muted">GPU 利用率 <b style="color:${utilColor}">${util}%</b></div>
        <div class="text-sm text-muted">已用 ${fmtMb(actualUsed)} / ${fmtMb(total, 0)}</div>
      </div>
    </div>
    <div class="vram-dist">
      ${segs.filter(s => s.mb > 0).map(s => `
        <div class="vram-dist__seg" data-group="${escapeHtml(s.group || '')}"
          style="width:${(s.mb / total) * 100}%;background:${s.color};cursor:${s.group ? 'pointer' : 'default'}"
          title="${escapeHtml(s.label)} ${fmtMb(s.mb)}${s.group ? '（点击展开明细）' : ''}"></div>
      `).join('')}
    </div>
    <div class="vram-dist__legend flex gap-md mt-sm">
      ${segs.map(s => `
        <span class="text-xs text-muted" data-group="${escapeHtml(s.group || '')}"
          style="cursor:${s.group ? 'pointer' : 'default'}">
          <span class="vram-dist__dot" style="background:${s.color}"></span>
          ${escapeHtml(s.label)} ${fmtMb(s.mb)}
        </span>
      `).join('')}
    </div>
    ${ledger.note ? `<div class="text-xs mt-sm ${ledger.state === 'loading' || ledger.state === 'releasing' ? 'text-warn' : 'text-muted'}">${escapeHtml(ledger.note)}</div>` : ''}
  </div>`);

  // 点击分段或图例 → 展开对应分组并滚动定位
  card.querySelectorAll('[data-group]').forEach(el => {
    const groupName = el.getAttribute('data-group');
    if (!groupName) return;
    el.addEventListener('click', () => {
      const target = Array.from(document.querySelectorAll('.vram-group')).find(g =>
        g.querySelector('.vram-group__name')?.textContent === groupName
      );
      if (target) {
        if (!target.classList.contains('expanded')) {
          target.classList.add('expanded');
          const toggle = target.querySelector('.vram-group__toggle');
          if (toggle) toggle.textContent = '▼';
          let next = target.nextElementSibling;
          while (next && next.classList.contains('vram-group__child')) {
            next.style.display = '';
            next = next.nextElementSibling;
          }
        }
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.style.transition = 'background 0.3s';
        target.style.background = 'var(--primary-dim)';
        setTimeout(() => { target.style.background = ''; }, 800);
      }
    });
  });

  return card;
}

/* ---------- 进程级显存明细（分组+可展开） ---------- */

function renderProcTable() {
  const ledger = statusData.vram_ledger || {};
  const noiseMb = ledger.noise_mb || 1200;

  // === 收集桌面进程（过滤 vmwp 和 <1MB 小进程）===
  const desktopProcesses = [];
  const desktopMb = {};
  if (desktopVramData?.processes) {
    for (const p of desktopVramData.processes) {
      desktopMb[String(p.Pid)] = p.MB || 0;
      const pname = (p.Name || '').toLowerCase();
      if ((p.MB || 0) >= 1 && !pname.includes('vmwp')) {
        desktopProcesses.push({ name: p.Name, pid: p.Pid, mb: p.MB || 0 });
      }
    }
  }
  desktopProcesses.sort((a, b) => b.mb - a.mb);
  const MAX_DESKTOP_SHOW = 15;
  const desktopShown = desktopProcesses.slice(0, MAX_DESKTOP_SHOW);
  const desktopHiddenCount = desktopProcesses.length - desktopShown.length;

  // === 收集 Docker 容器组 ===
  const containerItems = [];

  // Ollama（对话模型，可单独 stop）
  const ollamaModels = statusData.ollama?.models || [];
  const ollamaMb = ollamaModels.reduce((s, m) => s + (Number(m.size_gb) || 0) * 1024, 0);
  if (ollamaMb > 0) {
    containerItems.push({
      type: 'group', group: 'ollama', name: 'Ollama · 对话模型',
      mb: ollamaMb, tag: 'Docker',
      children: ollamaModels.map(m => ({
        name: m.name, mb: (Number(m.size_gb) || 0) * 1024,
        canStop: true, stopAction: 'ollama_stop',
      })),
      canFree: true, freeAction: 'ollama_free',
    });
  }

  // ComfyUI（生成引擎，只能 /free 全量卸载）
  const comfyData = statusData.comfyui_models || {};
  const comfyModelsList = comfyData.models || [];
  const comfyTorchMb = Number(comfyData.torch_vram_used_mb) || 0;
  if (comfyTorchMb > 1024) {
    let children = comfyModelsList.map(m => ({
      name: m.name || m.id, mb: (Number(m.vram_gb) || 0) * 1024,
      canStop: false,
    }));
    if (children.length === 0) {
      children = [{ name: '运行中模型（工作流未识别，如 Music3 / 自定义节点）', mb: comfyTorchMb, canStop: false }];
    }
    containerItems.push({
      type: 'group', group: 'comfyui', name: 'ComfyUI · 生成引擎',
      mb: comfyTorchMb, tag: 'Docker',
      children,
      canFree: true, freeAction: 'comfy_free',
    });
  }

  // Fooocus（固定 6.9G，可停止容器）
  if (statusData.containers?.fooocus) {
    containerItems.push({
      type: 'process', name: 'Fooocus · Flux 出图',
      mb: 6.9 * 1024, tag: 'Docker',
      canStop: true, stopAction: 'container_stop', container: 'fooocus',
    });
  }

  containerItems.sort((a, b) => b.mb - a.mb);

  // === 未登记进程（unknown_pids，尝试匹配 desktopMb）===
  const unknown = statusData.gpu_processes?.unknown_pids || [];
  for (const pid of unknown) {
    const mb = desktopMb[String(pid)] || 0;
    if (mb > 0) {
      desktopProcesses.push({ name: '未知进程', pid, mb, isUnknown: true });
    }
  }

  // === 构建表格 ===
  const card = el(`<div class="card">
    <div class="card__header">
      <div class="card__title">进程级显存明细</div>
      <div class="text-xs text-muted">Docker 容器分层 · 底噪可展开 · ComfyUI 仅支持全量释放 · vmwp(WSL2) 已合并至容器</div>
    </div>
    <div class="data-table">
      <table>
        <thead><tr><th style="width:24px"></th><th>进程 / 模型</th><th>来源</th><th class="num">显存</th><th>操作</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>`);
  const tbody = card.querySelector('tbody');

  const totalItems = containerItems.length + 1;
  if (totalItems === 1 && desktopProcesses.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding:24px">暂无占用显存的进程</td></tr>';
    return card;
  }

  // --- Docker 容器组 ---
  for (const item of containerItems) {
    if (item.type === 'group') {
      const tr = el(`<tr class="vram-group">
        <td><span class="vram-group__toggle">▶</span></td>
        <td><span class="vram-group__name">${escapeHtml(item.name)}</span> <span class="text-xs text-muted">(${item.children.length} 个模型)</span></td>
        <td><span class="tag tag--primary">${escapeHtml(item.tag)}</span></td>
        <td class="num"><b>${fmtMb(item.mb)}</b></td>
        <td></td>
      </tr>`);
      if (item.canFree) {
        const freeBtn = el('<button class="btn btn--sm btn--warn">释放</button>');
        freeBtn.addEventListener('click', (e) => { e.stopPropagation(); freeGroup(item); });
        tr.children[4].appendChild(freeBtn);
      }
      tbody.appendChild(tr);

      // 子模型行
      for (const child of item.children) {
        const ctr = el(`<tr class="vram-group__child" style="display:none">
          <td></td>
          <td style="padding-left:32px">└ ${escapeHtml(child.name)}</td>
          <td><span class="tag tag--muted">模型</span></td>
          <td class="num">${fmtMb(child.mb)}</td>
          <td></td>
        </tr>`);
        if (child.canStop) {
          const stopBtn = el('<button class="btn btn--sm btn--danger">停止</button>');
          stopBtn.addEventListener('click', (e) => { e.stopPropagation(); stopChildModel(item, child); });
          ctr.children[4].appendChild(stopBtn);
        } else {
          ctr.children[4].innerHTML = '<span class="text-xs text-muted">仅展示</span>';
        }
        tbody.appendChild(ctr);
      }

      tr.addEventListener('click', () => {
        const expanded = tr.classList.toggle('expanded');
        tr.querySelector('.vram-group__toggle').textContent = expanded ? '▼' : '▶';
        let next = tr.nextElementSibling;
        while (next && next.classList.contains('vram-group__child')) {
          next.style.display = expanded ? '' : 'none';
          next = next.nextElementSibling;
        }
      });
    } else {
      // 普通容器进程行（Fooocus 等）
      const tr = el(`<tr>
        <td></td>
        <td>${escapeHtml(item.name)}</td>
        <td><span class="tag tag--primary">${escapeHtml(item.tag)}</span></td>
        <td class="num">${fmtMb(item.mb)}</td>
        <td></td>
      </tr>`);
      if (item.canStop && item.stopAction === 'container_stop') {
        const stopBtn = el('<button class="btn btn--sm btn--danger">停止</button>');
        stopBtn.addEventListener('click', (e) => { e.stopPropagation(); stopContainer(item.container, item.name); });
        tr.children[4].appendChild(stopBtn);
      }
      tbody.appendChild(tr);
    }
  }

  // --- 底噪 / 系统（可展开，含桌面进程）---
  const desktopTotalMb = desktopProcesses.reduce((s, p) => s + p.mb, 0);
  const fixedOverheadMb = Math.max(noiseMb - desktopTotalMb, 0);
  const fixedLabel = fixedOverheadMb > 0 ? fmtMb(fixedOverheadMb) : '已含在桌面进程中';
  const noiseTr = el(`<tr class="vram-group vram-noise">
    <td><span class="vram-group__toggle">▶</span></td>
    <td><span class="vram-group__name">底噪 / 系统</span> <span class="text-xs text-muted">(固定开销 ${fixedLabel} + 桌面进程 ${desktopProcesses.length} 个)</span></td>
    <td><span class="tag tag--muted">系统</span></td>
    <td class="num"><b>${fmtMb(noiseMb)}</b></td>
    <td></td>
  </tr>`);
  tbody.appendChild(noiseTr);

  // 底噪子行：固定开销说明
  const fixedTr = el(`<tr class="vram-group__child vram-noise__fixed" style="display:none">
    <td></td>
    <td style="padding-left:32px">└ GPU驱动 + WSL2基础 + Docker开销</td>
    <td><span class="tag tag--muted">固定</span></td>
    <td class="num">${fixedLabel}</td>
    <td><span class="text-xs text-muted">不可结束</span></td>
  </tr>`);
  tbody.appendChild(fixedTr);

  // 底噪子行：桌面进程
  for (const p of desktopShown) {
    const pTr = el(`<tr class="vram-group__child" style="display:none">
      <td></td>
      <td style="padding-left:32px">└ ${escapeHtml(p.name)}${p.isUnknown ? ' (PID ' + p.pid + ')' : ''}</td>
      <td><span class="tag ${p.isUnknown ? 'tag--bad' : 'tag--muted'}">${p.isUnknown ? '未登记' : 'Windows'}</span></td>
      <td class="num">${fmtMb(p.mb)}</td>
      <td></td>
    </tr>`);
    const killBtn = el('<button class="btn btn--sm btn--danger">结束</button>');
    killBtn.addEventListener('click', (e) => { e.stopPropagation(); killDesktopProcess(p.pid, p.name); });
    pTr.children[4].appendChild(killBtn);
    tbody.appendChild(pTr);
  }

  // 隐藏的小进程提示
  if (desktopHiddenCount > 0) {
    const hiddenTr = el(`<tr class="vram-group__child" style="display:none">
      <td></td>
      <td style="padding-left:32px">└ 还有 ${desktopHiddenCount} 个小进程（按显存降序已折叠）</td>
      <td><span class="tag tag--muted">Windows</span></td>
      <td class="num text-muted">—</td>
      <td></td>
    </tr>`);
    tbody.appendChild(hiddenTr);
  }

  // 底噪展开/折叠
  noiseTr.addEventListener('click', () => {
    const expanded = noiseTr.classList.toggle('expanded');
    noiseTr.querySelector('.vram-group__toggle').textContent = expanded ? '▼' : '▶';
    let next = noiseTr.nextElementSibling;
    while (next && next.classList.contains('vram-group__child')) {
      next.style.display = expanded ? '' : 'none';
      next = next.nextElementSibling;
    }
  });

  return card;
}

/* ========== 显存操作函数 ========== */

async function freeGroup(item) {
  const ok = await confirm({
    title: '释放模型组',
    message: `确定要释放「${escapeHtml(item.name)}」的所有模型吗？${item.group === 'comfyui' ? 'ComfyUI 将通过 /free 全量卸载所有模型。' : 'Ollama 将逐个停止所有已加载模型。'}`,
    okText: '全部释放',
    danger: true,
  });
  if (!ok) return;
  try {
    if (item.freeAction === 'ollama_free') {
      for (const m of item.children) {
        try { await api.model(m.name, 'stop'); } catch (e) { /* 个别失败不影响 */ }
      }
    } else if (item.freeAction === 'comfy_free') {
      await api.free();
    }
    events.emit('toast', { type: 'success', message: `已释放 ${item.name}` });
    await refresh();
  } catch (e) {
    events.emit('toast', { type: 'error', message: `释放失败：${e.message}` });
  }
}

async function stopChildModel(group, child) {
  if (!child.canStop) return;
  const ok = await confirm({
    title: '停止模型',
    message: `确定要停止模型「${escapeHtml(child.name)}」吗？`,
    okText: '停止',
    danger: true,
  });
  if (!ok) return;
  try {
    if (child.stopAction === 'ollama_stop') {
      await api.model(child.name, 'stop');
    }
    events.emit('toast', { type: 'success', message: `已停止 ${child.name}` });
    await refresh();
  } catch (e) {
    events.emit('toast', { type: 'error', message: `停止失败：${e.message}` });
  }
}

async function stopContainer(name, label) {
  const ok = await confirm({
    title: '停止容器',
    message: `确定要停止容器「${escapeHtml(label || name)}」吗？容器内所有服务将终止。`,
    okText: '停止容器',
    danger: true,
  });
  if (!ok) return;
  try {
    await api.containerStop(name);
    events.emit('toast', { type: 'success', message: `已停止容器 ${name}` });
    await refresh();
  } catch (e) {
    events.emit('toast', { type: 'error', message: `停止失败：${e.message}` });
  }
}

async function killDesktopProcess(pid, name) {
  const ok = await confirm({
    title: '强制结束进程',
    message: `确定要结束进程「${escapeHtml(name || '')}」(PID ${pid}) 吗？此操作不可恢复。`,
    okText: '结束进程',
    danger: true,
  });
  if (!ok) return;
  try {
    await api.desktopKill(pid);
    events.emit('toast', { type: 'success', message: `已结束进程 ${name || ''} (PID ${pid})` });
    await refresh();
  } catch (e) {
    events.emit('toast', { type: 'error', message: `结束失败：${e.message}` });
  }
}

/* ========== Tab2: 服务健康 ========== */

function renderHealthTab(slot) {
  if (!healthData?.services) {
    slot.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><p>加载中...</p></div>';
    return;
  }

  const services = Object.entries(healthData.services);
  const summary = healthData.summary || {};

  const container = el(`<div class="observability-health">
    <div class="status-card-grid" style="grid-template-columns:repeat(4,1fr)">
      <div class="status-card" data-status="ok">
        <div class="status-card__header"><span>总计</span></div>
        <div class="status-card__value">${summary.total || 0}</div>
      </div>
      <div class="status-card" data-status="ok">
        <div class="status-card__header"><span>运行中</span></div>
        <div class="status-card__value text-ok">${summary.running || 0}</div>
      </div>
      <div class="status-card" data-status="warning">
        <div class="status-card__header"><span>已停止</span></div>
        <div class="status-card__value text-warn">${summary.stopped || 0}</div>
      </div>
      <div class="status-card" data-status="error">
        <div class="status-card__header"><span>不可达</span></div>
        <div class="status-card__value text-bad">${summary.unreachable || 0}</div>
      </div>
    </div>

    <div class="card">
      <div class="card__header">
        <div class="card__title">服务列表 (${services.length})</div>
        <button class="btn btn--sm btn--primary" data-action="probe-all">立即探测</button>
      </div>
      <div class="data-table">
        <table>
          <thead>
            <tr><th>服务</th><th>类型</th><th>状态</th><th>延迟</th><th>错误率</th><th>最后检查</th><th>操作</th></tr>
          </thead>
          <tbody>
            ${services.length === 0 ? '<tr><td colspan="7" class="text-muted text-center">无监控服务</td></tr>' :
              services.map(([sid, svc]) => {
                const status = svc.status || 'unknown';
                const statusLabel = { running: '运行中', stopped: '已停止', unreachable: '不可达', timeout: '超时', unknown: '未知' }[status] || status;
                const statusCls = { running: 'text-ok', stopped: 'text-muted', unreachable: 'text-bad', timeout: 'text-warn', unknown: 'text-muted' }[status] || '';
                const latency = svc.latency_ms != null ? `${svc.latency_ms}ms` : '-';
                const errorRate = svc.error_rate != null ? fmtPct(svc.error_rate * 100) : '-';
                const lastCheck = svc.last_check ? new Date(svc.last_check * 1000).toLocaleTimeString() : '-';
                return `
                  <tr>
                    <td><strong>${svc.name || sid}</strong><div class="text-xs text-muted">${svc.container || svc.url || ''}</div></td>
                    <td>${svc.type || '-'}</td>
                    <td class="${statusCls}">● ${statusLabel}</td>
                    <td class="font-mono">${latency}</td>
                    <td class="font-mono">${errorRate}</td>
                    <td class="text-xs">${lastCheck}</td>
                    <td><button class="btn btn--xs btn--ghost" data-probe-id="${sid}">探测</button></td>
                  </tr>
                `;
              }).join('')
            }
          </tbody>
        </table>
      </div>
    </div>
  </div>`);

  container.querySelector('[data-action="probe-all"]')?.addEventListener('click', async () => {
    try {
      await apiPost('/api/v1/health/probe', {});
      events.emit('toast', { type: 'success', message: '已触发全量探测' });
      refresh();
    } catch (err) {
      events.emit('toast', { type: 'error', message: '探测失败：' + err.message });
    }
  });

  container.querySelectorAll('[data-probe-id]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const sid = btn.dataset.probeId;
      try {
        await apiPost('/api/v1/health/probe', { id: sid });
        events.emit('toast', { type: 'success', message: `已探测 ${sid}` });
        refresh();
      } catch (err) {
        events.emit('toast', { type: 'error', message: '探测失败：' + err.message });
      }
    });
  });

  slot.appendChild(container);
}

/* ========== Tab3: 事件日志 ========== */

function renderEventsTab(slot) {
  if (!eventsData) {
    slot.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><p>加载中...</p></div>';
    return;
  }

  const evts = Array.isArray(eventsData) ? eventsData : [];

  const container = el(`<div class="observability-events">
    <div class="card">
      <div class="events-filter">
        <select class="form-input" data-filter="level">
          <option value="">全部级别</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="critical">Critical</option>
        </select>
        <select class="form-input" data-filter="service">
          <option value="">全部服务</option>
          ${[...new Set(evts.map(e => e.service).filter(Boolean))].map(s => `<option value="${s}">${s}</option>`).join('')}
        </select>
        <input type="text" class="form-input" data-filter="keyword" placeholder="搜索关键词..." style="flex:1">
        <button class="btn btn--sm btn--primary" data-action="refresh">刷新</button>
      </div>
    </div>

    <div class="card">
      <div class="card__title">事件流 (${evts.length})</div>
      <div class="events-list">
        ${evts.length === 0 ? '<div class="text-muted text-center py-4">暂无事件</div>' :
          evts.map(e => {
            const levelCls = { info: 'event--info', warning: 'event--warning', error: 'event--error', critical: 'event--critical' }[e.level] || '';
            const time = e.ts ? new Date(e.ts).toLocaleString() : '-';
            const meta = e.metadata && Object.keys(e.metadata).length > 0
              ? `<details class="event-meta"><summary>详情</summary><pre>${JSON.stringify(e.metadata, null, 2)}</pre></details>`
              : '';
            return `
              <div class="event-item ${levelCls}">
                <div class="event-item__time">${time}</div>
                <div class="event-item__level">${e.level?.toUpperCase()}</div>
                <div class="event-item__service">${e.service || '-'}</div>
                <div class="event-item__content">
                  <div class="event-item__type">${e.event_type}</div>
                  <div class="event-item__msg">${e.message || ''}</div>
                  ${meta}
                </div>
              </div>
            `;
          }).join('')
        }
      </div>
    </div>
  </div>`);

  container.querySelectorAll('[data-filter]').forEach(el => {
    el.addEventListener('change', () => applyFilter(container));
    el.addEventListener('input', () => applyFilter(container));
  });
  container.querySelector('[data-action="refresh"]')?.addEventListener('click', refresh);

  slot.appendChild(container);
}

function applyFilter(container) {
  const level = container.querySelector('[data-filter="level"]').value;
  const service = container.querySelector('[data-filter="service"]').value;
  const keyword = container.querySelector('[data-filter="keyword"]').value.toLowerCase();

  container.querySelectorAll('.event-item').forEach(item => {
    let show = true;
    if (level && !item.classList.contains(`event--${level}`)) show = false;
    if (service && !item.querySelector('.event-item__service')?.textContent.includes(service)) show = false;
    if (keyword && !item.textContent.toLowerCase().includes(keyword)) show = false;
    item.style.display = show ? '' : 'none';
  });
}

export default { render, onEnter, onLeave };
