"""Exercise real SQLite and external-call ordering, including crash windows."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest

from core.task_dispatch import DispatchUncertain, TaskDispatcher
from core.task_store import TaskConflict, TaskStore


def prechecked(store):
    task, _ = store.accept({'model': 'm', 'workflow': {'node': 'value'}})
    return store.checkpoint(task['id'], task['version'], 'precheck')


def test_intent_is_visible_to_independent_connection_before_backend_call(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    store = TaskStore(path)
    task = prechecked(store)

    def submit(workflow, submission_id):
        persisted = TaskStore(path).snapshot()[0]
        assert persisted['status'] == 'submitting'
        assert persisted['checkpoint']['submission_id'] == submission_id
        return 'backend-id', None

    result = TaskDispatcher(store).dispatch(task, {}, submit)
    assert result['status'] == 'running'
    assert result['checkpoint']['prompt_id'] == 'backend-id'


def test_concurrent_dispatchers_send_only_once(tmp_path):
    store = TaskStore(tmp_path / 'tasks.sqlite3')
    task = prechecked(store)
    barrier = threading.Barrier(2)
    calls = []

    def attempt():
        barrier.wait(timeout=5)
        try:
            return TaskDispatcher(store).dispatch(task, {}, lambda wf, sid: (calls.append(sid) or 'pid', None))
        except TaskConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert len(calls) == 1
    assert sum(result is not None for result in results) == 1


def test_failed_intent_write_prevents_backend_call(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    store = TaskStore(path)
    task = prechecked(store)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TRIGGER fail_update BEFORE UPDATE ON tasks "
                           "BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
    calls = []
    with pytest.raises(sqlite3.IntegrityError):
        TaskDispatcher(store).dispatch(task, {}, lambda wf, sid: calls.append(sid))
    assert not calls
    assert store.snapshot()[0] == task


def test_accepted_backend_with_failed_response_write_stays_reconcile_only(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    store = TaskStore(path)
    task = prechecked(store)
    accepted = []

    def submit(workflow, submission_id):
        accepted.append(submission_id)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TRIGGER fail_running BEFORE UPDATE ON tasks "
                               "WHEN NEW.state='running' BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
        return 'backend-id', None

    with pytest.raises(DispatchUncertain) as error:
        TaskDispatcher(store).dispatch(task, {}, submit)
    plan = TaskStore(path).recovery_plan()
    assert not plan['resume']
    assert plan['reconcile'][0]['status'] == 'submitting'
    assert error.value.submission_id == accepted[0]
    with pytest.raises(TaskConflict):
        TaskDispatcher(store).dispatch(plan['reconcile'][0], {}, submit)
    assert len(accepted) == 1


@pytest.mark.parametrize('response', [(None, None), (123, None), (None, {'uncertain': True})])
def test_ambiguous_response_cannot_release_as_failed(tmp_path, response):
    store = TaskStore(tmp_path / 'tasks.sqlite3')
    task = prechecked(store)
    with pytest.raises(DispatchUncertain):
        TaskDispatcher(store).dispatch(task, {}, lambda wf, sid: response)
    assert store.recovery_plan()['reconcile'][0]['status'] == 'uncertain'


def test_known_rejection_is_terminal(tmp_path):
    store = TaskStore(tmp_path / 'tasks.sqlite3')
    result = TaskDispatcher(store).dispatch(
        prechecked(store), {}, lambda wf, sid: (None, {'uncertain': False, 'message': 'invalid workflow'}))
    assert result['status'] == 'failed'
    assert store.recovery_plan()['terminal'] == [result]


def test_process_dies_after_backend_acceptance_keeps_correlation_id(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    evidence = tmp_path / 'backend-accepted.txt'
    source = str(Path(__file__).resolve().parents[1])
    code = '''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from core.task_store import TaskStore
from core.task_dispatch import TaskDispatcher
store=TaskStore(sys.argv[2])
task,_=store.accept({'model':'m'})
task=store.checkpoint(task['id'],task['version'],'precheck')
def submit(wf,sid):
    Path(sys.argv[3]).write_text(sid,encoding='utf-8')
    os._exit(0)
TaskDispatcher(store).dispatch(task,{},submit)
'''
    subprocess.run([sys.executable, '-c', code, source, str(path), str(evidence)], check=True, timeout=10)
    plan = TaskStore(path).recovery_plan()
    assert not plan['resume']
    assert plan['reconcile'][0]['checkpoint']['submission_id'] == evidence.read_text(encoding='utf-8')


def test_transport_exception_is_persisted_as_unknown(tmp_path):
    store = TaskStore(tmp_path / 'tasks.sqlite3')

    def submit(workflow, submission_id):
        raise TimeoutError('response lost')

    with pytest.raises(DispatchUncertain):
        TaskDispatcher(store).dispatch(prechecked(store), {}, submit)
    assert store.recovery_plan()['reconcile'][0]['status'] == 'uncertain'
