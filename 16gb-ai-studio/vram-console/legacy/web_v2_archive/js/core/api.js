/**
 * GMae 指挥家 v2.0 - core/api.js
 * 统一 API 客户端：封装全部后端接口、错误处理、超时、重试
 *
 * 约定：
 * - 所有请求默认 credentials: 'same-origin'（携带 Session Cookie）
 * - 若 localStorage 存在 .api_token，则附带 X-API-Key（向后兼容脚本/自动化）
 * - GET 请求对网络错误做有限重试；POST 不重试（避免重复副作用）
 * - 401 未认证 → 触发 'auth:unauthorized' 事件（由路由层跳登录页）
 * - 任何失败 → 触发 'api:error' 事件（Toast 层订阅展示）
 */

import { events } from './events.js';

/**
 * v1格式解包：{ok, data, error, meta} → 扁平格式（兼容现有前端代码）
 * v0格式（扁平）直接返回
 */
function unwrap(resp) {
  if (!resp || typeof resp !== 'object') return resp;
  // v1格式：有 data 和 meta 字段
  if ('data' in resp && 'meta' in resp) {
    const flat = { ok: resp.ok !== false };
    if (resp.data && typeof resp.data === 'object') {
      Object.assign(flat, resp.data);
    } else if (resp.data !== null && resp.data !== undefined) {
      flat.data = resp.data;
    }
    if (resp.error) {
      flat.error = typeof resp.error === 'object' ? resp.error.message : resp.error;
      flat.error_code = typeof resp.error === 'object' ? resp.error.code : '';
    }
    flat._meta = resp.meta; // 保留meta供调试
    return flat;
  }
  return resp;
}

const BASE = '';
const DEFAULT_TIMEOUT = 15000;       // 普通请求 15s
const LONG_TIMEOUT = 120000;         // 长操作（场景切换/队列）120s
const GET_RETRIES = 2;               // GET 网络错误重试次数
const RETRY_BASE_MS = 400;

function getToken() {
  try {
    return localStorage.getItem('gm_api_token') || '';
  } catch { return ''; }
}

/** 组装请求头 */
function buildHeaders(jsonBody) {
  const headers = { 'Accept': 'application/json' };
  const token = getToken();
  if (token) headers['X-API-Key'] = token;
  if (jsonBody !== undefined) headers['Content-Type'] = 'application/json';
  return headers;
}

/**
 * 底层请求
 * @param {string} path
 * @param {object} opts { method, body, timeout, retries, silent }
 */
async function request(path, opts = {}) {
  const {
    method = 'GET',
    body,
    timeout = DEFAULT_TIMEOUT,
    retries = 0,
    silent = false,
  } = opts;

  const url = path.startsWith('http') ? path : BASE + path;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const resp = await fetch(url, {
        method,
        headers: buildHeaders(body !== undefined ? body : undefined),
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: 'same-origin',
        signal: controller.signal,
      });

      // 401：认证失效
      if (resp.status === 401) {
        events.emit('auth:unauthorized', { path });
        if (!silent) {
          events.emit('api:error', { message: '登录已失效，请重新登录', path });
        }
        const err = new Error('未认证');
        err.status = 401;
        throw err;
      }

      // 解析响应
      let data = null;
      const ctype = resp.headers.get('content-type') || '';
      if (ctype.includes('application/json')) {
        data = await resp.json();
      } else {
        data = await resp.text();
      }

      // 业务失败（HTTP 4xx/5xx，但 body 可能含后端错误信息）
      if (!resp.ok) {
        const errMsg = data?.error?.message || data?.error || data?.message || `HTTP ${resp.status}`;
        if (!silent) events.emit('api:error', { message: errMsg, path, status: resp.status });
        const err = new Error(errMsg);
        err.status = resp.status;
        err.data = data;
        throw err;
      }

      // 后端约定 { ok:false, error } 或 v1格式 { ok:false, error:{code,message} }
      if (data && typeof data === 'object' && data.ok === false) {
        const errMsg = data?.error?.message || data.error || data.message || '操作失败';
        if (!silent) events.emit('api:error', { message: errMsg, path });
        const err = new Error(errMsg);
        err.data = data;
        throw err;
      }

      // v1格式解包：{ok, data, meta} → 扁平格式（兼容现有前端代码）
      return unwrap(data);
    } catch (err) {
      // AbortError = 超时
      if (err.name === 'AbortError') {
        const timeoutErr = new Error(`请求超时（${Math.round(timeout / 1000)}s）：${path}`);
        timeoutErr.timeout = true;
        if (!silent) events.emit('api:error', { message: timeoutErr.message, path });
        throw timeoutErr;
      }
      // 401 直接抛，不重试
      if (err.status === 401) throw err;
      lastErr = err;
      // 网络错误且还有重试次数 → 退避重试
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, RETRY_BASE_MS * (attempt + 1)));
        continue;
      }
      if (!silent) events.emit('api:error', { message: `网络错误：${err.message}`, path });
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastErr;
}

/* ========== 基础方法 ========== */

/** GET（幂等，自动重试网络错误） */
function get(path, opts = {}) {
  return request(path, { ...opts, method: 'GET', retries: GET_RETRIES });
}

/** POST（不重试） */
function post(path, body, opts = {}) {
  return request(path, { ...opts, method: 'POST', body });
}

/* ========== 认证 API（无需登录） ========== */

export const authApi = {
  status: () => get('/api/auth/status'),
  setup: (email, password) => post('/api/auth/setup', { email, password }),
  login: (email, password, remember = false) =>
    post('/api/auth/login', { email, password, remember }, { silent: true }),
  forgot: (email) => post('/api/auth/forgot', { email }),
  reset: (email, code, password) => post('/api/auth/reset', { email, code, password }),
  logout: () => post('/api/auth/logout', {}, { silent: true }),
  changePassword: (old_password, new_password) =>
    post('/api/auth/change-password', { old_password, new_password }),
};

/* ========== 核心 API（需认证） ========== */

export const api = {
  /** 健康检查（免认证） */
  health: () => get('/api/health', { silent: true }),

  /** 总状态（显存/模型/进程/场景等聚合） */
  status: () => get('/api/status', { timeout: LONG_TIMEOUT }),

  /** 模型登记台 */
  registry: () => get('/api/registry'),

  /** 预算引擎，支持 context 覆盖：{ modelId: ctxSize } */
  budget: (contextOverrides) => {
    if (contextOverrides && Object.keys(contextOverrides).length) {
      // 注意：整体一次 encodeURIComponent，避免二次编码（% 变 %25）
      const items = Object.entries(contextOverrides)
        .map(([id, ctx]) => `${id}:${ctx}`)
        .join(',');
      return get(`/api/budget?context=${encodeURIComponent(items)}`);
    }
    return get('/api/budget');
  },

  /** ComfyUI 实时事件 */
  comfyEvents: () => get('/api/comfy_events'),

  /** 桌面进程显存明细 */
  desktopVram: () => get('/api/desktop_vram'),

  /** 智能建议 + 未归因显存诊断（第二层，2026-08-31） */
  advice: () => get('/api/advice', { timeout: LONG_TIMEOUT }),

  /** 自动防死机（第三层，2026-08-31）：状态/配置 */
  autoProtectStatus: () => get('/api/auto-protect/status'),
  autoProtectConfig: (cfg) => post('/api/auto-protect/config', cfg),

  /** 桌面 Helper 状态 */
  helperStatus: () => get('/api/desktop/helper/status'),

  /** 模型扫描（新/缺失/一致） */
  scan: () => get('/api/scan'),

  /** 结构化事件日志（后端 /api/logs，默认 150 条） */
  logs: (limit = 150) => get(`/api/logs?limit=${limit}`),

  /** 任务队列快照 */
  queue: () => get('/api/queue'),

  /* ---- 操作类 POST ---- */

  /** 场景切换 */
  scene: (scene) => post('/api/scene', { scene }, { timeout: LONG_TIMEOUT }),

  /** 组合切换 */
  combo: (combo) => post('/api/combo', { combo }, { timeout: LONG_TIMEOUT }),

  /** 释放 ComfyUI 显存 */
  free: () => post('/api/free', {}, { timeout: LONG_TIMEOUT }),

  /** 门卫：check（只读）/ evict（软驱逐）/ kick（L2 强制驱逐指定 pid） */
  guardCheck: () => post('/api/guard', {}, { timeout: LONG_TIMEOUT }),
  guardEvict: () => post('/api/guard', { evict: true }, { timeout: LONG_TIMEOUT }),
  guardKick: (pid) => post('/api/guard', { action: 'kick', pid }, { timeout: LONG_TIMEOUT }),

  /** QoS */
  qosStatus: () => post('/api/qos/status', {}),
  qosCheck: () => post('/api/qos/check', {}),
  qosExecute: (suggestion_id) => post('/api/qos/execute', { suggestion_id }, { timeout: LONG_TIMEOUT }),

  /** 服务操作（start/stop/restart/status） */
  service: (name, action) => post('/api/service', { name, action }, { timeout: LONG_TIMEOUT }),

  /** 模型操作（load/unload/run/stop） */
  model: (name, action) => post('/api/model', { name, action }, { timeout: LONG_TIMEOUT }),

  /** 桌面进程：强制结束 */
  desktopKill: (pid) => post('/api/desktop/kill', { pid }, { timeout: LONG_TIMEOUT }),

  /** 桌面 Helper 启动/停止 */
  helperStart: () => post('/api/desktop/helper/start', {}, { timeout: LONG_TIMEOUT }),
  helperStop: () => post('/api/desktop/helper/stop', {}),

  /** 停止指定 Docker 容器（释放结果弹窗中的"结束"按钮） */
  containerStop: (name) => post('/api/container/stop', { name }, { timeout: LONG_TIMEOUT }),

  /** 任务队列：入队 / 取消 */
  queueEnqueue: (model, params = {}) => post('/api/queue', { model, params }, { timeout: LONG_TIMEOUT }),
  queueCancel: (id) => post('/api/queue/cancel', { id }),

  /** 扫描后登记 */
  scanRegister: (source, name, vramGb, category) =>
    post('/api/scan/register', { source, name, vram_gb: vramGb, category }),
};

export default api;
