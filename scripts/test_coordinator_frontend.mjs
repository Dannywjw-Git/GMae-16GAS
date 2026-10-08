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
  ['#task-prompt', {value: 'test prompt'}],
  ['#task-width', {value: '512'}],
  ['#task-height', {value: '768'}],
  ['#task-steps', {value: '8'}],
  ['#task-cfg', {value: '0'}],
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
assert.equal(JSON.stringify(calls.pop()), JSON.stringify({source: 'comfyui', model: 'registered-model',
  params: {prompt: 'test prompt', width: 512, height: 768, steps: 8, cfg: 0}}));
response = {ok: false, allowed: false, reason: 'uncalibrated'};
await Pages._checkTaskBudget();
assert.equal(elements.get('#btn-submit-task').disabled, true);
rejectPreview = true;
await Pages._checkTaskBudget();
assert.equal(elements.get('#btn-submit-task').disabled, true);
assert.match(elements.get('#task-budget').innerHTML, /不可用/);

// An older allowed result must not override a newer rejected parameter preview.
let resolveOld;
let previewCount = 0;
context.API.previewResources = body => {
  calls.push(body);
  return ++previewCount === 1 ? new Promise(resolve => { resolveOld = resolve; })
    : Promise.resolve({allowed: false, reason: 'new parameters require evidence'});
};
const oldPreview = Pages._checkTaskBudget();
elements.get('#task-width').value = '2048';
await Pages._checkTaskBudget();
resolveOld({allowed: true, execution_ready: true, budget: {vram_gb: 8}});
await oldPreview;
assert.equal(elements.get('#btn-submit-task').disabled, true);
assert.match(elements.get('#task-budget').innerHTML, /new parameters require evidence/);

Pages._hiddenTaskIds = new Set();
await Pages._loadQueue();
assert.equal(elements.get('#q-waiting').textContent, 1);
assert.match(elements.get('#task-list').innerHTML, /waiting_resource/);
assert.match(elements.get('#task-list').innerHTML, /&lt;wait&gt;/);
queueResponse = {ok: false, error: {message: 'offline'}};
await Pages._loadQueue();
assert.match(elements.get('#task-list').innerHTML, /队列接口不可用/);
assert.match(elements.get('#resource-coordination').innerHTML, /资源状态不可用/);

queueResponse = {ok: true, tasks: [{id: 'ollama-id', model: 'qwen', source: 'ollama', status: 'done',
  result: {response: '<script>untrusted output</script>', metrics: {eval_count: 24}}}], coordination: {active: null}};
await Pages._loadQueue();
assert.match(elements.get('#task-list').innerHTML, /文本结果（24 tokens）/);
assert.match(elements.get('#task-list').innerHTML, /&lt;script&gt;untrusted output&lt;\/script&gt;/);
assert.doesNotMatch(elements.get('#task-list').innerHTML, /<script>/);
Pages._expandedTaskOutputs = new Set(['ollama-id']);
await Pages._loadQueue();
assert.match(elements.get('#task-list').innerHTML, /data-task-output="ollama-id" open/);
Pages._loadQueue = () => {};
await Pages._cancelTask('full-task-id');
assert.equal(JSON.stringify(calls.pop()), JSON.stringify({id: 'full-task-id'}));
console.log('Coordinator frontend behavior checks passed');

// Measured presets preserve retry identity, cannot edit the server payload,
// and treat discovery as evidence only rather than a live permission check.
elements.set('#measured-preset', {value: 'preset-id', innerHTML: ''});
elements.set('#measured-preset-info', {innerHTML: ''});
elements.set('#btn-submit-preset', {disabled: true});
context.crypto = {getRandomValues: array => {array.fill(7); return array;}};
let catalogResponse = {ok: true, presets: [{id: 'preset-id', model: '<model>', context_length: 8192,
  prompt_tokens: 6182, max_output_tokens: 32, measured_peak_mb: 8321, envelope_mb: 8833,
  evidence_sha256: 'a'.repeat(64)}], limitation: '<fixed request>'};
context.API.getMeasuredPresets = async () => catalogResponse;
const submissions = [];
context.API.submitMeasuredPreset = async body => {submissions.push(body); return {ok: false, error: {message: 'timeout'}};};
await Pages._loadMeasuredPresets();
assert.equal(elements.get('#btn-submit-preset').disabled, false);
assert.match(elements.get('#measured-preset').innerHTML, /&lt;model&gt;/);
assert.match(elements.get('#measured-preset-info').innerHTML, /8833/);
assert.match(elements.get('#measured-preset-info').innerHTML, /&lt;fixed request&gt;/);
await Pages._submitMeasuredPreset();
await Pages._submitMeasuredPreset();
assert.deepEqual(Object.keys(submissions[0]).sort(), ['idempotency_key', 'preset_id']);
assert.equal(submissions[0].idempotency_key, submissions[1].idempotency_key);
context.API.submitMeasuredPreset = async body => {submissions.push(body); return {ok: true};};
await Pages._submitMeasuredPreset();
assert.equal(submissions[2].idempotency_key, submissions[0].idempotency_key);
assert.equal(Pages._pendingPresetSubmission, null);
catalogResponse = {ok: false, error: {message: '<offline>'}};
await Pages._loadMeasuredPresets();
assert.equal(elements.get('#btn-submit-preset').disabled, true);
assert.match(elements.get('#measured-preset-info').innerHTML, /&lt;offline&gt;/);
await Pages._submitMeasuredPreset();
assert.equal(submissions.length, 3);
let resolveOldCatalog;
let catalogCalls = 0;
context.API.getMeasuredPresets = () => ++catalogCalls === 1
  ? new Promise(resolve => {resolveOldCatalog = resolve;}) : Promise.resolve({ok: true, presets: []});
const oldCatalog = Pages._loadMeasuredPresets();
await Pages._loadMeasuredPresets();
resolveOldCatalog({ok: true, presets: [{id: 'preset-id'}]});
await oldCatalog;
assert.equal(elements.get('#btn-submit-preset').disabled, true);
assert.equal(Pages._measuredPresets.length, 0);
console.log('Measured preset submission checks passed');
