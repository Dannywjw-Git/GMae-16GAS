/**
 * GMae 指挥家 v2.0 - 应用入口
 * 模块化前端重写版本
 */

const APP_VERSION = 'v2.0.0-alpha';
const APP_NAME = 'GMae 指挥家';

function init() {
  const app = document.getElementById('app');
  if (!app) return;

  app.innerHTML = `
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;background:#121212;color:#e0e0e0;font-family:sans-serif;">
      <div style="font-size:48px;margin-bottom:16px;">🎼</div>
      <h1 style="font-size:24px;margin-bottom:8px;color:#5c6bc0;">${APP_NAME}</h1>
      <div style="font-size:14px;color:#9e9e9e;margin-bottom:32px;">版本 ${APP_VERSION}</div>
      <div style="background:#1e1e1e;padding:24px 32px;border-radius:12px;border:1px solid #333;max-width:500px;text-align:center;">
        <div style="font-size:16px;margin-bottom:12px;color:#e0e0e0;">🚧 前端模块化重写进行中</div>
        <div style="font-size:13px;color:#9e9e9e;line-height:1.8;">
          新前端采用 ES Modules 模块化架构<br>
          核心层 / 组件层 / 页面层 三级隔离<br>
          预计分 5 个阶段完成全部功能迁移
        </div>
      </div>
      <div style="margin-top:32px;font-size:12px;color:#616161;">
        如需使用旧版，请设置环境变量 FRONTEND_VERSION=v1 后重启服务
      </div>
    </div>
  `;

  console.log(`[GMae] ${APP_NAME} ${APP_VERSION} 已启动`);
}

// DOM 就绪后初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
