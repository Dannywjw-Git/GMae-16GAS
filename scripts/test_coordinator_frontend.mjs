// Exercise the actual queue page methods with a small DOM/API harness.
// This verifies presentation behavior, not browser layout or GPU execution.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const elements = new Map([
  ['#resource-coordination', {innerHTML: ''}],
  ['#task-budget', {innerHTML: ''}],
  ['#btn-submit-task', {disabled: true}],
  ['#task-model', {value: 'registered-model'}],
  ['#task-list', {innerHTML: ''}],
  ['#q-waiting', {}],
]);
const Pages = {};
const calls = [];
let response = {ok: true, allowed: true, execution_ready: false, reason: '<busy>', budget: {vram_gb: 8}};
let rejectPreview = false;
let queueResponse = {ok: true, tasks: [{id: 'full-id', model: 'm', status: 'waiting_resource', progress: '<wait>'}],
  coordination: {active: {owner: 'job', phase: 'running'}, reserved_mb: 8192}};
const context = vm.createContext({
  Pages,
  Utils: {$: selector => elements.get(selector), escapeHtml: value => String(value)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')},
  API: {
    getQueue: async () => queueResponse,
    previewResources: async body => {calls.push(body); if (rejectPreview) throw Error('offline'); return response;},
    cancelTask: async body => {calls.push(body); return {ok: true, note: 'requested'};},
  },
  Toast: {success() {}, error() {}},
  Modal: {confirm: options => options.onConfirm()},
  Icons: {},
});
vm.runInContext(fs.readFileSync(new URL('../16gb-ai-studio/vram-console/web/js/pages/queue.js', import.meta.url), 'utf8'), context);

Pages._renderCoordination({});
assert.match(elements.get('#resource-coordination').innerHTML, /资源状态不可用/);
Pages._renderCoordination({active: null});
assert.match(elements.get('#resource-coordination').innerHTML, /资源可申请/);
Pages._renderCoordination({active: {owner: '<job>', phase: 'uncertain', target_model: 'model-a'}, reserved_mb: 8192});
const banner = elements.get('#resource-coordination').innerHTML;
assert.match(banner, /执行状态待核验/);
assert.match(banner, /&lt;job&gt;/);
assert.match(banner, /model-a/);
assert.match(banner, /8 GiB/);
assert.match(banner, /btn-resource-reconcile/);

await Pages._checkTaskBudget();
assert.equal(elements.get('#btn-submit-task').disabled, false);
assert.match(elements.get('#task-budget').innerHTML, /可排队/);
assert.match(elements.get('#task-budget').innerHTML, /&lt;busy&gt;/);
assert.equal(JSON.stringify(calls.pop()), JSON.stringify({source: 'comfyui', model: 'registered-model'}));
response = {ok: false, allowed: false, reason: 'uncalibrated'};
await Pages._checkTaskBudget();
assert.equal(elements.get('#btn-submit-task').disabled, true);
rejectPreview = true;
await Pages._checkTaskBudget();
assert.equal(elements.get('#btn-submit-task').disabled, true);
assert.match(elements.get('#task-budget').innerHTML, /不可用/);

Pages._hiddenTaskIds = new Set();
await Pages._loadQueue();
assert.equal(elements.get('#q-waiting').textContent, 1);
assert.match(elements.get('#task-list').innerHTML, /waiting_resource/);
assert.match(elements.get('#task-list').innerHTML, /&lt;wait&gt;/);
queueResponse = {ok: false, error: {message: 'offline'}};
await Pages._loadQueue();
assert.match(elements.get('#task-list').innerHTML, /队列接口不可用/);
assert.match(elements.get('#resource-coordination').innerHTML, /资源状态不可用/);

Pages._loadQueue = () => {};
await Pages._cancelTask('full-task-id');
assert.equal(JSON.stringify(calls.pop()), JSON.stringify({id: 'full-task-id'}));
console.log('Coordinator frontend behavior checks passed');
