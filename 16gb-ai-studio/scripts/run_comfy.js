// 通用 ComfyUI 工作流运行器：提交 → 轮询 → 拉取全部输出（图片/视频/音频）
// 用法: node run_comfy.js <workflow.json> <outprefix> [timeout_minutes]
// 配置: 环境变量 COMFY_HOST（默认 localhost）、COMFY_PORT（默认 8188）、OUTPUT_DIR（默认 ./outputs）
//       环境变量 RUN_TIMEOUT（分钟，默认 30）
const http = require('http');
const fs = require('fs');
const path = require('path');

const COMFY_HOST = process.env.COMFY_HOST || 'localhost';
const COMFY_PORT = parseInt(process.env.COMFY_PORT || '8188');
const OUTPUT_DIR = process.env.OUTPUT_DIR || path.join(__dirname, '..', 'outputs');
const TIMEOUT_MIN = parseInt(process.env.RUN_TIMEOUT || process.argv[4] || '30');

const wfFile = process.argv[2];
const outPrefix = process.argv[3] || 'out';

// 校验 workflow 文件
if (!wfFile) {
  console.error('Usage: node run_comfy.js <workflow.json> <outprefix> [timeout_minutes]');
  process.exit(1);
}
if (!fs.existsSync(wfFile)) {
  console.error('ERROR: workflow file not found:', wfFile);
  process.exit(1);
}
let prompt;
try {
  prompt = JSON.parse(fs.readFileSync(wfFile, 'utf8'));
} catch (e) {
  console.error('ERROR: invalid JSON in workflow file:', e.message);
  process.exit(1);
}

// 确保输出目录存在
if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR, { recursive: true });

function req(method, urlPath, body, binary) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const r = http.request({ host: COMFY_HOST, port: COMFY_PORT, path: urlPath, method, headers: data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {} }, res => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, body: binary ? Buffer.concat(chunks) : Buffer.concat(chunks).toString('utf8') }));
    });
    r.on('error', reject);
    if (data) r.write(data);
    r.end();
  });
}

(async () => {
  const sub = await req('POST', '/prompt', { prompt, client_id: 'local-ai-studio-' + outPrefix });
  console.log('submit status', sub.status);
  if (sub.status !== 200) { console.log(sub.body.slice(0, 3000)); process.exit(1); }
  const { prompt_id } = JSON.parse(sub.body);
  console.log('prompt_id', prompt_id);
  const t0 = Date.now();
  const deadline = t0 + TIMEOUT_MIN * 60000;
  let loggedFive = new Set();
  for (;;) {
    if (Date.now() > deadline) {
      console.log('TIMEOUT: exceeded ' + TIMEOUT_MIN + ' minutes, aborting.');
      process.exit(1);
    }
    await new Promise(r => setTimeout(r, 15000));
    const h = await req('GET', '/history/' + prompt_id);
    let hist = {};
    try { hist = JSON.parse(h.body); } catch (e) {}
    const entry = hist[prompt_id];
    if (entry) {
      if (entry.status && entry.status.status_str === 'error') {
        console.log('RUN ERROR:', JSON.stringify(entry.status).slice(0, 3000));
        process.exit(1);
      }
      const outputs = entry.outputs || {};
      const min = Math.round((Date.now() - t0) / 60000);
      for (const id of Object.keys(outputs)) {
        const o = outputs[id];
        const items = [];
        for (const im of (o.images || [])) items.push({ f: im.filename, s: im.subfolder || '', k: im.type || 'output' });
        for (const au of (o.audio || [])) items.push({ f: au.filename, s: au.subfolder || '', k: au.type || 'output' });
        for (const it of items) {
          const v = await req('GET', '/view?filename=' + encodeURIComponent(it.f) + '&subfolder=' + encodeURIComponent(it.s) + '&type=' + encodeURIComponent(it.k), null, true);
          if (v.status === 200) {
            const out = path.join(OUTPUT_DIR, outPrefix + '_' + it.f.replace(/[\\\/]/g, '_'));
            fs.writeFileSync(out, v.body);
            console.log('OUTPUT(node ' + id + ', ' + min + 'min): ' + out + ' (' + Math.round(v.body.length / 1024) + 'KB)');
          } else console.log('view fetch status', v.status, it.f);
        }
      }
      if (entry.status && entry.status.completed) { console.log('RUN COMPLETED in ' + min + 'min'); process.exit(0); }
    }
    const min = Math.round((Date.now() - t0) / 60000);
    if (min > 0 && min % 5 === 0 && !loggedFive.has(min)) {
      loggedFive.add(min);
      console.log('... still running, elapsed ' + min + 'min (timeout ' + TIMEOUT_MIN + 'min)');
    }
  }
})().catch(e => { console.log('ERR', e.message); process.exit(1); });
