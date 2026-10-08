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
    monkeypatch.setattr(queue, '_load_workflow', lambda name: {'1': {'inputs': {'text': 'test'}}})
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
