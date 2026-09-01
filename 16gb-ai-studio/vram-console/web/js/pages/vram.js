/**
 * GMae 指挥家 v2.1 - pages/vram.js
 * 显存账本：Docker容器分层（模型可下钻）+ 底噪（可展开含桌面进程）+ 趋势(GB) + GPU利用率
 * 层级原则：不重复计算、操作能力与技术现实匹配、底噪=无法归因的剩余、全动态无硬编码
 */

import { store } from '../core/state.js';
import { api } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, escapeHtml, fmtMb, fmtTs, fmtRelative } from '../core/utils.js';
import { lineChart } from '../components/chart.js';
import { confirm } from '../components/modal.js';

const POLL_INTERVAL = 10000;
let pollTimer = null;
const history = [];

/* ========== 显存分布（底噪最左） ========== */

function renderDistribution(status, desktopVram) {
  const gpu = status?.gpu;
  const ledger = status?.vram_ledger;
  const total = gpu?.total_mb || 0;
  if (!total) return el('<div class="card chart__empty">未检测到 GPU</div>');

  const ollamaMb = ledger?.ollama_loaded_mb || 0;
  const comfyMb = ledger?.comfy_loaded_mb || 0;
  const fooocusMb = status?.containers?.fooocus ? 6.9 * 1024 : 0;
  const noiseMb = ledger?.noise_mb || 1200;
  const actualUsed = ledger?.actual_used_mb || gpu?.used_mb || 0;

  // 从 helper 数据中拆分 vmwp（WSL2/Docker GPU直通基础开销）和桌面应用
  let vmwpMb = 0;
  let desktopAppMb = 0;
  if (desktopVram?.processes) {
    for (const p of desktopVram.processes) {
      const mb = Number(p.MB) || 0;
      const pname = (p.Name || '').toLowerCase();
      if (pname.includes('vmwp')) {
        vmwpMb += mb;
      } else if (mb >= 1) {
        desktopAppMb += mb;
      }
    }
  }

  const otherMb = Math.max(actualUsed - noiseMb - ollamaMb - comfyMb - fooocusMb - vmwpMb - desktopAppMb, 0);
  const freeMb = Math.max(total - actualUsed, 0);

  // 底噪永远在最左，按层级：底噪 → WSL2基础 → 桌面应用 → Ollama → ComfyUI → Fooocus → 其他 → 空闲
  // group 字段对应进程表中的分组名，点击可展开并定位
  const segs = [
    { label: '底噪/系统', mb: noiseMb, color: 'var(--txt-tertiary)', group: '底噪 / 系统' },
    { label: 'WSL2/Docker基础', mb: vmwpMb, color: '#795548', group: null },
    { label: '桌面应用', mb: desktopAppMb, color: '#607d8b', group: '桌面进程 / 应用' },
    { label: '对话模型', mb: ollamaMb, color: 'var(--primary)', group: 'Ollama · 对话模型' },
    { label: '生成引擎', mb: comfyMb, color: 'var(--ok)', group: 'ComfyUI · 生成引擎' },
    { label: 'Fooocus', mb: fooocusMb, color: '#9c27b0', group: 'Fooocus · Flux 出图' },
    { label: '其他', mb: otherMb, color: 'var(--warn)', group: null },
    { label: '空闲', mb: freeMb, color: 'var(--line)', group: null },
  ];

  const util = gpu?.utilization || 0;
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
      ${segs.filter(s => s.mb > 0).map(s => `<div class="vram-dist__seg" data-group="${escapeHtml(s.group || '')}" style="width:${(s.mb / total) * 100}%;background:${s.color};cursor:${s.group ? 'pointer' : 'default'}" title="${escapeHtml(s.label)} ${fmtMb(s.mb)}${s.group ? '（点击展开明细）' : ''}"></div>`).join('')}
    </div>
    <div class="vram-dist__legend flex gap-md mt-sm">
      ${segs.map(s => `<span class="text-xs text-muted" data-group="${escapeHtml(s.group || '')}" style="cursor:${s.group ? 'pointer' : 'default'}"><span class="vram-dist__dot" style="background:${s.color}"></span>${escapeHtml(s.label)} ${fmtMb(s.mb)}</span>`).join('')}
    </div>
    ${ledger?.note ? `<div class="text-xs mt-sm ${ledger.state === 'loading' || ledger.state === 'releasing' ? 'text-warn' : 'text-muted'}">${escapeHtml(ledger.note)}</div>` : ''}
  </div>`);

  // 点击进度条段或图例 → 展开对应分组并滚动定位
  card.querySelectorAll('[data-group]').forEach(el => {
    const groupName = el.getAttribute('data-group');
    if (!groupName) return;
    el.addEventListener('click', () => {
      const target = Array.from(document.querySelectorAll('.vram-group')).find(g =>
        g.querySelector('.vram-group__name')?.textContent === groupName
      );
      if (target) {
        // 展开
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
        // 滚动定位
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // 高亮闪烁
        target.style.transition = 'background 0.3s';
        target.style.background = 'var(--primary-dim)';
        setTimeout(() => { target.style.background = ''; }, 800);
      }
    });
  });

  return card;
}

/* ========== 进程表（Docker容器分层 + 底噪可展开） ========== */

function renderProcTable(status, desktopVram) {
  const ledger = status?.vram_ledger;
  const noiseMb = ledger?.noise_mb || 1200;

  // === 收集桌面进程（过滤 vmwp 和 <1MB 小进程，放在底噪展开下面）===
  const desktopProcesses = [];
  const desktopMb = {};
  if (desktopVram?.processes) {
    for (const p of desktopVram.processes) {
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
  const ollamaModels = status?.ollama?.models || [];
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

  // ComfyUI（生成引擎，只能 /free 全量卸载，子模型不可单独结束）
  const comfyData = status?.comfyui_models || {};
  const comfyModelsList = comfyData.models || [];
  const comfyTorchMb = Number(comfyData.torch_vram_used_mb) || 0;
  if (comfyTorchMb > 1024) {
    let children = comfyModelsList.map(m => ({
      name: m.name || m.id, mb: (Number(m.vram_gb) || 0) * 1024,
      canStop: false,  // ComfyUI 无单模型卸载 API
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
  if (status?.containers?.fooocus) {
    containerItems.push({
      type: 'process', name: 'Fooocus · Flux 出图',
      mb: 6.9 * 1024, tag: 'Docker',
      canStop: true, stopAction: 'container_stop', container: 'fooocus',
    });
  }

  // 其它占显存的容器（未来新装的 GPU 容器自动出现）
  // 当前后端仅对 ollama/comfyui 有精确显存获取，其它容器暂不展示（显存为0时按规则过滤）
  // 未来扩展：_container_gpu_mb() 支持更多容器后自动出现在这里

  // 按显存降序
  containerItems.sort((a, b) => b.mb - a.mb);

  // === 未登记进程（unknown_pids，尝试匹配 desktopMb）===
  const unknown = status?.gpu_processes?.unknown_pids || [];
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
    <table class="table">
      <thead><tr><th style="width:24px"></th><th>进程 / 模型</th><th>来源</th><th class="num">显存</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>`);
  const tbody = card.querySelector('tbody');

  const totalItems = containerItems.length + 1; // +1 底噪
  if (totalItems === 1 && desktopProcesses.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding:24px">暂无占用显存的进程</td></tr>';
    return card;
  }

  // --- Docker 容器组 ---
  for (const item of containerItems) {
    if (item.type === 'group') {
      // 分组行
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

  // 底噪子行：桌面进程（只显示前 MAX_DESKTOP_SHOW 个）
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

/* 释放整个模型组 */
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

/* 结束单个子模型（仅 Ollama 支持） */
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

/* 停止 Docker 容器 */
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

/* 结束桌面进程 */
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

/* ========== 趋势图（GB 单位） ========== */

function renderTrend() {
  const card = el(`<div class="card">
    <div class="card__header"><div class="card__title">显存趋势（本次会话）</div><div class="text-xs text-muted">单位：GB</div></div>
    <div data-trend></div>
  </div>`);
  drawTrend(card.querySelector('[data-trend]'));
  return card;
}

function drawTrend(container) {
  empty(container);
  if (history.length < 2) {
    container.appendChild(el('<div class="chart__empty">收集数据中…</div>'));
    return;
  }
  const totalGb = (store.get('status')?.gpu?.total_mb || 16384) / 1024;
  const data = history.map((h, i) => ({
    label: i === 0 ? '开始' : `${i * 10}s`,
    value: Number((h.usedMb / 1024).toFixed(1)),
  }));
  container.appendChild(lineChart(data, { height: 160, yMax: totalGb, color: 'var(--primary-light)' }));
}

/* ========== 页面主体 ========== */

function render() {
  const page = el(`<div class="page vram-page">
    <div class="page-header flex justify-between items-center">
      <div>
        <div class="page-title">显存账本</div>
        <div class="page-subtitle">每一块显存去哪了——Docker 容器 / 底噪 / 桌面进程一目了然</div>
      </div>
      <button class="btn btn--ghost" data-refresh>刷新</button>
    </div>
    <div class="flex-col gap-md">
      <div data-dist></div>
      <div data-advice></div>
      <div class="grid grid-2"><div data-trend-slot></div><div data-helper-slot></div></div>
      <div data-proc></div>
    </div>
  </div>`);

  page.querySelector('[data-refresh]').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = '刷新中…';
    try {
      await refresh();
      events.emit('toast', { type: 'success', message: '显存数据已刷新' });
    } catch (err) {
      events.emit('toast', { type: 'error', message: err.message });
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  });
  load(page);
  return page;
}

async function load(page) {
  try {
    const status = await api.status();
    store.set('status', status);

    const usedMb = status?.gpu?.used_mb;
    if (usedMb !== undefined) {
      history.push({ usedMb, ts: Date.now() });
      if (history.length > 60) history.shift();
    }

    let desktopVram = null;
    if (status?.helper_running) {
      try { desktopVram = await api.desktopVram(); } catch (e) { /* helper 可能刚退出 */ }
    }

    renderAll(page, status, desktopVram);
    loadAdvice(page);
  } catch (e) {
    const d = page?.querySelector('[data-dist]');
    if (d) d.appendChild(el('<div class="card chart__empty">加载显存数据失败</div>'));
  }
}

function renderAll(page, status, desktopVram) {
  if (!page.isConnected) return;

  // 保存展开状态（轮询刷新后恢复）
  const expandedNames = new Set();
  document.querySelectorAll('.vram-group.expanded').forEach(g => {
    const name = g.querySelector('.vram-group__name')?.textContent;
    if (name) expandedNames.add(name);
  });

  const dist = page.querySelector('[data-dist]');
  empty(dist);
  dist.appendChild(renderDistribution(status, desktopVram));

  const trendSlot = page.querySelector('[data-trend-slot]');
  empty(trendSlot);
  trendSlot.appendChild(renderTrend());

  const helperSlot = page.querySelector('[data-helper-slot]');
  empty(helperSlot);
  helperSlot.appendChild(renderHelperCard(status));

  const proc = page.querySelector('[data-proc]');
  empty(proc);
  proc.appendChild(renderProcTable(status, desktopVram));

  // 恢复展开状态
  document.querySelectorAll('.vram-group').forEach(g => {
    const name = g.querySelector('.vram-group__name')?.textContent;
    if (name && expandedNames.has(name)) {
      g.classList.add('expanded');
      const toggle = g.querySelector('.vram-group__toggle');
      if (toggle) toggle.textContent = '▼';
      let next = g.nextElementSibling;
      while (next && next.classList.contains('vram-group__child')) {
        next.style.display = '';
        next = next.nextElementSibling;
      }
    }
  });
}

function renderHelperCard(status) {
  const helperRunning = status?.helper_running;
  const card = el(`<div class="card">
    <div class="card__header">
      <div class="card__title">桌面进程 Helper</div>
      <span class="tag ${helperRunning ? 'tag--ok' : 'tag--muted'}">${helperRunning ? '运行中' : '未运行'}</span>
    </div>
    <div class="text-sm text-muted">Helper 提供 Windows 桌面进程的逐进程显存查询与强制结束能力。桌面进程显示在「底噪/系统」展开列表中；vmwp(WSL2) 已自动合并至 Docker 容器明细，不重复显示。</div>
    <div class="mt-sm flex gap-sm">
      <button class="btn btn--sm btn--ghost" data-helper="${helperRunning ? 'stop' : 'start'}">${helperRunning ? '停止 Helper' : '启动 Helper'}</button>
    </div>
  </div>`);

  card.querySelector('[data-helper]').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const action = btn.dataset.helper;
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = action === 'start' ? '启动中…' : '停止中…';
    try {
      if (action === 'start') {
        await api.helperStart();
        events.emit('toast', { type: 'success', message: 'Helper 已启动' });
      } else {
        await api.helperStop();
        events.emit('toast', { type: 'success', message: 'Helper 已停止' });
      }
      // 直接更新 DOM：状态标签 + 按钮文本/属性
      const newRunning = action === 'start';
      const tag = card.querySelector('.tag');
      if (tag) {
        tag.textContent = newRunning ? '运行中' : '未运行';
        tag.classList.toggle('tag--ok', newRunning);
        tag.classList.toggle('tag--muted', !newRunning);
      }
      btn.dataset.helper = newRunning ? 'stop' : 'start';
      btn.textContent = newRunning ? '停止 Helper' : '启动 Helper';
      // 同步更新 store，供其他页面和下次轮询使用
      const cur = store.get('status') || {};
      cur.helper_running = newRunning;
      store.set('status', cur);
      // 不立即 refresh：避免 status 缓存未更新导致重新渲染覆盖 DOM 变化
      // 15 秒轮询会自动刷新，届时状态已正确
    } catch (err) {
      events.emit('toast', { type: 'error', message: err.message });
      btn.textContent = orig;
    } finally {
      btn.disabled = false;
    }
  });
  return card;
}

/* ========== 智能建议 + 未归因诊断（第二层，2026-08-31） ========== */

function renderAdviceCard(advice) {
  const card = el(`<div class="card">
    <div class="card__header">
      <div class="card__title">智能建议 · 显存诊断</div>
      <span class="text-xs text-muted">场景感知 + 释放收益排序</span>
    </div>
    <div data-advice-body></div>
  </div>`);
  const body = card.querySelector('[data-advice-body]');
  if (!advice?.ok) {
    body.appendChild(el('<div class="text-muted text-sm">诊断不可用：' + escapeHtml(advice?.error || '未知错误') + '</div>'));
    return card;
  }
  const bd = advice.breakdown || {};
  const segs = [
    { label: '底噪', mb: bd.noise_mb }, { label: '对话', mb: bd.ollama_mb },
    { label: '生成', mb: bd.comfy_mb }, { label: '其他', mb: bd.unattributed_mb },
  ].filter(s => s.mb > 0);
  const suggestions = advice.suggestions || [];
  const suggHtml = suggestions.length
    ? suggestions.map(s => {
        const rec = s.recover_mb ? fmtMb(s.recover_mb) : '';
        const btn = s.actionable
          ? '<button class="btn btn--sm btn--ghost" data-sugg-action="' + escapeHtml(s.id) + '">释放</button>'
          : '<span class="text-xs text-muted">不建议释放</span>';
        return '<div class="advice-row" style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">'
          + '<div style="min-width:0;margin-right:12px"><div style="font-weight:600;font-size:13px">' + escapeHtml(s.title || '') + '</div>'
          + '<div class="text-xs text-muted">' + escapeHtml(s.reason || '') + '</div></div>'
          + '<div style="display:flex;align-items:center;gap:10px;flex-shrink:0"><span style="font-weight:700;font-size:13px;min-width:56px;text-align:right">' + rec + '</span>' + btn + '</div></div>';
      }).join('')
    : '<div class="text-muted text-xs" style="padding:8px 0">当前无待释放项，显存状态健康</div>';

  const desktop = advice.desktop || [];
  const desktopHtml = desktop.length
    ? desktop.slice(0, 12).map(d => {
        const mb = d.used_mb != null ? fmtMb(d.used_mb) : '?';
        return '<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px">'
          + '<span>' + escapeHtml(d.name || '') + ' <span class="text-muted">(PID ' + d.pid + ')</span></span>'
          + '<span class="text-muted">' + mb + '</span></div>';
      }).join('')
      + (desktop.length > 12 ? '<div class="text-xs text-muted">…等 ' + desktop.length + ' 个进程</div>' : '')
    : '<div class="text-muted text-xs">未识别到桌面 GPU 进程</div>';
  const unknownHtml = advice.unknown_mb != null
    ? '<div class="text-xs ' + (advice.unknown_mb > 500 ? 'text-warn' : 'text-muted') + '" style="margin-top:6px">仍未归因：' + fmtMb(advice.unknown_mb) + (advice.helper_on ? '' : '（启动 Helper 可获得逐进程显存诊断）') + '</div>'
    : (desktop.length ? '<div class="text-xs text-muted" style="margin-top:6px">已识别 ' + desktop.length + ' 个桌面 GPU 进程（启动 Helper 获取逐进程显存）</div>' : '');
  const helperTag = advice.helper_on
    ? '<span class="tag tag--ok" style="margin-left:6px">Helper 已连接</span>'
    : '<span class="tag tag--muted" style="margin-left:6px">Helper 未运行</span>';

  body.appendChild(el('<div style="margin-bottom:12px">'
    + '<div class="text-xs text-muted" style="margin-bottom:6px">当前场景：<b>' + escapeHtml(advice.scene || 'unknown') + '</b>　空闲 ' + fmtMb(advice.gpu?.free_mb) + ' / 已用 ' + fmtMb(advice.gpu?.used_mb) + helperTag + '</div>'
    + '<div style="display:flex;gap:8px;flex-wrap:wrap">' + segs.map(s => '<span class="tag tag--muted">' + escapeHtml(s.label) + ' ' + fmtMb(s.mb) + '</span>').join('') + '</div>'
    + '</div>'
    + '<div style="font-weight:600;font-size:13px;margin-bottom:6px">释放建议（按收益排序）</div>'
    + suggHtml
    + '<div style="font-weight:600;font-size:13px;margin:12px 0 6px">其他 / 未归因诊断</div>'
    + desktopHtml + unknownHtml));

  setTimeout(() => {
    card.querySelectorAll('[data-sugg-action]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const id = e.currentTarget.getAttribute('data-sugg-action');
        const s = suggestions.find(x => x.id === id);
        if (!s) return;
        e.currentTarget.disabled = true;
        const orig = e.currentTarget.textContent;
        e.currentTarget.textContent = '执行中…';
        try {
          if (s.type === 'ollama_stop') await api.model(s.target, 'stop');
          else if (s.type === 'comfy_free') await api.free();
          else if (s.type === 'fooocus_stop') await api.containerStop('fooocus');
          else if (s.type === 'desktop_kill') {
            const pid = parseInt(String(id).replace('desktop_kill_', ''), 10);
            await api.desktopKill(pid);
          }
          events.emit('toast', { type: 'success', message: '已执行：' + (s.title || '') });
          await refresh();
        } catch (err) {
          events.emit('toast', { type: 'error', message: '执行失败：' + err.message });
          e.currentTarget.disabled = false;
          e.currentTarget.textContent = orig;
        }
      });
    });
  }, 50);
  return card;
}

async function loadAdvice(page) {
  const slot = page?.querySelector('[data-advice]');
  if (!slot) return;
  try {
    const advice = await api.advice();
    if (!slot.isConnected) return;
    empty(slot);
    slot.appendChild(renderAdviceCard(advice));
  } catch (e) {
    if (!slot.isConnected) return;
    empty(slot);
    slot.appendChild(el('<div class="card"><div class="card__header"><div class="card__title">智能建议 · 显存诊断</div></div><div class="text-muted text-sm">诊断加载失败：' + escapeHtml(e.message) + '</div></div>'));
  }
}

async function refresh() {
  const page = document.querySelector('.vram-page');
  if (page) await load(page);
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(refresh, POLL_INTERVAL);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

export default {
  title: '显存账本',
  render,
  onEnter: () => { refresh(); startPolling(); },
  onLeave: () => { stopPolling(); },
};
