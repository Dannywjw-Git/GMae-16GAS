"""Crash, retry, contention and rollback evidence for durable task storage."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest
from core.task_store import TaskStore, TaskConflict


def intent():
    return {'model': 'registered-model', 'params': {'prompt': '持久化任务', 'seed': 1}}


def test_same_retry_key_accepts_one_task_under_real_thread_contention(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    store = TaskStore(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.accept(intent(), 'request-key'), range(16)))
    assert len({task['id'] for task, created in results}) == 1
    assert sum(created for task, created in results) == 1
    assert len(TaskStore(path).snapshot()) == 1


def test_retry_with_changed_parameters_cannot_reuse_key(tmp_path):
    store = TaskStore(tmp_path / 'tasks.sqlite3')
    original, _ = store.accept(intent(), 'key')
    with pytest.raises(TaskConflict, match='different intent'):
        store.accept({'model': 'different'}, 'key')
    assert store.snapshot() == [original]


def test_stale_writers_cannot_overwrite_cancel_checkpoint(tmp_path):
    store = TaskStore(tmp_path / 'tasks.sqlite3')
    task, _ = store.accept(intent())
    canceled = store.checkpoint(task['id'], 0, 'canceled', {'cancel_requested': True})
    with pytest.raises(TaskConflict, match='version changed'):
        store.checkpoint(task['id'], 0, 'precheck')
    assert store.snapshot() == [canceled]


def test_crash_after_committed_acceptance_survives_process_exit(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    source = str(Path(__file__).resolve().parents[1])
    code = ('import os,sys; sys.path.insert(0,sys.argv[1]); '
            'from core.task_store import TaskStore; '
            'TaskStore(sys.argv[2]).accept({"model":"m"},"durable-key"); os._exit(0)')
    subprocess.run([sys.executable, '-c', code, source, str(path)], check=True, timeout=10)
    plan = TaskStore(path).recovery_plan()
    assert len(plan['resume']) == 1
    assert plan['resume'][0]['status'] == 'queued'


def test_submission_checkpoint_requires_reconciliation_after_reopen(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    store = TaskStore(path)
    task, _ = store.accept(intent())
    task = store.checkpoint(task['id'], task['version'], 'precheck')
    with pytest.raises(ValueError, match='correlation ID'):
        store.checkpoint(task['id'], task['version'], 'submitting')
    task = store.checkpoint(task['id'], task['version'], 'submitting', {'submission_id': 'full-client-id'})
    plan = TaskStore(path).recovery_plan()
    assert not plan['resume']
    assert plan['reconcile'] == [task]
    with pytest.raises(TaskConflict, match='identity'):
        store.checkpoint(task['id'], task['version'], 'running', {'submission_id': 'replacement'})


def test_terminal_tasks_cannot_be_replayed(tmp_path):
    store = TaskStore(tmp_path / 'tasks.sqlite3')
    task, _ = store.accept(intent(), 'key')
    task = store.checkpoint(task['id'], task['version'], 'failed', {'error': 'bad workflow'})
    retried, created = store.accept(intent(), 'key')
    assert not created
    assert retried == task
    with pytest.raises(TaskConflict, match='lifecycle'):
        store.checkpoint(task['id'], task['version'], 'queued')


def test_event_failure_rolls_back_task_acceptance(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    store = TaskStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TRIGGER fail_event BEFORE INSERT ON task_events "
                           "BEGIN SELECT RAISE(ABORT, 'event storage failed'); END")
    with pytest.raises(sqlite3.IntegrityError, match='event storage failed'):
        store.accept(intent(), 'key')
    assert not store.snapshot()


def test_snapshot_mutation_does_not_change_stored_intent(tmp_path):
    store = TaskStore(tmp_path / 'tasks.sqlite3')
    task, _ = store.accept(intent())
    task['intent']['params']['seed'] = 999
    assert store.snapshot()[0]['intent']['params']['seed'] == 1


def test_nonfinite_parameters_rejected_before_task_is_written(tmp_path):
    store = TaskStore(tmp_path / 'tasks.sqlite3')
    with pytest.raises(ValueError):
        store.accept({'params': {'cfg': float('nan')}})
    assert not store.snapshot()
