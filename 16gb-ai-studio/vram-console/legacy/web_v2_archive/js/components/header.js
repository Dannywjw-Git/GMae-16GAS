/**
 * GMae 指挥家 v2.0 - components/header.js
 * 顶部栏：页面标题 + 主操作按钮插槽 + 版本号 + 用户信息
 */

import { el } from '../core/utils.js';
import { events } from '../core/events.js';
import { api, authApi } from '../core/api.js';
import { store } from '../core/state.js';
import { confirm, open as openModal } from './modal.js';

let headerNode = null;
let titleNode = null;
let actionSlot = null;
let dangerTimer = null;
let lastDangerLevel = 'safe';
let dangerModalOpen = false;

/** 设置页面标题 */
export function setTitle(title) {
  if (titleNode) titleNode.textContent = title;
}

/** 设置主操作按钮区（页面可动态注入） */
export function setActions(nodes) {
  if (!actionSlot) return;
  actionSlot.innerHTML = '';
  const list = Array.isArray(nodes) ? nodes : [nodes];
  for (const n of list) {
    if (n) actionSlot.appendChild(n);
  }
}

function showFreeResult(result) {
  const freedGb = (result?.freed_mb || 0) / 1024;
  const beforeGb = (result?.free_mb_before || 0) / 1024;
  const afterGb = (result?.free_mb_after || 0) / 1024;
  const stopped = result?.stopped || [];
  const running = (result?.running || []).filter(r => (r.gpu_mb || 0) > 0);

  // 已停止的进程明细
  const stoppedHtml = stopped.length ? stopped.map(s => {
    const methodLabel = s.method === 'stop_models' ? '停止模型' : s.method === '/free' ? '卸载模型' : '停止容器';
    return '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--line-dark);gap:12px">'
      + '<span style="font-weight:500;font-size:13px">✅ ' + s.name + '</span>'
      + '<span class="text-xs text-muted">' + methodLabel + '</span>'
      + '</div>';
  }).join('') : '<div class="text-muted text-xs">无（容器未运行或无需释放）</div>';

  // 仍在运行的进程明细（含显存 + 结束按钮）
  const runningHtml = running.length ? running.map(r => {
    const gmb = r.gpu_mb || 0;
    const gpuText = gmb > 0 ? (gmb >= 1024 ? (gmb/1024).toFixed(1) + ' GB' : Math.round(gmb) + ' MB') : '—';
    const protTag = r.protected ? '<span class="tag tag--muted" style="margin-left:6px">受保护</span>' : '';
    return '<div class="running-row" data-name="' + r.name + '" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--line-dark);gap:12px">'
      + '<span style="font-size:13px;flex:1">' + r.name + protTag + '</span>'
      + '<span class="text-xs text-muted" style="min-width:60px;text-align:right">' + gpuText + '</span>'
      + '<button class="btn btn--sm btn--danger" data-stop-container="' + r.name + '" style="flex-shrink:0">结束</button>'
      + '</div>';
  }).join('') : '<div class="text-muted text-xs">无</div>';

  const body = '<div style="margin-bottom:16px;padding:12px;background:var(--bg-tertiary);border-radius:var(--radius-md)">'
    + '<div style="font-size:20px;font-weight:700;color:var(--primary);margin-bottom:4px">腾出 ' + freedGb.toFixed(1) + ' GB 显存</div>'
    + '<div class="text-muted" style="font-size:13px">空闲显存：' + beforeGb.toFixed(1) + ' GB → ' + afterGb.toFixed(1) + ' GB　|　' + (result?.success_count || 0) + '/' + (result?.total_count || 0) + ' 项成功</div>'
    + '</div>'
    + '<div style="font-weight:600;margin-bottom:8px;font-size:14px">已停止的进程（' + stopped.length + '）</div>'
    + '<div style="margin-bottom:16px;max-height:160px;overflow-y:auto">' + stoppedHtml + '</div>'
    + '<div style="font-weight:600;margin-bottom:8px;font-size:14px">仍在运行的进程（' + running.length + '）</div>'
    + '<div style="max-height:200px;overflow-y:auto">' + runningHtml + '</div>';

  const close = openModal({ title: '一键释放结果', body, width: '600px' });

  // 绑定"结束"按钮
  setTimeout(() => {
    document.querySelectorAll('[data-stop-container]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const name = e.currentTarget.getAttribute('data-stop-container');
        const row = e.currentTarget.closest('.running-row');
        e.currentTarget.disabled = true;
        e.currentTarget.textContent = '停止中…';
        try {
          const r = await api.containerStop(name);
          if (r.ok) {
            events.emit('toast', { type: 'success', message: '已停止容器 ' + name });
            if (row) row.remove();
            events.emit('status:refresh');
          } else {
            events.emit('toast', { type: 'error', message: r.error || '停止失败' });
            e.currentTarget.disabled = false;
            e.currentTarget.textContent = '结束';
          }
        } catch (err) {
          events.emit('toast', { type: 'error', message: err.message });
          e.currentTarget.disabled = false;
          e.currentTarget.textContent = '结束';
        }
      });
    });
  }, 50);
}

async function onFreeAll() {
  const btn = headerNode?.querySelector('[data-free]');
  if (!btn) return;
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = '释放中…';
  try {
    const result = await api.free();
    showFreeResult(result);
    events.emit('toast', { type: 'success', message: result?.message || '显存已释放' });
    events.emit('status:refresh');
  } catch (err) {
    events.emit('toast', { type: 'error', message: err.message });
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

async function onLogout() {
  const ok = await confirm({
    title: '退出登录',
    message: '确定要退出当前账号吗？',
    okText: '退出',
    danger: true,
  });
  if (!ok) return;
  try {
    await authApi.logout();
  } catch { /* 忽略 */ }
  window.location.href = '/login';
}

/** 渲染顶部栏（仅调用一次） */
export function render() {
  headerNode = el(`<header class="topbar">
    <div class="topbar__left">
      <h1 class="topbar__title"></h1>
    </div>
    <div class="topbar__actions" data-actions></div>
    <div class="topbar__right">
      <span class="vram-danger" data-vram-danger style="display:none"></span>
      <span class="topbar__version"></span>
      <span class="topbar__user" data-user></span>
      <button class="btn btn--ok btn--sm" data-free>一键释放</button>
      <button class="btn btn--ghost btn--sm" data-logout>退出</button>
    </div>
  </header>`);

  titleNode = headerNode.querySelector('.topbar__title');
  actionSlot = headerNode.querySelector('[data-actions]');
  headerNode.querySelector('[data-version]') && null;
  headerNode.querySelector('.topbar__version').textContent = store.get('ui')?.version || 'v2.0.0-alpha';
  headerNode.querySelector('.topbar__user').textContent = store.get('auth')?.email || '';
  headerNode.querySelector('[data-logout]').addEventListener('click', onLogout);
  headerNode.querySelector('[data-free]').addEventListener('click', onFreeAll);

  // 路由变化 → 更新标题
  events.on('route:change', ({ title }) => {
    if (title) setTitle(title);
  });

  // 显存危险等级轮询（每5秒）
  startDangerMonitor();

  return headerNode;
}

/* ========== 显存危险等级监控 ========== */

function startDangerMonitor() {
  if (dangerTimer) return;
  updateDangerIndicator();
  dangerTimer = setInterval(updateDangerIndicator, 5000);
}

function fmtMbLocal(mb) {
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB';
  return Math.round(mb) + ' MB';
}

async function updateDangerIndicator() {
  try {
    const status = await api.status();
    const ledger = status?.vram_ledger || {};
    const level = ledger.danger_level || 'safe';
    const freeMb = ledger.free_mb ?? 99999;
    const indicator = headerNode?.querySelector('[data-vram-danger]');
    if (!indicator) return;

    const configs = {
      safe:     { show: false, bg: '', color: '', text: '', blink: false },
      warning:  { show: true,  bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', text: '显存紧张 ' + fmtMbLocal(freeMb), blink: false },
      danger:   { show: true,  bg: 'rgba(249,115,22,0.2)',  color: '#f97316', text: '显存危险 ' + fmtMbLocal(freeMb), blink: false },
      critical: { show: true,  bg: 'rgba(239,68,68,0.25)',   color: '#ef4444', text: '显存危急 ' + fmtMbLocal(freeMb) + ' 随时死机', blink: true },
    };
    const cfg = configs[level] || configs.safe;
    indicator.style.display = cfg.show ? '' : 'none';
    if (cfg.show) {
      indicator.style.background = cfg.bg;
      indicator.style.color = cfg.color;
      indicator.style.border = '1px solid ' + cfg.color;
      indicator.style.padding = '2px 10px';
      indicator.style.borderRadius = '12px';
      indicator.style.fontSize = '12px';
      indicator.style.fontWeight = '600';
      indicator.style.animation = cfg.blink ? 'dangerBlink 1s infinite' : '';
      indicator.textContent = cfg.text;
    }

    // 从非 critical 变为 critical 时弹出紧急弹窗
    if (level === 'critical' && lastDangerLevel !== 'critical' && !dangerModalOpen) {
      showDangerModal(status);
    }
    lastDangerLevel = level;
  } catch (e) {
    // 忽略轮询错误
  }
}

function showDangerModal(status) {
  dangerModalOpen = true;
  const ledger = status?.vram_ledger || {};
  const gpu = status?.gpu || {};
  const freeMb = ledger.free_mb ?? gpu.free_mb ?? 0;
  const usedMb = ledger.actual_used_mb || gpu.used_mb || 0;
  const ollamaMb = ledger.ollama_loaded_mb || 0;
  const comfyMb = ledger.comfy_loaded_mb || 0;
  const noiseMb = ledger.noise_mb || 1200;
  const otherMb = Math.max(usedMb - noiseMb - ollamaMb - comfyMb, 0);

  // 占用排行
  const items = [];
  if (comfyMb > 0) items.push({ name: 'ComfyUI 生成引擎', mb: comfyMb, action: 'comfy', hint: '调用 /free 全量卸载' });
  if (ollamaMb > 0) items.push({ name: 'Ollama 对话模型', mb: ollamaMb, action: 'ollama', hint: '停止所有已加载模型' });
  if (otherMb > 500) items.push({ name: '其他/未归因', mb: otherMb, action: null, hint: '可能是 CUDA context 或未识别进程' });
  items.push({ name: '底噪/系统', mb: noiseMb, action: null, hint: '固定开销，不可释放' });
  items.sort((a, b) => b.mb - a.mb);

  const bodyHtml = '<div class="text-muted" style="margin-bottom:16px">空闲仅剩 <b style="color:var(--bad)">' + fmtMbLocal(freeMb) + '</b>，系统随时可能死机。建议立即释放以下模型：</div>'
    + items.map(it => {
        const btn = it.action
          ? '<button class="btn btn--sm btn--ghost" data-danger-action="' + it.action + '">释放</button>'
          : '<span class="text-xs text-muted">不可释放</span>';
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">'
          + '<div><div style="font-weight:600">' + it.name + '</div>'
          + '<div class="text-xs text-muted">' + it.hint + '</div></div>'
          + '<div style="display:flex;align-items:center;gap:12px">'
          + '<span style="font-weight:700;min-width:70px;text-align:right">' + fmtMbLocal(it.mb) + '</span>'
          + btn + '</div></div>';
      }).join('');

  const footerHtml = '<button class="btn btn--sm btn--ghost" data-danger-close>暂不处理</button>'
    + '<button class="btn btn--sm btn--ok" data-danger-freeall>一键释放全部</button>';

  const close = openModal({
    title: '显存危急',
    body: bodyHtml,
    footer: footerHtml,
    width: '480px',
  });

  const onClose = () => { dangerModalOpen = false; };

  // 释放单个
  document.querySelectorAll('[data-danger-action]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const action = btn.getAttribute('data-danger-action');
      btn.disabled = true;
      btn.textContent = '释放中...';
      try {
        await api.free();
        events.emit('toast', { type: 'success', message: '已释放，显存正在回收' });
        onClose();
        close();
      } catch (e) {
        btn.disabled = false;
        btn.textContent = '释放';
        events.emit('toast', { type: 'error', message: '释放失败：' + e.message });
      }
    });
  });

  // 一键释放全部
  document.querySelector('[data-danger-freeall]')?.addEventListener('click', async () => {
    try {
      const result = await api.free();
      showFreeResult(result);
      onClose();
      close();
    } catch (e) {
      events.emit('toast', { type: 'error', message: '释放失败：' + e.message });
    }
  });

  // 关闭
  document.querySelector('[data-danger-close]')?.addEventListener('click', () => { onClose(); close(); });
}


export default { render, setTitle, setActions };
