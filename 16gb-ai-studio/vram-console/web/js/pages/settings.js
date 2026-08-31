/**
 * GMae 指挥家 v2.0 - pages/settings.js
 * 设置页（阶段 4）：系统信息 + 服务状态 + 门卫登记簿 + QoS + 账号
 * 数据源：/api/registry（system/gpu_guard/containers）+ /api/status（containers/helper）+ /api/qos/status + auth
 */

import { store } from '../core/state.js';
import { api, authApi } from '../core/api.js';
import { events } from '../core/events.js';
import { el, empty, escapeHtml } from '../core/utils.js';

let page = null;
let registry = null;

/* ========== 各分组 ========== */

function renderSystem(sys) {
  const slot = page.querySelector('[data-sys]');
  if (!slot) return;
  empty(slot);
  const rows = [
    ['GPU 显存总量', sys?.gpu_vram_total_gb != null ? `${sys.gpu_vram_total_gb} GB` : '—'],
    ['底噪占用', sys?.gpu_base_noise_gb != null ? `${sys.gpu_base_noise_gb} GB` : '—'],
    ['系统保留', sys?.vram_reserve_gb != null ? `${sys.vram_reserve_gb} GB` : '—'],
    ['M1 阈值（预释放线）', sys?.m1_threshold_mb != null ? `${sys.m1_threshold_mb} MB` : '—'],
    ['看门狗重启延时', sys?.watchdog_restart_delay_s != null ? `${sys.watchdog_restart_delay_s} s` : '—'],
  ];
  slot.appendChild(renderInfoCard('系统配置', rows));
}

function renderServices(status) {
  const slot = page.querySelector('[data-services]');
  if (!slot) return;
  empty(slot);
  const c = status?.containers || {};
  const items = [
    { name: 'ComfyUI', on: !!c.comfyui, port: 8188 },
    { name: 'Fooocus', on: !!c.fooocus, port: 7865 },
    { name: 'Ollama', on: true, port: 11434 },
  ];
  const rows = items.map((s) => [
    s.name,
    `<span class="tag ${s.on ? 'tag--ok' : 'tag--muted'}">${s.on ? '运行中' : '已停止'}</span>`,
    `:${s.port}`,
  ]);
  const helper = status?.helper_running;
  rows.push(['桌面 Helper', `<span class="tag ${helper ? 'tag--ok' : 'tag--muted'}">${helper ? '运行中' : '未运行'}</span>`, '逐进程显存查询']);
  slot.appendChild(renderInfoCard('服务状态', rows));
}

function renderGuardBook(gg) {
  const slot = page.querySelector('[data-guardbook]');
  if (!slot) return;
  empty(slot);
  const card = el(`<div class="card">
    <div class="card__title">门卫登记簿 <span class="text-xs text-muted">${escapeHtml(gg?.description || '')}</span></div>
    <div class="card__body grid grid-2 gap-lg">
      <div>
        <div class="text-xs text-muted mb-sm">managed（可安全驱逐）</div>
        ${(gg?.managed || []).map((m) => `<div class="settings-row"><span>${escapeHtml(m.name)}</span><span class="text-muted text-xs">${escapeHtml(m.note || '')}</span></div>`).join('') || '<div class="text-muted text-xs">无</div>'}
      </div>
      <div>
        <div class="text-xs text-muted mb-sm">protect（永不触碰）</div>
        ${(gg?.protect || []).map((m) => `<div class="settings-row"><span>${escapeHtml(m.name)}</span><span class="text-muted text-xs">${escapeHtml(m.note || '')}</span></div>`).join('') || '<div class="text-muted text-xs">无</div>'}
      </div>
    </div>
    ${gg?.unknown_policy ? `<div class="card__body text-xs text-muted">未登记占用策略：${escapeHtml(gg.unknown_policy)}</div>` : ''}
  </div>`);
  slot.appendChild(card);
}

function renderQos(qos) {
  const slot = page.querySelector('[data-qos]');
  if (!slot) return;
  empty(slot);
  const cfg = qos?.config || {};
  const level = qos?.level || '—';
  const rows = [
    ['当前水位', `<span class="tag ${level === 'ok' ? 'tag--ok' : level === 'warning' ? 'tag--warn' : 'tag--bad'}">${escapeHtml(String(level))}</span>`],
    ['紧急阈值', cfg.emergency_threshold_mb != null ? `${cfg.emergency_threshold_mb} MB` : '—'],
    ['预警阈值', cfg.warning_threshold_mb != null ? `${cfg.warning_threshold_mb} MB` : '—'],
    ['巡检间隔', cfg.check_interval_s != null ? `${cfg.check_interval_s} s` : '—'],
    ['启用', cfg.enabled ? '✅' : '❌'],
  ];
  slot.appendChild(renderInfoCard('QoS 水位管控', rows));
}

const AUTO_PROTECT_MODES = {
  conservative: { label: '保守', desc: '仅 <1GB 危急时自动卸载多余模型 + ComfyUI 释放，不碰容器' },
  standard: { label: '标准', desc: '<2GB 开始分级释放；<1GB 危急时再停 Fooocus' },
  aggressive: { label: '激进', desc: '<4GB 即释放多余模型；<2GB 加 ComfyUI 释放；<1GB 加停 Fooocus' },
};

function renderAutoProtect(ap) {
  const slot = page.querySelector('[data-autoprotect]');
  if (!slot) return;
  empty(slot);
  const enabled = !!ap?.enabled;
  const mode = ap?.mode || 'standard';
  const last = ap?.last_trigger;
  const card = el(`<div class="card">
    <div class="card__title">自动防死机 <span class="text-xs text-muted">第三层 · 需授权</span></div>
    <div class="card__body">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px">
        <div>
          <div class="text-sm" style="font-weight:600">${enabled ? '已开启 ✅' : '已关闭（仅告警，不自动释放）'}</div>
          <div class="text-xs text-muted" style="margin-top:4px">开启后，显存危急时 GMae 自动执行分级释放（卸载多余模型 → ComfyUI 释放 → 停非保护容器）。
            红线：<b>永不杀桌面进程/前台应用</b>、永不停止受保护容器，每次动作全量审计日志。</div>
        </div>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;white-space:nowrap">
          <input type="checkbox" data-ap-enabled ${enabled ? 'checked' : ''} />
          <span class="text-sm">授权启用</span>
        </label>
      </div>
      <div class="flex-col gap-sm" style="margin-top:12px">
        <div class="text-xs text-muted">释放模式</div>
        ${Object.entries(AUTO_PROTECT_MODES).map(([k, m]) => `
          <label class="settings-row" style="cursor:pointer">
            <input type="radio" name="ap-mode" value="${k}" ${k === mode ? 'checked' : ''} />
            <span>${m.label}</span><span class="text-muted text-xs">${m.desc}</span>
          </label>`).join('')}
      </div>
      <button class="btn" data-ap-save style="margin-top:12px">保存授权配置</button>
      ${last ? `<div class="text-xs ${last.level === 'critical' ? 'text-warn' : 'text-muted'}" style="margin-top:8px">
        最近触发：${new Date(last.ts * 1000).toLocaleString()} · ${escapeHtml(String(last.level))}（空闲 ${(last.free_mb / 1024).toFixed(1)}GB）
        → ${last.actions.map((a) => escapeHtml(a.action)).join('、')}
      </div>` : '<div class="text-xs text-muted" style="margin-top:8px">尚未触发过自动释放</div>'}
    </div>
  </div>`);
  card.querySelector('[data-ap-save]').addEventListener('click', async () => {
    const btn = card.querySelector('[data-ap-save]');
    btn.disabled = true;
    try {
      const r = await api.autoProtectConfig({
        enabled: card.querySelector('[data-ap-enabled]').checked,
        mode: card.querySelector('input[name="ap-mode"]:checked')?.value || 'standard',
      });
      events.emit('toast', { type: r.ok ? 'success' : 'error', message: r.ok ? `已保存：${r.enabled ? '开启' : '关闭'}（模式：${r.mode}）` : (r.error || '保存失败') });
      refresh();
    } catch (err) {
      events.emit('toast', { type: 'error', message: err.message });
    } finally {
      btn.disabled = false;
    }
  });
  slot.appendChild(card);
}

function renderAccount() {
  const slot = page.querySelector('[data-account]');
  if (!slot) return;
  empty(slot);
  const card = el(`<div class="card">
    <div class="card__title">账号</div>
    <div class="card__body">
      <form class="settings-form flex-col gap-sm" data-pwform>
        <div class="flex-col gap-sm" style="max-width:320px">
          <input type="password" placeholder="当前密码" data-old required class="settings-input" />
          <input type="password" placeholder="新密码" data-new required minlength="6" class="settings-input" />
          <button class="btn" type="submit" style="align-self:flex-start">修改密码</button>
        </div>
      </form>
    </div>
  </div>`);
  card.querySelector('[data-pwform]').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.currentTarget.querySelector('button');
    btn.disabled = true;
    try {
      await authApi.changePassword(
        e.currentTarget.querySelector('[data-old]').value,
        e.currentTarget.querySelector('[data-new]').value,
      );
      events.emit('toast', { type: 'success', message: '密码已修改' });
      e.currentTarget.querySelector('[data-old]').value = '';
      e.currentTarget.querySelector('[data-new]').value = '';
    } catch (err) {
      events.emit('toast', { type: 'error', message: err.message });
    } finally {
      btn.disabled = false;
    }
  });
  slot.appendChild(card);
}

function renderInfoCard(title, rows) {
  return el(`<div class="card">
    <div class="card__title">${escapeHtml(title)}</div>
    <div class="card__body settings-rows">${rows.map((r) => `<div class="settings-row">
      <span>${escapeHtml(r[0])}</span><span>${r[1]}</span><span class="text-muted text-xs">${r[2] != null ? escapeHtml(String(r[2])) : ''}</span>
    </div>`).join('')}</div>
  </div>`);
}

/* ========== 页面骨架 ========== */

function render() {
  page = el(`<div class="page settings-page">
    <div class="page-header">
      <div class="page-title">设置</div>
      <div class="page-subtitle">系统配置 · 服务状态 · 门卫登记簿 · QoS · 账号</div>
    </div>
    <div class="flex-col gap-lg">
      <div class="grid grid-2" data-sys></div>
      <div class="grid grid-2" data-services></div>
      <div data-guardbook></div>
      <div class="grid grid-2" data-qos></div>
      <div data-autoprotect></div>
      <div data-account></div>
      <div class="text-xs text-muted font-mono" data-about></div>
    </div>
  </div>`);
  return page;
}

/* ========== 数据加载 ========== */

async function refresh() {
  try {
    if (!registry) {
      try {
        const reg = await api.registry();
        registry = reg;
      } catch { registry = null; }
    }
    const [status, qos, ap] = await Promise.all([
      api.status(),
      api.qosStatus(),
      api.autoProtectStatus(),
    ]);
    store.set('status', status);
    renderSystem(registry?.system);
    renderServices(status);
    renderGuardBook(registry?.gpu_guard);
    renderQos(qos);
    renderAutoProtect(ap);
    const about = page.querySelector('[data-about]');
    if (about) about.textContent = `GMae 指挥家 · registry v${registry?.version || '?'} · 更新 ${registry?.last_updated || '—'}`;
  } catch { /* api:error 已广播 */ }
}

/* ========== 页面注册 ========== */

export default {
  title: '设置',
  render,
  onEnter: () => {
    renderAccount();
    refresh();
  },
  onLeave: () => {},
};
