"""Production queue paths with real storage and controlled external adapters."""
from collections import deque
import sqlite3
from unittest.mock import Mock

import pytest

from core.registry import registry
from core.resource_coordinator import ResourceCoordinator, ResourceDenied, ResourceRequest
from core.task_store import TaskStore
from engine import queue, coordinator

_real_wait = queue._queue_wait


@pytest.fixture
def ollama_runtime(runtime,tmp_path,monkeypatch):
    import hashlib,json
    from pathlib import Path
    from core.ollama_profile import profile_from_evidence
    payload=(Path(__file__).resolve().parents[3]/'docs/evidence/ollama-long-profile-20261008/ollama-qwen9b-long8192-20261008.json').read_bytes()
    raw=json.loads(payload);profile=profile_from_evidence(payload,512)
    directory=tmp_path/'profiles';directory.mkdir()
    (directory/'raw.json').write_bytes(payload)
    (directory/(profile['workflow_sha256']+'.json')).write_text(json.dumps(dict(
        raw_file='raw.json',raw_sha256=hashlib.sha256(payload).hexdigest(),margin_mb=512)))
    monkeypatch.setenv('GMAE_PROFILE_DIR',str(directory))
    monkeypatch.setattr(queue,'REGISTRY',{'ollama':{'models':[{'id':raw['request']['model']}]},
        'comfyui':{'models':[{'id':'m','workflow':'test.json'}]}})
    return runtime,raw['request']


def ollama_response(request):
    return dict(model=request['model'],done=True,done_reason='stop',eval_count=2,
                prompt_eval_count=10,response='test output')


def test_ollama_intent_idempotent_and_conflicts_across_backends(ollama_runtime):
    path,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request,'shared-key')
    retry=queue.queue_enqueue_ollama(request,'shared-key')
    assert first['created'] and not retry['created']
    assert first['task']['id']==retry['task']['id'] and len(queue._task_queue)==1
    assert queue.queue_enqueue('m',{},'shared-key')['code']=='IDEMPOTENCY_CONFLICT'
    assert TaskStore(path).get(first['task']['id'])['intent']['effective_workflow']==request


def test_ollama_submit_checkpoint_precedes_rpc_and_completion_is_saved(ollama_runtime,monkeypatch):
    path,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request)
    task=queue._tasks[first['task']['id']]
    def rpc(body):
        assert TaskStore(path).get(task['id'])['status']=='submitting'
        assert coordinator.get_coordinator().snapshot()['active']['service']=='ollama'
        return ollama_response(body)
    monkeypatch.setattr(queue,'_ollama_generate',rpc)
    queue._run_task(task)
    saved=TaskStore(path).get(task['id'])
    assert saved['status']=='done' and saved['checkpoint']['backend_correlation_supported'] is False
    assert queue._confirmed_ollama_completion(task)
    assert coordinator.get_coordinator().snapshot()['active'] is None


def test_ollama_lost_response_retained_and_never_replayed(ollama_runtime,monkeypatch):
    _,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request)
    rpc=Mock(side_effect=TimeoutError('response lost'))
    monkeypatch.setattr(queue,'_ollama_generate',rpc)
    queue._run_task(queue._tasks[first['task']['id']])
    assert queue._tasks[first['task']['id']]['status']=='uncertain'
    restart()
    active=coordinator.get_coordinator().snapshot()['active']
    assert active['service']=='ollama' and active.get('prompt_id') is None
    assert not queue._task_queue and rpc.call_count==1
    assert coordinator.reconcile_uncertain()['code']=='UNCONFIRMED_EXECUTION'


def test_ollama_cancel_during_rpc_waits_for_complete_response(ollama_runtime,monkeypatch):
    _,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request);task=queue._tasks[first['task']['id']]
    def rpc(body):
        result=queue.queue_cancel(task['id'])
        assert result['backend_cancel']['code']=='CANCEL_UNSUPPORTED'
        assert coordinator.get_coordinator().snapshot()['active'] is not None
        return ollama_response(body)
    monkeypatch.setattr(queue,'_ollama_generate',rpc)
    queue._run_task(task)
    assert task['status']=='canceled' and queue._confirmed_ollama_completion(task)
    assert coordinator.get_coordinator().snapshot()['active'] is None


def test_ollama_queued_cancel_never_submits_after_restart(ollama_runtime,monkeypatch):
    _,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request)
    assert queue.queue_cancel(first['task']['id'])['ok']
    rpc=Mock();monkeypatch.setattr(queue,'_ollama_generate',rpc)
    restart()
    assert not queue._task_queue
    queue._run_task(queue._tasks[first['task']['id']]);rpc.assert_not_called()


def test_saved_ollama_response_recovers_without_backend_replay(ollama_runtime,monkeypatch):
    import hashlib
    path,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request);store=TaskStore(path)
    record=store.get(first['task']['id'])
    for status in ('precheck','submitting'):
        record=store.checkpoint(record['id'],record['version'],status,{'submission_id':'local-only'})
    response=ollama_response(request);metrics={k:v for k,v in response.items() if k not in ('model','response')}
    record=store.checkpoint(record['id'],record['version'],'running',dict(
        backend_completion=dict(model=request['model'],metrics=metrics),
        result=dict(response=response['response'],response_sha256=hashlib.sha256(response['response'].encode()).hexdigest(),metrics=metrics)))
    from core.operation_journal import OperationJournal
    journal=OperationJournal(path)
    journal.begin(dict(operation='generate',owner='job:'+record['id'],service='ollama',model=request['model']))
    registry.set('operation_journal',journal)
    rpc=Mock();monkeypatch.setattr(queue,'_ollama_generate',rpc)
    restart()
    assert store.get(record['id'])['status']=='done'
    assert not queue._task_queue and coordinator.get_coordinator().snapshot()['active'] is None
    assert journal.pending()==[]
    rpc.assert_not_called()


def test_terminal_ollama_receipt_finishes_pending_operation_on_startup(ollama_runtime,monkeypatch):
    from core.operation_journal import OperationJournal
    path,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request);task=queue._tasks[first['task']['id']]
    monkeypatch.setattr(queue,'_ollama_generate',lambda body:ollama_response(body))
    queue._run_task(task)
    journal=OperationJournal(path)
    journal.begin(dict(operation='generate',owner='job:'+task['id'],service='ollama',model=request['model']))
    registry.delete('operation_journal')
    registry.set('resource_coordinator',ResourceCoordinator())
    coordinator.restore_resource_operations()
    assert journal.pending()==[]
    assert coordinator.get_coordinator().snapshot()['active'] is None


def delegated_pending(ollama_runtime):
    from pathlib import Path
    import sys
    from core.operation_journal import OperationJournal
    path,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request);store=TaskStore(path)
    record=store.get(first['task']['id'])
    for status in ('precheck','submitting'):
        record=store.checkpoint(record['id'],record['version'],status,{'submission_id':'local-only'})
    journal=OperationJournal(path)
    operation=journal.begin(dict(operation='generate',owner='job:'+record['id'],service='ollama',model=request['model']))
    args=[sys.executable,str(Path(queue.BASE_DIR)/'core/ollama_worker.py'),str(path.resolve()),record['id'],record['intent']['workflow_sha256']]
    command=journal.command_begin(operation,args,supervised=True)
    assert journal.command_claim(command)==args
    registry.set('operation_journal',journal)
    return store,record,request,journal,command


def test_exact_delegated_receipt_recovers_without_rpc(ollama_runtime,monkeypatch):
    import json
    store,record,request,journal,command=delegated_pending(ollama_runtime)
    journal.command_finish(command,0,json.dumps(ollama_response(request)))
    rpc=Mock();monkeypatch.setattr(queue,'_ollama_generate',rpc)
    monkeypatch.setattr(coordinator,'fresh_gpu',lambda:dict(total_mb=16380,used_mb=1,free_mb=16379))
    restart()
    assert coordinator.reconcile_uncertain()['resolved']
    assert store.get(record['id'])['status']=='done' and journal.pending()==[]
    assert coordinator.get_coordinator().snapshot()['active'] is None
    rpc.assert_not_called()


@pytest.mark.parametrize('fault',['missing','wrong_model','failed_command'])
def test_bad_delegated_receipt_keeps_unknown_hold(ollama_runtime,monkeypatch,fault):
    import json
    store,record,request,journal,command=delegated_pending(ollama_runtime)
    if fault!='missing':
        response=ollama_response(request)
        if fault=='wrong_model': response['model']='other'
        journal.command_finish(command,1 if fault=='failed_command' else 0,json.dumps(response))
    monkeypatch.setattr(coordinator,'fresh_gpu',lambda:dict(total_mb=16380,used_mb=1,free_mb=16379))
    restart()
    assert coordinator.reconcile_uncertain()['code']=='UNCONFIRMED_EXECUTION'
    assert store.get(record['id'])['status']=='uncertain'
    assert coordinator.get_coordinator().snapshot()['active'] is not None


def test_delegated_worker_reads_only_exact_saved_intent(ollama_runtime):
    import json
    from core.ollama_worker import execute
    store,record,request,journal,command=delegated_pending(ollama_runtime)
    fetch=Mock(return_value=ollama_response(request))
    result=execute(store.path,record['id'],record['intent']['workflow_sha256'],fetch)
    assert json.loads(result)['done'] and fetch.call_args.args[0]==request
    with pytest.raises(ValueError): execute(store.path,record['id'],'0'*64,fetch)
    assert fetch.call_count==1


def test_ollama_completion_storage_failure_retains_ownership(ollama_runtime,monkeypatch):
    path,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request);task=queue._tasks[first['task']['id']]
    monkeypatch.setattr(queue,'_ollama_generate',lambda body:ollama_response(body))
    original=queue._persist
    def persist(task,status=None,**fields):
        if status=='running': raise OSError('completion disk failure')
        return original(task,status,**fields)
    monkeypatch.setattr(queue,'_persist',persist)
    queue._run_task(task)
    assert TaskStore(path).get(task['id'])['status']=='uncertain'
    assert coordinator.get_coordinator().snapshot()['active']['phase']=='uncertain'


def test_ollama_unmeasured_prompt_and_unsafe_context_reject_before_acceptance(ollama_runtime):
    from copy import deepcopy
    path,request=ollama_runtime
    changed=deepcopy(request);changed['prompt']='different request'
    assert queue.queue_enqueue_ollama(changed)['code']=='PROFILE_REQUIRED'
    changed=deepcopy(request);changed['options']['num_ctx']=16384
    assert queue.queue_enqueue_ollama(changed)['code']=='INVALID_INTENT'
    assert not TaskStore(path).snapshot()


def test_corrupt_saved_ollama_response_is_not_terminal_proof(ollama_runtime):
    import hashlib
    path,request=ollama_runtime
    first=queue.queue_enqueue_ollama(request);store=TaskStore(path)
    record=store.get(first['task']['id'])
    for status in ('precheck','submitting'):
        record=store.checkpoint(record['id'],record['version'],status,{'submission_id':'local-only'})
    response=ollama_response(request);metrics={k:v for k,v in response.items() if k not in ('model','response')}
    record=store.checkpoint(record['id'],record['version'],'running',dict(
        backend_completion=dict(model=request['model'],metrics=metrics),
        result=dict(response='changed',response_sha256=hashlib.sha256(response['response'].encode()).hexdigest(),metrics=metrics)))
    restart()
    assert store.get(record['id'])['status']=='uncertain'
    assert coordinator.get_coordinator().snapshot()['active']['service']=='ollama'


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    path = tmp_path / 'tasks.sqlite3'
    registry.delete('task_store')
    previous_journal = registry.get('operation_journal')
    monkeypatch.setenv('GMAE_TASK_DB', str(path))
    state = {'tasks': {}, 'task_queue': deque(), 'worker_alive': False}
    monkeypatch.setattr(queue, '_queue_state', state)
    monkeypatch.setattr(queue, '_tasks', state['tasks'])
    monkeypatch.setattr(queue, '_task_queue', state['task_queue'])
    monkeypatch.setattr(queue, '_start_worker', lambda: None)
    monkeypatch.setattr(queue, 'REGISTRY', {'comfyui': {'models': [{'id': 'm', 'workflow': 'test.json'}]}})
    monkeypatch.setattr(queue, '_load_workflow', lambda name: {'1': {'inputs': {'text': 'test', 'seed': 1}}})
    monkeypatch.setattr(coordinator, 'assess', lambda *args: None)
    monkeypatch.setattr(queue, '_model_budget', lambda spec: ({}, {'decision': 'ok'}))
    monkeypatch.setattr(queue, 'update_gen_stats', lambda *args: None)
    monkeypatch.setattr(queue, '_queue_wait', lambda *args: 'done')
    monkeypatch.setattr('clients.comfyui_client.cancel_job', lambda prompt_id: {
        'ok': False, 'code': 'CANCEL_UNSUPPORTED'})
    yield path
    registry.delete('task_store')
    if previous_journal is None:
        registry.delete('operation_journal')
    else:
        registry.set('operation_journal', previous_journal)


def restart():
    queue._tasks.clear()
    queue._task_queue.clear()
    queue._queue_state['restored'] = False
    registry.delete('task_store')
    registry.set('resource_coordinator', ResourceCoordinator())
    queue.queue_restore()


def test_enqueue_retry_and_cancel_survive_restart(runtime):
    first = queue.queue_enqueue('m', {'seed': 1}, 'request')
    retry = queue.queue_enqueue('m', {'seed': 1}, 'request')
    assert first['created'] and not retry['created']
    assert first['task']['id'] == retry['task']['id']
    assert len(queue._task_queue) == 1
    conflict = queue.queue_enqueue('m', {'seed': 2}, 'request')
    assert conflict['code'] == 'IDEMPOTENCY_CONFLICT'
    assert queue.queue_cancel(first['task']['id'])['ok']
    restart()
    assert not queue._task_queue
    assert queue._tasks[first['task']['id']]['status'] == 'canceled'


def test_saved_payload_survives_template_change_and_restart(runtime, monkeypatch):
    first = queue.queue_enqueue('m', {'prompt': 'original'}, 'immutable')
    restart()
    monkeypatch.setattr(queue, '_load_workflow', lambda name: {'1': {'inputs': {'text': 'changed'}}})
    submitted = []
    monkeypatch.setattr(queue, '_queue_submit_comfy', lambda wf, sid: (submitted.append(wf) or 'pid', None))
    current = queue._tasks[first['task']['id']]
    queue._run_task(current)
    assert current['status'] == 'done'
    assert submitted[0]['1']['inputs']['text'] == 'original'
    assert current['budget']['workflow_sha256'] == first['task']['workflow_sha256']


def test_corrupted_payload_never_submits(runtime, monkeypatch):
    first = queue.queue_enqueue('m', {})
    task = queue._tasks[first['task']['id']]
    task['effective_workflow']['1']['inputs']['text'] = 'tampered'
    submit = Mock()
    monkeypatch.setattr(queue, '_queue_submit_comfy', submit)
    queue._run_task(task)
    assert task['status'] == 'failed'
    submit.assert_not_called()


def test_unbound_parameter_rejected_before_durable_accept(runtime):
    assert queue.queue_enqueue('m', {'steps': 5})['code'] == 'INVALID_INTENT'
    assert not TaskStore(runtime).snapshot()


def test_changed_resource_controls_cannot_reuse_fixed_budget(runtime, monkeypatch):
    monkeypatch.setattr(queue, '_load_workflow', lambda name: {'1': {'inputs': {'width': 1024}}})
    result = queue.queue_enqueue('m', {'width': 2048})
    assert result['code'] == 'PROFILE_REQUIRED'
    assert not TaskStore(runtime).snapshot()


def test_preflight_release_unknown_is_durable_and_not_failed(runtime, monkeypatch):
    from core.operation_journal import OperationJournal
    journal = OperationJournal(runtime)
    registry.set('operation_journal', journal)
    accepted = queue.queue_enqueue('m', {})
    task = queue._tasks[accepted['task']['id']]
    def incomplete_release(spec, lease):
        lease.transition('releasing')
        raise ResourceDenied('RELEASE_UNVERIFIED', 'physical memory still pending')
    monkeypatch.setattr(coordinator, 'assess', incomplete_release)
    submit = Mock()
    monkeypatch.setattr(queue, '_queue_submit_comfy', submit)
    queue._run_task(task)
    assert task['status'] == 'uncertain'
    assert TaskStore(runtime).get(task['id'])['status'] == 'uncertain'
    assert coordinator.get_coordinator().snapshot()['active']['phase'] == 'uncertain'
    submit.assert_not_called()


def test_real_queue_dispatch_commits_before_rpc_and_terminal_before_release(runtime, monkeypatch):
    accepted = queue.queue_enqueue('m', {}, 'key')
    current = queue._tasks[accepted['task']['id']]

    def submit(workflow, sid):
        row = TaskStore(runtime).snapshot()[0]
        assert row['status'] == 'submitting'
        assert row['checkpoint']['submission_id'] == sid
        assert coordinator.get_coordinator().current_token()
        return 'real-backend-id', None

    monkeypatch.setattr(queue, '_queue_submit_comfy', submit)
    queue._run_task(current)
    assert current['status'] == 'done'
    assert TaskStore(runtime).snapshot()[0]['status'] == 'done'
    assert coordinator.get_coordinator().snapshot()['active'] is None
    restart()
    assert not queue._task_queue
    assert queue._tasks[current['id']]['status'] == 'done'


def test_lost_response_restarts_as_gpu_hold_without_replay(runtime, monkeypatch):
    accepted = queue.queue_enqueue('m', {})
    current = queue._tasks[accepted['task']['id']]
    submit = Mock(return_value=(None, {'uncertain': True}))
    monkeypatch.setattr(queue, '_queue_submit_comfy', submit)
    queue._run_task(current)
    assert current['status'] == 'uncertain'
    assert queue.queue_cancel(current['id'])['ok']
    restart()
    restored = queue._tasks[current['id']]
    assert restored['status'] == 'uncertain' and restored['cancel_requested']
    assert not queue._task_queue
    active = coordinator.get_coordinator().snapshot()['active']
    assert active['prompt_id'] == restored['submission_id']
    assert active['token'] == restored['coordination']['token']
    with pytest.raises(ResourceDenied, match='GPU'):
        with coordinator.get_coordinator().operation(ResourceRequest('release', 'new-owner')):
            pytest.fail('unknown execution must block all mutations')
    submit.assert_called_once()


def test_terminal_storage_failure_keeps_hold_until_evidence_is_persisted(runtime, monkeypatch):
    accepted = queue.queue_enqueue('m', {})
    current = queue._tasks[accepted['task']['id']]
    monkeypatch.setattr(queue, '_queue_submit_comfy', lambda *args: ('backend-id', None))
    with sqlite3.connect(runtime) as connection:
        connection.execute("CREATE TRIGGER fail_terminal BEFORE UPDATE ON tasks "
                           "WHEN NEW.state IN ('done','failed','canceled') "
                           "BEGIN SELECT RAISE(ABORT, 'storage unavailable'); END")
    queue._run_task(current)
    assert current['status'] == 'uncertain'
    assert coordinator.get_coordinator().snapshot()['active']['phase'] == 'uncertain'
    monkeypatch.setattr('clients.comfyui_client._get', lambda path: (
        True, {'backend-id': {'status': {'status_str': 'success'}}}, ''))
    monkeypatch.setattr(coordinator, 'fresh_gpu', lambda: {})
    assert coordinator.reconcile_uncertain()['code'] == 'TASK_STORAGE_UNAVAILABLE'
    assert coordinator.get_coordinator().snapshot()['active'] is not None
    with sqlite3.connect(runtime) as connection:
        connection.execute('DROP TRIGGER fail_terminal')
    assert coordinator.reconcile_uncertain()['resolved']
    assert TaskStore(runtime).snapshot()[0]['status'] == 'done'
    assert coordinator.get_coordinator().snapshot()['active'] is None


def test_multiple_recovered_jobs_have_no_release_gap(runtime, monkeypatch):
    store = queue._store()
    ids = []
    for prompt in ('first', 'second'):
        row, _ = store.accept({'model': 'm', 'workflow': 'test.json', 'params': {}})
        row = store.checkpoint(row['id'], row['version'], 'precheck')
        row = store.checkpoint(row['id'], row['version'], 'submitting', {'submission_id': prompt})
        ids.append(row['id'])
    restart()
    monkeypatch.setattr('clients.comfyui_client._get', lambda path: (
        True, {path.split('/')[-1]: {'status': {'status_str': 'success'}}}, ''))
    monkeypatch.setattr(coordinator, 'fresh_gpu', lambda: {})
    assert len(coordinator.get_coordinator().snapshot()['recovery_pending']) == 1
    assert coordinator.reconcile_uncertain()['resolved']
    assert coordinator.get_coordinator().snapshot()['active']['job_id'] == ids[1]
    with pytest.raises(ResourceDenied):
        with coordinator.get_coordinator().operation(ResourceRequest('release', 'new')):
            pytest.fail('second unresolved task must retain ownership')
    assert coordinator.reconcile_uncertain()['resolved']
    assert coordinator.get_coordinator().snapshot()['active'] is None


def test_corrupt_database_does_not_accept_or_dispatch(runtime, monkeypatch):
    runtime.write_bytes(b'corrupt SQLite')
    submit = Mock()
    monkeypatch.setattr(queue, '_queue_submit_comfy', submit)
    result = queue.queue_enqueue('m', {})
    assert result['code'] == 'TASK_STORAGE_UNAVAILABLE'
    assert not queue._task_queue
    submit.assert_not_called()


def test_cancel_during_rpc_is_not_lost_and_does_not_release_early(runtime, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    entered, finish = threading.Event(), threading.Event()
    accepted = queue.queue_enqueue('m', {})
    current = queue._tasks[accepted['task']['id']]

    def submit(workflow, sid):
        entered.set()
        assert finish.wait(5)
        return 'backend-id', None

    monkeypatch.setattr(queue, '_queue_submit_comfy', submit)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(queue._run_task, current)
        assert entered.wait(5)
        try:
            assert queue.queue_cancel(current['id'])['ok']
            row = TaskStore(runtime).get(current['id'])
            assert row['checkpoint']['cancel_requested']
            assert coordinator.get_coordinator().snapshot()['active'] is not None
        finally:
            finish.set()
        future.result(timeout=5)
    assert TaskStore(runtime).get(current['id'])['status'] == 'canceled'
    assert coordinator.get_coordinator().snapshot()['active'] is None


def test_targeted_cancel_waits_for_absence_then_persists_before_release(runtime, monkeypatch):
    from io import BytesIO
    accepted = queue.queue_enqueue('m', {})
    current = queue._tasks[accepted['task']['id']]
    sent = []
    state = {'absent': False}

    def cancel(prompt_id):
        sent.append(prompt_id)
        return {'ok': True, 'prompt_id': prompt_id, 'acknowledged': True}

    def submit(workflow, sid):
        assert queue.queue_cancel(current['id'])['ok']
        assert coordinator.get_coordinator().snapshot()['active'] is not None
        return sid, None

    def sleep(seconds):
        assert TaskStore(runtime).get(current['id'])['status'] == 'running'
        assert coordinator.get_coordinator().snapshot()['active'] is not None
        state['absent'] = True

    monkeypatch.setattr('clients.comfyui_client.cancel_job', cancel)
    monkeypatch.setattr('clients.comfyui_client.canceled_job_absent', lambda pid: state['absent'])
    monkeypatch.setattr(coordinator, 'fresh_gpu', lambda: {})
    monkeypatch.setattr(queue, '_queue_submit_comfy', submit)
    monkeypatch.setattr(queue, '_queue_wait', _real_wait)
    monkeypatch.setattr(queue.urllib.request, 'urlopen', lambda *args, **kwargs: BytesIO(b'{}'))
    monkeypatch.setattr(queue.time, 'sleep', sleep)
    queue._run_task(current)
    assert sent == [current['prompt_id']]
    assert TaskStore(runtime).get(current['id'])['status'] == 'canceled'
    assert coordinator.get_coordinator().snapshot()['active'] is None


def test_restored_cancel_ack_requires_fresh_absence_before_resolve(runtime, monkeypatch):
    accepted = queue.queue_enqueue('m', {})
    row = queue._store().get(accepted['task']['id'])
    row = queue._store().checkpoint(row['id'], row['version'], 'precheck')
    row = queue._store().checkpoint(row['id'], row['version'], 'submitting', {'submission_id': 'target'})
    queue._store().checkpoint(row['id'], row['version'], 'uncertain', {
        'cancel_requested': True, 'backend_cancel': {'prompt_id': 'target', 'acknowledged': True}})
    restart()
    monkeypatch.setattr('clients.comfyui_client._get', lambda path: (True, {}, ''))
    monkeypatch.setattr('clients.comfyui_client.canceled_job_absent', lambda pid: False)
    monkeypatch.setattr(coordinator, 'fresh_gpu', lambda: {})
    assert coordinator.reconcile_uncertain()['code'] == 'UNCONFIRMED_EXECUTION'
    assert coordinator.get_coordinator().snapshot()['active'] is not None
    monkeypatch.setattr('clients.comfyui_client.canceled_job_absent', lambda pid: True)
    assert coordinator.reconcile_uncertain()['resolved']
    assert TaskStore(runtime).get(row['id'])['status'] == 'canceled'


def test_cancel_cannot_address_another_owners_job(runtime, monkeypatch):
    accepted = queue.queue_enqueue('m', {})
    current = queue._tasks[accepted['task']['id']]
    current.update(cancel_requested=True, prompt_id='target', coordination={'token': 'other-token'})
    coordinator.get_coordinator().restore_uncertain(
        ResourceRequest('generate', 'different-owner', 'comfyui'),
        {'job_id': 'other-job', 'prompt_id': 'target'})
    cancel = Mock()
    monkeypatch.setattr('clients.comfyui_client.cancel_job', cancel)
    assert queue._cancel_backend(current)['code'] == 'CANCEL_DEFERRED'
    cancel.assert_not_called()


def test_task_and_operation_journal_share_one_restored_hold(runtime, monkeypatch):
    coordinator.restore_resource_operations()
    journal = registry.get('operation_journal')
    accepted = queue.queue_enqueue('m', {})
    current = queue._tasks[accepted['task']['id']]
    monkeypatch.setattr(queue, '_queue_submit_comfy', lambda *args: (None, {'uncertain': True}))
    queue._run_task(current)
    assert len(journal.pending()) == 1
    registry.delete('operation_journal')
    registry.set('resource_coordinator', ResourceCoordinator())
    coordinator.restore_resource_operations()
    # The queue supplies the stronger durable submission identity.
    assert coordinator.get_coordinator().snapshot()['active'] is None
    queue._tasks.clear()
    queue._task_queue.clear()
    queue._queue_state['restored'] = False
    registry.delete('task_store')
    queue.queue_restore()
    active = coordinator.get_coordinator().snapshot()['active']
    assert active['journal_id'] == journal.pending()[0]['id']
    assert not coordinator.get_coordinator().snapshot()['recovery_pending']
    sid = current['submission_id']
    monkeypatch.setattr('clients.comfyui_client._get', lambda path: (
        True, {sid: {'status': {'status_str': 'success'}}}, ''))
    monkeypatch.setattr(coordinator, 'fresh_gpu', lambda: {})
    assert coordinator.reconcile_uncertain()['resolved']
    assert not journal.pending()
    assert coordinator.get_coordinator().snapshot()['active'] is None
