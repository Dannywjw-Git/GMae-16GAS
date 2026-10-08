"""Real OS processes test ownership; no Docker/GPU work is performed."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
from core.process_ownership import ProcessOwnership


SCRIPT = '''
import sys
from core.process_ownership import ProcessOwnership
try:
    owner = ProcessOwnership(sys.argv[1], sys.argv[2]).acquire()
except Exception:
    print('blocked', flush=True)
    raise SystemExit(2)
print('owned', flush=True)
sys.stdin.readline()
'''


def launch(db, lock):
    return subprocess.Popen([sys.executable, '-c', SCRIPT, str(db), str(lock)],
        cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_two_processes_only_one_owner_and_crash_releases_os_lock(tmp_path):
    db, lock = tmp_path / 'tasks.sqlite3', tmp_path / 'gpu0.lock'
    children = [launch(db, lock), launch(db, lock)]
    try:
        outcomes = [child.stdout.readline().strip() for child in children]
        assert sorted(outcomes) == ['blocked', 'owned']
        winner = children[outcomes.index('owned')]
        winner.kill()
        winner.wait(timeout=10)
        with pytest.raises(RuntimeError, match='journal differs'):
            ProcessOwnership(tmp_path / 'different.sqlite3', lock).acquire()
        recovered = ProcessOwnership(db, lock).acquire()
        recovered.close()
        again = ProcessOwnership(db, lock).acquire()
        again.close()
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)


def test_corrupt_identity_fails_closed(tmp_path):
    lock = tmp_path / 'gpu0.lock'
    lock.write_bytes(b'0invalid-json')
    with pytest.raises(ValueError):
        ProcessOwnership(tmp_path / 'db', lock).acquire()


def test_crash_lock_recovery_restores_durable_hold(tmp_path, monkeypatch):
    from core.operation_journal import OperationJournal
    from core.registry import registry
    from engine import coordinator
    db, lock = tmp_path / 'db.sqlite3', tmp_path / 'gpu0.lock'
    journal = OperationJournal(db)
    journal.begin(dict(operation='release', owner='crashed-owner', service='comfyui',
                       model=None, peak_mb=0, command_only=True))
    child = launch(db, lock)
    try:
        assert child.stdout.readline().strip() == 'owned'
        child.kill()
        child.communicate(timeout=10)
        recovered = ProcessOwnership(db, lock).acquire()
        previous = registry.get('operation_journal')
        registry.delete('operation_journal')
        monkeypatch.setenv('GMAE_TASK_DB', str(db))
        try:
            coordinator.restore_resource_operations()
            assert coordinator.get_coordinator().snapshot()['active']['phase'] == 'uncertain'
            assert coordinator.reconcile_uncertain()['code'] == 'UNCONFIRMED_EXECUTION'
        finally:
            recovered.close()
            registry.delete('operation_journal')
            if previous is not None:
                registry.set('operation_journal', previous)
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)
