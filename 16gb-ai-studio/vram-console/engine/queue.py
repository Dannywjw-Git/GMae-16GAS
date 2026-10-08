#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae 任务队列模块
- 16G 单卡串行化：提交→排队→预检→释放→加载→生成→完成
- 生成时间统计（预演模式"预计时间"用）
"""
import json
import math
from dataclasses import replace
import os
import threading
import time
import uuid
import urllib.request
import urllib.error
from collections import deque
from core.logger import log_event, log_error
from core.config import REGISTRY, BASE_DIR
from core.registry import registry
from engine.coordinator import OperationSpec, coordinated_operation, _model_budget
from core.resource_coordinator import ResourceDenied
from core.exceptions import ConfigError
from core.task_store import TaskStore, TaskConflict
from core.task_dispatch import TaskDispatcher, DispatchUncertain
from core.workload_profile import workload_fingerprint, resource_configuration_fingerprint
from engine.gen_stats import load_gen_stats, save_gen_stats, update_gen_stats

# 队列状态 — 已迁移到 registry（状态包装）
_QUEUE_CLIENT_ID = str(uuid.uuid4())
_queue_state = registry.get("queue_state")
if _queue_state is None:
    _queue_state = {
        "tasks": {},
        "task_queue": deque(),
        "worker_alive": False,
    }
    registry.set("queue_state", _queue_state)

# 可变对象直接引用（修改字段不需要 global）
_tasks = _queue_state["tasks"]
_task_queue = _queue_state["task_queue"]
_task_lock = threading.RLock()


def _store():
    with _task_lock:
        store = registry.get('task_store')
        if store is None:
            store = TaskStore(os.environ.get('GMAE_TASK_DB', os.path.join(BASE_DIR, 'data', 'tasks.sqlite3')))
            registry.set('task_store', store)
        return store


def _runtime_task(record):
    return {**record['intent'], 'id': record['id'], 'status': record['status'],
            'created': record['created'], 'started': None, 'ended': None,
            'error': '', 'progress': '', 'prompt_id': None, 'result': None,
            **record['checkpoint'], '_version': record['version']}


def _persist(task, status=None, **fields):
    """Commit before publishing in-memory changes; caller uses the same RLock."""
    with _task_lock:
        status = status or task['status']
        if '_version' in task:
            record = _store().checkpoint(task['id'], task['_version'], status, fields)
            task['_version'] = record['version']
        task.update(fields)
        task['status'] = status


def _start_worker():
    if _task_queue and not _queue_state['worker_alive']:
        _queue_state['worker_alive'] = True
        threading.Thread(target=_queue_worker, daemon=True).start()


def queue_restore():
    """Restore durable facts before background mutation threads or new requests.

    Storage errors abort startup. Unknown execution installs GPU holds; only
    pre-submission tasks may be resumed. No backend request is issued here.
    """
    from engine.coordinator import get_coordinator
    from core.resource_coordinator import ResourceRequest
    with _task_lock:
        if _queue_state.get('restored'):
            return
        records = _store().snapshot()
        journal = registry.get('operation_journal')
        journal_records = {row['intent']['owner']: row for row in journal.pending()} if journal else {}
        journal_ids = {owner:row['id'] for owner,row in journal_records.items()}
        for record in records:
            task = _runtime_task(record)
            _tasks[task['id']] = task
            if task['status']=='running' and _confirmed_ollama_completion(task):
                operation=journal_records.get('job:'+task['id'])
                if operation and (operation['intent'].get('service')!='ollama'
                                  or operation['intent'].get('model')!=task['model']):
                    raise ConfigError('Ollama 完成回执与资源日志意图冲突')
                _persist(task,'canceled' if task.get('cancel_requested') else 'done',
                         ended=int(time.time()),progress='重启后核验已持久化完整回执，不重放')
                if operation:
                    journal.finish(operation['id'],True,{'terminal':True,'job_id':task['id'],
                        'basis':'persisted_exact_ollama_completion'})
                continue
            if task['status'] in ('submitting', 'running', 'uncertain'):
                lease = get_coordinator().restore_uncertain(
                    ResourceRequest('generate', 'job:' + task['id'], task.get('source','comfyui'), task['model']),
                    {'job_id': task['id'],
                     **({'prompt_id': task.get('prompt_id') or task.get('submission_id')}
                        if task.get('source','comfyui')=='comfyui' else {}),
                     **({'journal_id': journal_ids['job:' + task['id']]} if 'job:' + task['id'] in journal_ids else {}),
                     'reason': '进程重启后执行未知，必须核验对应后端任务'})
                _persist(task, 'uncertain', coordination={'token': lease.token, 'owner': 'job:' + task['id']})
            elif task['status'] in ('queued', 'waiting_resource', 'precheck'):
                if task.get('cancel_requested'):
                    _persist(task, 'canceled', ended=int(time.time()))
                else:
                    _task_queue.append(task['id'])
        _queue_state['restored'] = True
        _start_worker()

# 生成时间统计


def _load_workflow(workflow_name):
    """读取工作流模板（vram-console/workflows/ 下），返回 dict；失败返回 None。"""
    p = os.path.join(BASE_DIR, "workflows", workflow_name)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        raise ConfigError("工作流模板解析失败: %s" % workflow_name, detail={"file": p}) from e


def _apply_params(wf, params):
    """Bind supported parameters; never silently ignore a requested control."""
    if not isinstance(params, dict):
        raise ValueError('params 必须是对象')
    aliases = {'frames': ('length', 'frames', 'num_frames'),
               'duration': ('seconds', 'duration', 'max_duration'),
               'cfg': ('cfg', 'cfg_scale')}
    integer_keys = {'seed', 'width', 'height', 'steps', 'frames', 'batch_size'}
    allowed = integer_keys | {'prompt', 'cfg', 'filename_prefix', 'duration'}
    if set(params) - allowed:
        raise ValueError('不支持的任务参数: ' + ', '.join(sorted(set(params) - allowed)))
    normalized = {}
    for key, value in params.items():
        if key in ('prompt', 'filename_prefix'):
            if not isinstance(value, str):
                raise ValueError(key + ' 必须是字符串')
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(key + ' 必须是有限数值')
            if key in integer_keys:
                if int(value) != value:
                    raise ValueError(key + ' 必须是整数')
                value = int(value)
            if value < 0 or (key not in ('seed', 'cfg') and value == 0):
                raise ValueError(key + ' 超出有效范围')
        normalized[key] = value
    wf = json.loads(json.dumps(wf, allow_nan=False))
    prompt_done = False
    applied = set()
    for node in wf.values():
        if not isinstance(node, dict):
            raise ValueError('工作流节点必须是对象')
        ins = node.get("inputs")
        if not isinstance(ins, dict):
            continue
        if "prompt" in normalized and not prompt_done:
            if "text" in ins:
                ins["text"] = normalized["prompt"]
                prompt_done = True
            elif "caption" in ins:
                ins["caption"] = normalized["prompt"]
                prompt_done = True
        if prompt_done:
            applied.add('prompt')
        for key, value in normalized.items():
            if key == 'prompt':
                continue
            for target in aliases.get(key, (key,)):
                if target in ins and not isinstance(ins[target], list):
                    ins[target] = value
                    applied.add(key)
    if set(normalized) - applied:
        raise ValueError('工作流没有可绑定的参数: ' + ', '.join(sorted(set(normalized) - applied)))
    return wf


def queue_enqueue(model: str, params: dict, idempotency_key=None) -> dict:
    """提交任务入队。model=registry comfyui 模型 id；params={prompt,seed,width,height,...}"""
    m = next((x for x in REGISTRY.get("comfyui", {}).get("models", []) if x["id"] == model), None)
    if not m:
        return {"ok": False, "error": "unknown model: " + model}
    wf_name = m.get("workflow")
    template = _load_workflow(wf_name) if wf_name else None
    if not template:
        return {"ok": False, "error": "工作流模板缺失: %s（需先在 ComfyUI 前端导出到 vram-console/workflows/）" % wf_name}
    if not isinstance(params, dict):
        return {'ok': False, 'code': 'INVALID_INTENT', 'error': 'params 必须是对象'}
    try:
        effective = _apply_params(template, params)
        fingerprint = workload_fingerprint(effective)
        configuration = resource_configuration_fingerprint(template)
        from engine.profile_admission import select_profile
        profile_reference = select_profile(effective)
        if resource_configuration_fingerprint(effective) != configuration and profile_reference is None:
            return {'ok': False, 'code': 'PROFILE_REQUIRED',
                    'error': '任务资源参数与登记模板不同，缺少匹配测量 Profile，拒绝复用固定显存预算'}
        queue_restore()
        with _task_lock:
            record, created = _store().accept(
                {'model': model, 'workflow': wf_name, 'params': params,
                 'effective_workflow': effective, 'workflow_sha256': fingerprint,
                 'resource_configuration_sha256': configuration,
                 **({'profile_reference': profile_reference} if profile_reference is not None else {})}, idempotency_key)
            tid = record['id']
            task = _tasks.get(tid) or _runtime_task(record)
            _tasks[tid] = task
            if created:
                _task_queue.append(tid)
            _start_worker()
    except TaskConflict as error:
        return {'ok': False, 'code': 'IDEMPOTENCY_CONFLICT', 'error': str(error)}
    except ResourceDenied as error:
        return error.result()
    except ValueError as error:
        return {'ok': False, 'code': 'INVALID_INTENT', 'error': str(error)}
    except Exception as error:
        return {'ok': False, 'code': 'TASK_STORAGE_UNAVAILABLE', 'error': str(error)}
    log_event("queue_enqueue", task=tid, model=model, workflow=wf_name)
    return {"ok": True, "task": dict(task), 'created': created}


def _queue_submit_comfy(wf, submission_id=None):
    """POST ComfyUI /prompt 提交工作流，返回 prompt_id / 错误。"""
    from engine.coordinator import get_coordinator
    if not get_coordinator().current_token():
        raise ResourceDenied("INVALID_LEASE", "提交工作流必须持有资源预留")
    payload = {"prompt": wf, "client_id": _QUEUE_CLIENT_ID, "prompt_id": submission_id}
    try:
        req = urllib.request.Request("http://127.0.0.1:8188/prompt",
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("prompt_id"), None
    except urllib.error.HTTPError as e:
        return None, {"message": str(e), "uncertain": e.code >= 500}
    except Exception as e:
        return None, {"message": str(e), "uncertain": True}


def queue_enqueue_ollama(request, idempotency_key=None):
    """Accept an exact measured request; backend supplies no durable request ID."""
    try:
        request=_validate_ollama_request(request)
        from engine.profile_admission import select_profile
        reference=select_profile(request)
        if reference is None:
            return {'ok':False,'code':'PROFILE_REQUIRED','error':'Ollama 请求缺少精确测量 Profile'}
        queue_restore()
        with _task_lock:
            record,created=_store().accept(dict(source='ollama',model=request['model'],
                effective_workflow=request,workflow_sha256=workload_fingerprint(request),
                profile_reference=reference),idempotency_key)
            task=_tasks.get(record['id']) or _runtime_task(record)
            _tasks[record['id']]=task
            if created: _task_queue.append(record['id'])
            _start_worker()
        return {'ok':True,'created':created,'task':dict(task)}
    except TaskConflict as error:
        return {'ok':False,'code':'IDEMPOTENCY_CONFLICT','error':str(error)}
    except ResourceDenied as error:
        return error.result()
    except (ValueError,TypeError,KeyError) as error:
        return {'ok':False,'code':'INVALID_INTENT','error':str(error)}
    except Exception as error:
        return {'ok':False,'code':'TASK_STORAGE_UNAVAILABLE','error':str(error)}


def _validate_ollama_request(request):
    if not isinstance(request,dict) or set(request)!={'model','prompt','think','stream','keep_alive','options'}:
        raise ValueError('需提供完整有限 Ollama 请求，不允许额外参数')
    options=request['options']
    if (request['think'] is not False or request['stream'] is not False
            or not isinstance(request['prompt'],str) or not request['prompt']
            or not isinstance(request['keep_alive'],str) or request['keep_alive']!='30m'
            or not isinstance(options,dict) or set(options)!={'num_ctx','num_predict','temperature','seed'}):
        raise ValueError('不支持的 Ollama 请求选项')
    if (type(options['num_ctx']) is not int or not 1<=options['num_ctx']<=8192
            or type(options['num_predict']) is not int or not 1<=options['num_predict']<=32
            or type(options['seed']) is not int or options['temperature']!=0):
        raise ValueError('上下文或有限输出参数无效')
    if not any(m['id']==request['model'] for m in REGISTRY.get('ollama',{}).get('models',[])):
        raise ValueError('Ollama 模型未登记')
    return json.loads(json.dumps(request,allow_nan=False))


def _queue_wait(prompt_id, task, timeout=3600):
    """轮询 /history/{prompt_id} 直到 success/error，回填进度。"""
    url = "http://127.0.0.1:8188/history/%s" % prompt_id
    deadline = time.time() + timeout
    while time.time() < deadline:
        if task.get('cancel_requested'):
            cancellation = task.get('backend_cancel', {})
            if (cancellation.get('acknowledged') is not True and
                    cancellation.get('code') not in ('CANCEL_UNSUPPORTED', 'INVALID_BACKEND_ID')):
                _cancel_backend(task)
            cancellation = task.get('backend_cancel', {})
            if cancellation.get('acknowledged') is True and cancellation.get('prompt_id') == prompt_id:
                from clients.comfyui_client import canceled_job_absent
                if canceled_job_absent(prompt_id):
                    from engine.coordinator import fresh_gpu
                    fresh_gpu()
                    return 'canceled'
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                h = json.loads(r.read().decode("utf-8"))
            if prompt_id in h:
                st = h[prompt_id].get("status", {})
                s = st.get("status_str")
                if s == "success":
                    raw_outputs = h[prompt_id].get("outputs") or {}
                    images = []
                    for node_id, node_out in raw_outputs.items():
                        for img in (node_out.get("images") or []):
                            fname = img.get("filename", "")
                            sub = img.get("subfolder", "")
                            ftype = img.get("type", "output")
                            url = "http://127.0.0.1:8188/view?filename={}&subfolder={}&type={}".format(
                                fname, sub, ftype)
                            images.append({"filename": fname, "subfolder": sub, "type": ftype, "url": url, "node": node_id})
                    task["result"] = {"outputs": list(raw_outputs.keys()), "images": images}
                    return "done"
                if s == "error":
                    task["error"] = "comfy_error: " + json.dumps(st.get("messages", [])[-1:] if st.get("messages") else {})
                    return "failed"
        except Exception as e:
            log_error("exception_suppressed", error=e, context="queue.py:148")
        time.sleep(3)
    return "uncertain"


def _effective_workflow(task):
    """New tasks use their committed payload; legacy tasks bind once before execution."""
    wf = task.get('effective_workflow')
    if task.get('source')=='ollama':
        wf=_validate_ollama_request(wf)
        if (workload_fingerprint(wf)!=task.get('workflow_sha256') or not task.get('profile_reference')):
            raise ResourceDenied('PROFILE_UNVERIFIED','保存的 Ollama 请求或证据引用不完整')
        return wf
    configuration = task.get('resource_configuration_sha256')
    if configuration is None:
        template = _load_workflow(task['workflow'])
        if not template:
            raise ConfigError('缺少资源配置模板，不能核验旧任务预算')
        configuration = resource_configuration_fingerprint(template)
    if wf is None:
        template = _load_workflow(task['workflow'])
        if not template:
            raise ConfigError('模板读取失败')
        wf = _apply_params(template, task['params'])
        _persist(task, effective_workflow=wf, workflow_sha256=workload_fingerprint(wf),
                 resource_configuration_sha256=configuration)
    if workload_fingerprint(wf) != task.get('workflow_sha256'):
        raise ValueError('已保存的工作流摘要不匹配，拒绝执行')
    if resource_configuration_fingerprint(wf) != configuration and not task.get('profile_reference'):
        raise ResourceDenied('PROFILE_REQUIRED', '资源参数缺少匹配测量 Profile，拒绝复用固定预算')
    return json.loads(json.dumps(wf, allow_nan=False))


def _ollama_generate(request):
    """Independent supervisor persists the RPC receipt even if parent exits."""
    from pathlib import Path
    import sys
    from engine.coordinator import get_coordinator
    active=get_coordinator().snapshot()['active']
    journal=registry.get('operation_journal')
    if (not get_coordinator().current_token() or not active or active.get('service')!='ollama'
            or not active.get('job_id') or not active.get('journal_id') or journal is None):
        raise ResourceDenied('INVALID_LEASE','Ollama 提交必须持有预留')
    from core.command_worker import run_supervised
    args=[sys.executable,str(Path(BASE_DIR)/'core/ollama_worker.py'),str(_store().path.resolve()),
          active['job_id'],workload_fingerprint(request)]
    _,(rc,output)=run_supervised(journal,active['journal_id'],args,315)
    if rc!=0: raise RuntimeError('delegated Ollama completion unavailable')
    return json.loads(output)


def _ollama_completion(request,response):
    import hashlib
    if (not isinstance(response,dict) or response.get('done') is not True
            or response.get('model')!=request['model'] or type(response.get('eval_count')) is not int
            or not 0<response['eval_count']<=request['options']['num_predict']
            or not isinstance(response.get('response'),str)):
        raise ValueError('Ollama 完整生成回执无法核验')
    metrics={key:response.get(key) for key in ('done','done_reason','eval_count',
        'prompt_eval_count','total_duration','load_duration','eval_duration','prompt_eval_duration')}
    return dict(backend_completion=dict(model=response['model'],metrics=metrics),
        result=dict(response=response['response'],response_sha256=hashlib.sha256(response['response'].encode()).hexdigest(),metrics=metrics))


def _confirmed_ollama_completion(task):
    """Only the durable response for this exact intent proves historical success."""
    import hashlib
    try:
        request=task['effective_workflow'];completion=task['backend_completion'];result=task['result']
        metrics=completion['metrics']
        return (task.get('source')=='ollama' and completion['model']==task['model']==request['model']
            and workload_fingerprint(request)==task['workflow_sha256']
            and metrics.get('done') is True and type(metrics.get('eval_count')) is int
            and 0<metrics['eval_count']<=request['options']['num_predict']
            and result['metrics']==metrics and isinstance(result['response'],str)
            and hashlib.sha256(result['response'].encode()).hexdigest()==result['response_sha256'])
    except (KeyError,TypeError,ValueError):
        return False


def _execute_ollama_task(task,lease,request):
    """Write-ahead synchronous dispatch; local ID is not a backend history ID."""
    _persist(task,'submitting',submission_id=str(uuid.uuid4()),backend_correlation_supported=False)
    try:
        lease.transition('running',job_id=task['id'])
        response=_ollama_generate(request)
        # Persist the response before terminal state. A crash in this window must
        # retain unknown ownership until the durable response is inspected.
        _persist(task,'running',**_ollama_completion(request,response))
        _persist(task,'canceled' if task.get('cancel_requested') else 'done',ended=int(time.time()),
            progress='后端完整生成回执已持久化；取消为请求结束后确认，未即时中断')
        lease.transition('completed')
    except BaseException as error:
        lease.uncertain('Ollama 请求或完成保存未知，不重放',job_id=task['id'])
        try:
            _persist(task,'uncertain',error=str(error))
        except Exception as storage_error:
            task.update(status='uncertain',error='未知状态保存失败: '+str(storage_error))
        raise


def _execute_reserved_task(task, lease, spec):
    """Keep one reservation through submission and execution confirmation."""
    _persist(task, 'precheck', coordination={"token": lease.token, "owner": spec.owner})
    wf = _effective_workflow(task)
    if task.get("cancel_requested"):
        _persist(task, 'canceled', ended=int(time.time()))
        lease.transition('completed')
        return
    lease.transition("verifying")
    _, decision = _model_budget(spec)
    if decision.get("decision") != "ok":
        raise ResourceDenied("ADMISSION_CHANGED", "提交前预算发生变化，拒绝提交")
    _persist(task, budget={**decision, 'workflow_sha256': workload_fingerprint(wf),
                          'profile_status': decision.get('profile_status', 'registry_estimate_unverified')},
             started=int(time.time()))
    if task.get('source')=='ollama':
        _execute_ollama_task(task,lease,wf)
        return
    if '_version' in task:
        def submit_durable(workflow, submission_id):
            with _task_lock:
                task.update(_runtime_task(_store().get(task['id'])))
                lease.transition('running', prompt_id=submission_id, job_id=task['id'])
            return _queue_submit_comfy(workflow, submission_id)

        try:
            TaskDispatcher(_store()).dispatch(
                {'id': task['id'], 'status': task['status'], 'version': task['_version']},
                wf, submit_durable)
            with _task_lock:
                task.update(_runtime_task(_store().get(task['id'])))
        except DispatchUncertain as error:
            lease.uncertain(str(error), prompt_id=error.submission_id, job_id=task['id'])
            # A storage failure cannot erase the already committed submitting
            # checkpoint. Retain the lease before attempting any further read.
            task.update(status='uncertain', submission_id=error.submission_id, error=str(error))
            try:
                saved = next(row for row in _store().snapshot() if row['id'] == task['id'])
                task['_version'] = saved['version']
            except Exception as storage_error:
                log_error('task_checkpoint_unavailable', error=storage_error)
            return
        pid = task.get('prompt_id')
        if task['status'] == 'failed':
            lease.transition('failed')
            return
        lease.transition('running', prompt_id=pid, job_id=task['id'])
        _wait_reserved_task(task, lease, pid)
        return
    submission_id = str(uuid.uuid4())
    task["submission_id"] = submission_id
    lease.transition("running", prompt_id=submission_id, job_id=task["id"])
    try:
        pid, err = _queue_submit_comfy(wf, submission_id)
    except Exception as error:
        task["status"] = "uncertain"
        task["error"] = "提交异常，执行状态未知: " + str(error)
        lease.uncertain(task["error"], prompt_id=submission_id)
        return
    if not pid:
        uncertain = not isinstance(err, dict) or err.get("uncertain", True)
        message = err.get("message", "") if isinstance(err, dict) else str(err or "")
        task["error"] = "ComfyUI 提交失败: " + message
        task["status"] = "uncertain" if uncertain else "failed"
        if uncertain:
            lease.uncertain("提交响应丢失，执行状态未知", prompt_id=submission_id)
        return
    task["prompt_id"] = pid
    lease.transition("running", prompt_id=pid)
    task["progress"] = "已提交，资源预留保持至执行结束确认"
    _wait_reserved_task(task, lease, pid)


def _wait_reserved_task(task, lease, pid):
    try:
        rc = _queue_wait(pid, task)
    except Exception as error:
        message = "结束核验异常，资源预留保留: " + str(error)
        lease.uncertain(message, prompt_id=pid)
        task['status'] = 'uncertain'
        _persist(task, 'uncertain', error=message)
        return
    if rc == "uncertain":
        message = "执行超时或状态不可用；资源预留保留，等待核验"
        lease.uncertain(message, prompt_id=pid)
        task['status'] = 'uncertain'
        _persist(task, 'uncertain', error=message)
    else:
        try:
            _persist(task, 'canceled' if task.get('cancel_requested') else ('done' if rc == 'done' else 'failed'),
                     ended=int(time.time()), result=task.get('result'), error=task.get('error', ''))
        except Exception:
            lease.uncertain('结束证据无法落盘，资源预留保留', prompt_id=pid)
            task['status'] = 'uncertain'
            raise
        lease.transition("completed" if rc == "done" else "failed")


def _run_task(task):
    """Wait for ownership and execute under one lifetime reservation."""
    spec = OperationSpec("generate", task.get('source','comfyui'), task["model"], owner="job:" + task["id"])
    try:
        with _task_lock:
            if task['status'] in TaskStore.TERMINAL:
                return
            if task.get('cancel_requested'):
                _persist(task, 'canceled', ended=int(time.time()))
                return
            if task['status'] == 'queued':
                _persist(task, 'precheck')
            # Validate/freeze before assessment can release any resident model.
            wf = _effective_workflow(task)
            spec = replace(spec, workflow=wf, profile_reference=task.get('profile_reference'),
                           ctx=wf['options']['num_ctx'] if spec.service=='ollama' else None)
        while True:
            if task.get("cancel_requested"):
                _persist(task, 'canceled', ended=int(time.time()))
                return
            try:
                with coordinated_operation(spec) as lease:
                    _execute_reserved_task(task, lease, spec)
                return
            except ResourceDenied as error:
                task["coordination"] = error.result()
                if error.code not in ("RESOURCE_BUSY", "SERVICE_BUSY"):
                    raise
                if task['status'] != 'waiting_resource' or task.get('progress') != str(error):
                    _persist(task, 'waiting_resource', progress=str(error), coordination=error.result())
                time.sleep(0.25)
    except Exception as error:
        from engine.coordinator import get_coordinator
        active = get_coordinator().snapshot()['active']
        if (active and active.get('owner') == 'job:' + task['id'] and active.get('phase') == 'uncertain'
                and task['status'] not in TaskStore.TERMINAL and task['status'] != 'uncertain'):
            try:
                _persist(task, 'uncertain', error=str(error), coordination={'token': active['token'], 'owner': active['owner']})
            except Exception as storage_error:
                task.update(status='uncertain', error='未知状态无法保存: ' + str(storage_error))
        if task['status'] == 'uncertain':
            task['error'] = str(error)
        else:
            try:
                _persist(task, 'failed', error=str(error), ended=int(time.time()))
            except Exception as storage_error:
                task['error'] = '任务状态无法保存: ' + str(storage_error)
    finally:
        task["ended"] = int(time.time()) if task["status"] not in ("waiting_resource", "uncertain") else None
        if task["status"] == "done" and task.get("started"):
            update_gen_stats(task["model"], task["ended"] - task["started"])
        log_event("queue_finish", task=task["id"], model=task["model"], status=task["status"],
                  err=task.get("error", "")[-200:])



def _queue_worker():
    """串行 worker：取队首 → 执行 → 下一个；队列空时休眠 2s。"""
    while True:
        with _task_lock:
            if not _task_queue:
                _queue_state["worker_alive"] = False
                return
            tid = _task_queue.popleft()
        task = _tasks.get(tid)
        if task:
            try:
                _run_task(task)
            except Exception as error:
                # Observability failures must not strand queued tasks behind a
                # permanently true worker flag. Execution retains its own lease.
                log_error('queue_worker_exception', error=error, task=tid)


def reconcile_task(job_id: str, token: str, prompt_id: str, status: str) -> bool:
    """Apply trusted terminal evidence only to the matching uncertain task."""
    with _task_lock:
        task = _tasks.get(job_id)
        if not task:
            return False
        if task.get("coordination", {}).get("token") != token:
            return False
        if prompt_id not in (task.get("prompt_id"), task.get("submission_id")):
            return False
        expected = 'canceled' if task.get('cancel_requested') else 'done' if status == 'success' else 'failed'
        if task['status'] in TaskStore.TERMINAL:
            return task['status'] == expected
        if task['status'] != 'uncertain':
            return False
        if '_version' in task:
            saved = next(row for row in _store().snapshot() if row['id'] == task['id'])
            task['_version'] = saved['version']
            if saved['status'] != 'uncertain':
                _persist(task, 'uncertain')
        _persist(task, 'canceled' if task.get('cancel_requested') else
                 'done' if status == 'success' else 'failed',
                 ended=int(time.time()), progress='已核验对应任务的结束记录',
                 error='' if status == 'success' else 'ComfyUI 执行失败（结束记录已核验）')
        return True


def reconcile_ollama_task(active,journal):
    """Consume only the exact worker's durable complete receipt, without RPC."""
    from pathlib import Path
    import sys
    with _task_lock:
        task=_tasks.get(active['job_id'])
        if (not task or task.get('source')!='ollama' or task.get('model')!=active.get('model')
                or task.get('coordination',{}).get('token')!=active['token']
                or task['status'] not in ('uncertain','done','canceled')):
            raise ValueError('Ollama task ownership mismatch')
        expected=[sys.executable,str(Path(BASE_DIR)/'core/ollama_worker.py'),str(_store().path.resolve()),
                  task['id'],task['workflow_sha256']]
        commands=journal.commands(active['journal_id'])
        matches=[row for row in commands if row['intent']==expected]
        if len(matches)!=1: raise ValueError('exact delegated worker receipt unavailable')
        command=matches[0]
        if command['state']!='confirmed' or command['return_code']!=0:
            raise ValueError('delegated worker completion not confirmed')
        result=journal.command_result(command['id'])
        if result is None or result[0]!=0: raise ValueError('durable response unavailable')
        response=json.loads(result[1])
        fields=_ollama_completion(_effective_workflow(task),response)
        if task['status'] in TaskStore.TERMINAL:
            if not _confirmed_ollama_completion(task) or any(task.get(key)!=value for key,value in fields.items()):
                raise ValueError('terminal task receipt mismatch')
            return command['id']
        latest=_store().get(task['id'])
        task.update(_runtime_task(latest))
        _persist(task,'uncertain',**fields)
        if not _confirmed_ollama_completion(task): raise ValueError('response integrity unverified')
        _persist(task,'canceled' if task.get('cancel_requested') else 'done',ended=int(time.time()),
                 progress='独立执行回执核验并恢复；没有重放请求')
        return command['id']


def cancellation_evidence(job_id, token, prompt_id):
    """Only a stored ack bound to this owned task can justify queue absence."""
    with _task_lock:
        task = _tasks.get(job_id)
        if not task or not task.get('cancel_requested') or task.get('coordination', {}).get('token') != token:
            return False
        acknowledgment = task.get('backend_cancel', {})
        return acknowledgment.get('acknowledged') is True and acknowledgment.get('prompt_id') == prompt_id


def queue_snapshot() -> dict:
    """队列观察：全部任务（含历史）+ 当前 worker 状态。"""
    with _task_lock:
        tasks = [dict(t) for t in _tasks.values()]
        queue = list(_task_queue)
    tasks.sort(key=lambda t: t.get("created", 0), reverse=True)
    from engine.coordinator import get_coordinator
    return {"ok": True, "queue": queue, "tasks": tasks, "coordination": get_coordinator().snapshot(),
            "worker_alive": _queue_state["worker_alive"], "client_id": _QUEUE_CLIENT_ID}


def queue_cancel(tid: str) -> dict:
    """取消排队中任务（运行中无法中断 ComfyUI，标记请求取消，完成后置 canceled）。"""
    with _task_lock:
        task = _tasks.get(tid)
        if not task:
            return {"ok": False, "error": "task not found"}
        if '_version' in task:
            saved = _store().get(tid)
            was_uncertain = task['status'] == 'uncertain'
            task.update(_runtime_task(saved))
            if was_uncertain and saved['status'] not in TaskStore.TERMINAL:
                task['status'] = 'uncertain'
        if task["status"] == "queued":
            _persist(task, 'canceled', ended=int(time.time()))
            try:
                _task_queue.remove(tid)
            except ValueError: pass  # 合理忽略：值解析失败，使用默认值
            log_event("queue_cancel", task=tid)
            return {"ok": True, "task": task}
        if task["status"] in ("waiting_resource", "precheck", "freeing", "submitting", "running", "uncertain"):
            _persist(task, cancel_requested=True)
        else:
            return {"ok": False, "error": "已结束的任务无法取消"}
    result = _cancel_backend(task)
    return {'ok': True, 'note': '取消意图已保存；执行结束确认前仍保留资源预留',
            'backend_cancel': result, 'task': dict(task)}


def _cancel_backend(task):
    """Special capability for canceling the owned job, not a new GPU operation."""
    from engine.coordinator import get_coordinator
    if task.get('source')=='ollama':
        # Closing HTTP is not proof that the runner stopped; never issue a global
        # stop or invent an interrupt acknowledgment from /api/ps.
        return {'ok':False,'code':'CANCEL_UNSUPPORTED',
                'error':'取消意图已保存；Ollama 请求结束确认前保留预留，不宣称即时中断'}
    from clients.comfyui_client import cancel_job
    with _task_lock:
        active = get_coordinator().snapshot()['active']
        prompt_id = task.get('prompt_id') or task.get('submission_id')
        if (not task.get('cancel_requested') or not prompt_id or not active or
                active.get('service') != 'comfyui' or
                active.get('job_id') != task['id'] or active.get('prompt_id') != prompt_id or
                active['token'] != task.get('coordination', {}).get('token')):
            return {'ok': False, 'code': 'CANCEL_DEFERRED', 'error': '等待对应任务取得执行身份'}
        if task.get('backend_cancel', {}).get('acknowledged') is True:
            return task['backend_cancel']
    result = cancel_job(prompt_id)
    with _task_lock:
        if task.get('backend_cancel', {}).get('acknowledged') is True:
            return task['backend_cancel']
        if task['status'] not in TaskStore.TERMINAL:
            if '_version' in task:
                saved = _store().get(task['id'])
                task['_version'] = saved['version']
            _persist(task, backend_cancel=result)
    return result
