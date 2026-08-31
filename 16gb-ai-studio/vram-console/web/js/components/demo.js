/**
 * GMae 指挥家 v2.0 - components/demo.js
 * 一键演示模式（全屏 overlay，5 幕脚本）
 * 参考旧版 demo-overlay，适配新版模块化架构。
 * 安全策略：第1幕真实 /free（安全）、第3幕真实 /budget（只读）；
 * 第2/4/5幕用真实数据展示 + 模拟日志，不执行危险操作（kick/evict/scene switch）。
 */

import { api } from '../core/api.js';
import { el, empty, escapeHtml, fmtMb } from '../core/utils.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ========== 5 幕脚本 ========== */

const SCENES = [
  {
    id: 1, icon: '⚡', name: '显存秒级释放',
    desc: '展示 /free 接口秒级释放 ComfyUI 显存，对比容器重启需 30 秒',
    detail: 'GMae 的核心能力之一：显存秒级释放。传统方式需要重启容器（约 30 秒），而 GMae 通过 ComfyUI /free 接口可在 1-2 秒内释放显存，实现真正的动态调度。',
    estimated: 30,
    action: async (log) => {
      log('info', '【第一幕】显存秒级释放能力展示');
      log('', '步骤 1/3：记录当前显存状态...');
      await sleep(800);
      const before = await api.status();
      const gpu = before?.gpu || {};
      log('info', `当前显存：已用 ${fmtMb(gpu.used_mb || 0)} / ${fmtMb(gpu.total_mb || 0)}（可用 ${fmtMb(gpu.free_mb || 0)}）`);
      log('', '步骤 2/3：调用 ComfyUI /free 释放显存...');
      await sleep(400);
      const t0 = Date.now();
      try { await api.free(); } catch (e) { log('warn', `释放请求异常：${e.message}`); }
      const t1 = Date.now();
      log('success', `✓ /free 调用完成，耗时 ${((t1 - t0) / 1000).toFixed(2)} 秒`);
      log('', '步骤 3/3：验证显存释放结果...');
      await sleep(1200);
      const after = await api.status();
      const gpu2 = after?.gpu || {};
      const freed = Math.max(0, (gpu2.free_mb || 0) - (gpu.free_mb || 0));
      log('success', `✓ 释放后显存：已用 ${fmtMb(gpu2.used_mb || 0)} / ${fmtMb(gpu2.total_mb || 0)}（可用 ${fmtMb(gpu2.free_mb || 0)}）`);
      log('success', `✓ 释放了 ${fmtMb(freed)} 显存`);
      log('info', '对比：传统容器重启方式需约 30 秒，GMae /free 仅需 1-2 秒，效率提升 15 倍+');
    },
  },
  {
    id: 2, icon: '⚔️', name: '门卫强制驱逐',
    desc: '展示进程级显存账本，可识别并强制驱逐占用显存的进程',
    detail: 'GMae 的门卫（Guard）模块提供进程级显存管理：能识别每个 GPU 进程的 PID、名称、显存占用、归属容器，并支持强制驱逐（验明正身后 docker exec kill，protect 类进程自动拒绝）。这是实现显存动态调度的基础能力。',
    estimated: 40,
    action: async (log) => {
      log('info', '【第二幕】门卫强制驱逐能力展示');
      log('', '步骤 1/3：获取进程级显存账本...');
      await sleep(800);
      const status = await api.status();
      const procs = status?.gpu_processes || {};
      const managed = procs.processes || [];
      const desktop = procs.desktop_processes || [];
      const unknown = procs.unknown_pids || [];
      log('info', `进程账本：受管 ${managed.length} 个 · 桌面 ${desktop.length} 个 · 未登记 ${unknown.length} 个`);
      if (managed.length) {
        const p = managed[0];
        log('', `步骤 2/3：识别受管进程 PID ${p.pid}（${escapeHtml(p.name || '?')}，归属 ${escapeHtml(p.app || '')}，占用 ${fmtMb(p.used_mb || 0)}）`);
      } else {
        log('', '步骤 2/3：当前无受管 GPU 进程（ComfyUI 未加载模型）');
      }
      await sleep(600);
      log('', '步骤 3/3：模拟强制驱逐（演示模式不真实 kill，保护系统）...');
      await sleep(500);
      log('success', '✓ 验明正身：进程属于受管容器 comfyui，非 protect 类');
      log('success', '✓ 模拟 docker exec kill -9 执行成功（演示模式未真实执行）');
      log('info', '门卫登记簿：managed（可安全驱逐）= ollama/comfyui/fooocus；protect（永不触碰）= open-webui/immich/ollama本体');
    },
  },
  {
    id: 3, icon: '🧮', name: '预算引擎智能决策',
    desc: '展示预算引擎：每个模型能不能跑、要释放多少、差多少',
    detail: 'GMae 的预算引擎（Budget Engine）实时核算每个已知模型「能不能跑、要释放多少、差多少」，支持 context 覆盖（不同上下文窗口对应不同显存），为预演模式和调度决策提供数据支撑。',
    estimated: 35,
    action: async (log) => {
      log('info', '【第三幕】预算引擎智能决策展示');
      log('', '步骤 1/3：调用预算引擎 /api/budget...');
      await sleep(800);
      const b = await api.budget();
      log('info', `显存预算：总量 ${b.total_gb}G · 底噪 ${b.noise_gb}G · 保留 ${b.reserve_gb}G · 安全上限 ${b.safe_ceiling_gb}G`);
      log('info', `当前：已用 ${b.used_gb}G · 可释放 ${b.releasable_gb}G · 可用 ${b.avail_gb}G`);
      log('', '步骤 2/3：模型决策分析（前 5 个）...');
      await sleep(500);
      const models = b.models || [];
      const okCount = models.filter((m) => m.decision === 'ok').length;
      const freeCount = models.filter((m) => m.decision === 'free' || m.need_free_gb > 0).length;
      log('info', `共 ${models.length} 个模型：可直接加载 ${okCount} 个 · 需释放 ${freeCount} 个`);
      for (const m of models.slice(0, 5)) {
        const tag = m.decision === 'ok' ? '✓ 可直接加载' : m.need_free_gb > 0 ? `⚠ 需释放 ${m.need_free_gb}G` : `✗ 超限 ${m.gap_gb}G`;
        log('', `  ${escapeHtml(m.name)}（${m.vram_gb}G）→ ${tag}`);
      }
      log('', '步骤 3/3：Context 覆盖演示（Qwen3.5 9B：16K→196K）...');
      await sleep(500);
      const qwen = models.find((m) => (m.id || '').includes('qwen3.5'));
      if (qwen?.context_vram) {
        const ctxs = Object.entries(qwen.context_vram);
        for (const [ctx, vram] of ctxs) {
          log('', `  Context ${Math.round(Number(ctx) / 1024)}K → ${vram}G`);
        }
        log('success', '✓ Context 越大显存越高，预算引擎实时核算，预演模式可直接试算');
      } else {
        log('info', 'Qwen3.5 未找到 context 数据，跳过');
      }
    },
  },
  {
    id: 4, icon: '🎬', name: '多模态连续生成',
    desc: '展示模型登记台 + 任务队列，支持文生图/文生视频/文生音乐串行调度',
    detail: 'GMae 支持多模态模型统一登记与调度：文生图（SDXL/Flux）、文生视频（Wan2.2）、文生音乐（Music3）通过统一任务队列串行调度，16G 单卡也能连续生成。',
    estimated: 40,
    action: async (log) => {
      log('info', '【第四幕】多模态连续生成展示');
      log('', '步骤 1/3：获取模型登记台...');
      await sleep(800);
      const reg = await api.registry();
      const comfy = reg?.comfyui_models || [];
      const ollama = reg?.ollama_models || [];
      log('info', `模型登记：对话/嵌入 ${ollama.length} 个 · 生成 ${comfy.length} 个`);
      const wf = comfy.filter((m) => m.workflow);
      log('info', `有工作流模板的生成模型：${wf.map((m) => escapeHtml(m.name)).join('、')}`);
      log('', '步骤 2/3：任务队列状态...');
      await sleep(600);
      const q = await api.queue();
      const tasks = q?.tasks || [];
      const running = tasks.filter((t) => t.status === 'running').length;
      const waiting = tasks.filter((t) => ['queued', 'precheck', 'freeing'].includes(t.status)).length;
      log('info', `队列：worker ${q?.worker_alive ? '🟢 运行中' : '⚪ 空闲'} · 运行 ${running} · 排队 ${waiting} · 共 ${tasks.length}`);
      log('', '步骤 3/3：模拟连续生成（演示模式不真实生成，保护显存）...');
      await sleep(500);
      log('success', '✓ 模拟入队：SDXL 文生图（480x480，seed=42）');
      log('success', '✓ 模拟入队：Wan2.2 文生视频（480x480x17帧）');
      log('success', '✓ 模拟入队：Music3 文生音乐（60秒）');
      log('info', '16G 单卡串行调度：生成完一个自动释放显存，再跑下一个，无需人工干预');
    },
  },
  {
    id: 5, icon: '🎭', name: '多场景稳定切换',
    desc: '展示场景化调度：对话/出图/视频/音乐/游戏一键切换，显存预算自动适配',
    detail: 'GMae 的场景化（Scene）调度：一套场景 = 一套容器状态 + 显存预算。一键切换对话态/出图态/视频态/音乐态/游戏态，系统自动启停容器、释放显存、适配预算，全程无需人工干预。',
    estimated: 35,
    action: async (log) => {
      log('info', '【第五幕】多场景稳定切换展示');
      log('', '步骤 1/3：当前场景状态...');
      await sleep(800);
      const status = await api.status();
      const scene = status?.scene || 'none';
      const SCENE_LABEL = { dialogue: '对话态', comfy: 'SDXL出图', h3: '视频态', fooocus: 'Flux出图', music: '音乐态', game: '游戏态', none: '空闲' };
      log('info', `当前场景：${SCENE_LABEL[scene] || scene}`);
      log('', '步骤 2/3：场景清单与显存预算...');
      await sleep(500);
      const reg = await api.registry();
      const scenes = reg?.scenes || {};
      for (const [id, s] of Object.entries(scenes)) {
        const tag = id === scene ? '← 当前' : '';
        log('', `  ${escapeHtml(s.label || id)}（~${s.vram_budget_gb}G${s.exclusive ? ' · 独占' : ''}）${tag}`);
      }
      log('', '步骤 3/3：模拟场景切换（演示模式不真实启停容器，保护系统）...');
      await sleep(500);
      log('success', '✓ 模拟切换：对话态 → SDXL出图态（停 ollama 模型 → 启 comfyui → 释放显存 → 等待就绪）');
      log('success', '✓ 模拟切换：SDXL出图态 → 视频态（停 comfyui 模型 → 加载 Wan2.2 → 独占全卡）');
      log('info', '切换全程自动：M1 铁律（切换前显存<4G 自动预释放）+ 关键步骤失败检测 + 120s 超时保护');
      log('success', '🎉 五幕演示全部完成！GMae 展示了消费级显卡的强大管理能力');
      log('info', 'One GPU, Infinite Models — 一张显卡，无限可能');
    },
  },
];

/* ========== 状态 ========== */

let state = null;
let overlay = null;

function log(type, msg) {
  if (!overlay) return;
  const logEl = overlay.querySelector('[data-demo-log]');
  if (!logEl) return;
  const time = new Date().toLocaleTimeString();
  const line = el(`<div class="demo-log-line ${type || ''}"><span class="demo-log-time">[${time}]</span> ${msg}</div>`);
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
  state.logs.push({ type, msg, time });
}

function renderScenes() {
  const list = overlay.querySelector('[data-demo-scenes]');
  if (!list) return;
  empty(list);
  SCENES.forEach((s, i) => {
    const cls = i === state.current ? 'active' : i < state.current ? 'done' : '';
    const num = i < state.current ? '✓' : String(i + 1);
    const item = el(`<div class="demo-scene-item ${cls}" data-scene="${i}">
      <span class="demo-scene-num">${num}</span>
      <span class="demo-scene-name">${s.icon} ${escapeHtml(s.name)}</span>
      <div class="demo-scene-desc">${escapeHtml(s.desc)}</div>
      <div class="demo-scene-time">预计 ${s.estimated}s</div>
    </div>`);
    item.addEventListener('click', () => selectScene(i));
    list.appendChild(item);
  });
}

function selectScene(i) {
  state.current = i;
  const s = SCENES[i];
  const title = overlay.querySelector('[data-demo-title]');
  const desc = overlay.querySelector('[data-demo-desc]');
  if (title) title.textContent = `第 ${i + 1} 幕：${s.icon} ${s.name}`;
  if (desc) desc.textContent = s.detail;
  renderScenes();
  updateProgress();
}

function updateProgress() {
  const total = SCENES.length;
  const cur = state.current;
  const pct = cur >= 0 ? Math.round(((cur + 1) / total) * 100) : 0;
  const fill = overlay.querySelector('[data-demo-progress-fill]');
  const pctEl = overlay.querySelector('[data-demo-progress-pct]');
  const txt = overlay.querySelector('[data-demo-progress-text]');
  const done = overlay.querySelector('[data-demo-done]');
  if (fill) fill.style.width = pct + '%';
  if (pctEl) pctEl.textContent = pct + '%';
  if (txt) txt.textContent = cur >= 0 ? `第 ${cur + 1}/${total} 幕：${SCENES[cur].name}` : '准备就绪';
  if (done) done.textContent = Math.max(0, cur);
}

function startTimer() {
  if (state.timer) clearInterval(state.timer);
  state.startTime = Date.now();
  state.timer = setInterval(() => {
    if (!state.running) return;
    const elapsed = Math.floor((Date.now() - state.startTime) / 1000);
    const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const ss = String(elapsed % 60).padStart(2, '0');
    const elEl = overlay?.querySelector('[data-demo-elapsed]');
    if (elEl) elEl.textContent = `${mm}:${ss}`;
    // 预计剩余
    const doneEst = SCENES.slice(0, state.current + 1).reduce((a, s) => a + s.estimated, 0);
    const totalEst = SCENES.reduce((a, s) => a + s.estimated, 0);
    const remain = Math.max(0, totalEst - Math.min(elapsed, doneEst));
    const rmm = String(Math.floor(remain / 60)).padStart(2, '0');
    const rss = String(remain % 60).padStart(2, '0');
    const remEl = overlay?.querySelector('[data-demo-remaining]');
    if (remEl) remEl.textContent = `${rmm}:${rss}`;
    // 当前显存
    const vramEl = overlay?.querySelector('[data-demo-vram]');
    if (vramEl && state.current >= 0) {
      api.status().then((s) => {
        if (s?.gpu) vramEl.textContent = `${fmtMb(s.gpu.used_mb || 0)}/${fmtMb(s.gpu.total_mb || 0)}`;
      }).catch(() => {});
    }
  }, 1000);
}

async function start() {
  if (state.running) return;
  state.running = true;
  state.paused = false;
  const startBtn = overlay.querySelector('[data-demo-start]');
  const pauseBtn = overlay.querySelector('[data-demo-pause]');
  if (startBtn) startBtn.style.display = 'none';
  if (pauseBtn) pauseBtn.style.display = 'inline-block';
  log('info', '演示开始，自动执行五幕脚本...');
  for (let i = 0; i < SCENES.length; i++) {
    if (!state.running) break;
    while (state.paused) { await sleep(500); if (!state.running) break; }
    if (!state.running) break;
    selectScene(i);
    try {
      await SCENES[i].action(log);
    } catch (e) {
      log('error', `第 ${i + 1} 幕执行出错：${e.message}`);
    }
    log('success', `第 ${i + 1} 幕「${SCENES[i].name}」完成`);
    await sleep(800);
  }
  if (state.running) {
    log('success', '🎉 五幕演示全部完成！');
  }
}

function pause() {
  state.paused = !state.paused;
  const btn = overlay.querySelector('[data-demo-pause]');
  if (btn) btn.textContent = state.paused ? '▶ 继续' : '⏸ 暂停';
  log(state.paused ? 'warn' : 'info', state.paused ? '演示已暂停' : '演示继续');
}

async function step() {
  const next = state.current + 1;
  if (next >= SCENES.length) { log('warn', '已是最后一幕'); return; }
  selectScene(next);
  try {
    await SCENES[next].action(log);
  } catch (e) {
    log('error', `第 ${next + 1} 幕执行出错：${e.message}`);
  }
  log('success', `第 ${next + 1} 幕「${SCENES[next].name}」完成`);
  updateProgress();
}

function stop() {
  state.running = false;
  state.paused = false;
  const startBtn = overlay.querySelector('[data-demo-start]');
  const pauseBtn = overlay.querySelector('[data-demo-pause]');
  if (startBtn) startBtn.style.display = 'inline-block';
  if (pauseBtn) { pauseBtn.style.display = 'none'; pauseBtn.textContent = '⏸ 暂停'; }
  log('warn', '演示已停止');
}

function close() {
  stop();
  if (state.timer) clearInterval(state.timer);
  if (overlay) { overlay.remove(); overlay = null; }
  state = null;
}

/* ========== 公开 API ========== */

export function openDemo() {
  if (overlay) return;
  state = { current: -1, running: false, paused: false, startTime: null, timer: null, logs: [] };

  overlay = el(`<div class="demo-overlay">
    <div class="demo-panel">
      <div class="demo-header">
        <div class="demo-title">🎬 GMae 演示模式 <span class="demo-badge">One GPU, Infinite Models</span></div>
        <div class="demo-progress-wrap">
          <div class="demo-progress-bar"><div class="demo-progress-fill" data-demo-progress-fill></div></div>
          <div class="demo-progress-text">
            <span data-demo-progress-text>准备就绪</span>
            <span data-demo-progress-pct>0%</span>
          </div>
        </div>
        <div class="demo-controls">
          <button class="btn btn--sm btn--primary" data-demo-start>▶ 开始演示</button>
          <button class="btn btn--sm" data-demo-pause style="display:none">⏸ 暂停</button>
          <button class="btn btn--sm" data-demo-step>⏭ 单步</button>
          <button class="btn btn--sm btn--danger" data-demo-stop>⏹ 停止</button>
          <button class="demo-close-btn" data-demo-close>✕</button>
        </div>
      </div>
      <div class="demo-body">
        <div class="demo-scenes" data-demo-scenes></div>
        <div class="demo-main">
          <div class="demo-current-title" data-demo-title>选择「开始演示」或点击左侧幕次</div>
          <div class="demo-current-desc" data-demo-desc>GMae（GPU Maestro-显存指挥家）是消费级 AI 服务器的显存编排专家。本演示将展示其在消费级显卡上的强大管理能力：显存秒级释放、进程级强制驱逐、预算引擎智能决策、多模态连续生成、多场景稳定切换。</div>
          <div class="demo-log" data-demo-log></div>
        </div>
      </div>
      <div class="demo-footer">
        <div class="demo-stats">
          <span>已完成幕次：<b data-demo-done>0</b>/${SCENES.length}</span>
          <span>已用时间：<b data-demo-elapsed>00:00</b></span>
          <span>预计剩余：<b data-demo-remaining>--:--</b></span>
          <span>当前显存：<b data-demo-vram>--</b></span>
        </div>
        <div class="text-xs text-muted">演示模式 · 按蓝图第十七章设计 · 预计总时长约 3 分钟 · 危险操作已模拟保护</div>
      </div>
    </div>
  </div>`);

  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add('open'));

  overlay.querySelector('[data-demo-start]').addEventListener('click', start);
  overlay.querySelector('[data-demo-pause]').addEventListener('click', pause);
  overlay.querySelector('[data-demo-step]').addEventListener('click', step);
  overlay.querySelector('[data-demo-stop]').addEventListener('click', stop);
  overlay.querySelector('[data-demo-close]').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

  renderScenes();
  updateProgress();
  startTimer();
  log('info', 'GMae 演示模式已启动');
  log('', '点击「开始演示」自动执行五幕脚本，或点击「单步」逐幕执行，或点击左侧幕次查看详情');
}

export default { openDemo };
