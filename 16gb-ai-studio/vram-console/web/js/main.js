/**
 * GMae 指挥家 v2.0 - 应用入口（main.js）
 * 职责：装配核心模块 → 构建布局（sidebar+header+content）→ 注册页面 → 启动路由
 * 技术规范：ES Modules，无全局变量，零构建工具
 */

import { store } from './core/state.js';
import { events } from './core/events.js';
import router, { register, setContainer } from './core/router.js';
import { authApi } from './core/api.js';
import toast from './components/toast.js';
import sidebar from './components/sidebar.js';
import header from './components/header.js';

export const APP_VERSION = 'v2.0.0-alpha';
export const APP_NAME = 'GMae 指挥家';

/* ========== 布局构建 ========== */

function buildLayout() {
  const app = document.getElementById('app');
  app.innerHTML = `
    <div class="app">
      <div data-slot="sidebar"></div>
      <div class="app-main">
        <div data-slot="header"></div>
        <main class="app-content" id="app-content"></main>
      </div>
    </div>
  `;
  app.querySelector('[data-slot="sidebar"]').appendChild(sidebar.render());
  app.querySelector('[data-slot="header"]').appendChild(header.render());
  // 页面渲染到 content 区
  setContainer('#app-content');
}

/* ========== 全局事件接线 ========== */

function wireGlobalEvents() {
  // 认证失效 → 跳回登录页
  events.on('auth:unauthorized', () => {
    window.location.href = '/login';
  });

  // API 错误 → 统一打印（Toast 组件会展示）
  events.on('api:error', ({ message }) => {
    if (message) console.warn(`[api] ${message}`);
  });

  // 路由变化 → 同步 store.ui.activePage + 更新顶栏标题
  events.on('route:change', ({ name, found, title }) => {
    if (found) store.update('ui', { activePage: name });
  });
}

/* ========== 页面注册 ========== */

async function registerPages() {
  // v2.0 信息架构：总览 / 观测 / 诊断 / 工作负载 / 设置
  const { default: dashboard } = await import('./pages/dashboard.js');
  register('dashboard', dashboard);

  const { default: observability } = await import('./pages/observability.js');
  register('observability', observability);

  const { default: diagnostics } = await import('./pages/diagnostics.js');
  register('diagnostics', diagnostics);

  const { default: workloads } = await import('./pages/workloads.js');
  register('workloads', workloads);

  const { default: settings } = await import('./pages/settings.js');
  register('settings', settings);

  // 旧页面保留注册（可通过直接访问URL进入，后续迭代移除）
  const { default: chat } = await import('./pages/chat.js');
  register('chat', chat);
  const { default: models } = await import('./pages/models.js');
  register('models', models);
  const { default: vram } = await import('./pages/vram.js');
  register('vram', vram);
  const { default: scenes } = await import('./pages/scenes.js');
  register('scenes', scenes);
  const { default: queue } = await import('./pages/queue.js');
  register('queue', queue);
  const { default: guard } = await import('./pages/guard.js');
  register('guard', guard);
  const { default: logs } = await import('./pages/logs.js');
  register('logs', logs);
}

/* ========== 启动 ========== */

async function bootstrap() {
  store.update('ui', { version: APP_VERSION });
  toast.init();
  wireGlobalEvents();
  buildLayout();

  // 认证状态初始化
  try {
    const auth = await authApi.status();
    store.set('auth', auth);
    header.setTitle('总览');
  } catch (e) {
    store.set('auth', { status: 'unknown', error: String(e.message || e) });
  }

  await registerPages();
  router.start();

  console.log(`[GMae] ${APP_NAME} ${APP_VERSION} 已启动，页面：${router.list().join(', ')}`);
}

bootstrap();
