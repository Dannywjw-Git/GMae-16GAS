"""Real operation paths and SQLite failures; no service mutations."""
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import Mock

import pytest

from core.operation_journal import OperationJournal
from core.registry import registry
from core.resource_coordinator import ResourceCoordinator, ResourceDenied, ResourceRequest
from engine import coordinator


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / 'operations.sqlite3'
    monkeypatch.setenv('GMAE_TASK_DB', str(path))
    previous = registry.get('operation_journal')
    registry.delete('operation_journal')
    coordinator.restore_resource_operations()
    monkeypatch.setattr(coordinator, 'assess', lambda *args: None)
    yield registry.get('operation_journal')
    if previous is None:
        registry.delete('operation_journal')
    else:
        registry.set('operation_journal', previous)


def test_mutation_intent_committed_before_adapter_and_confirmed_before_release(journal):
    @coordinator.coordinated(lambda args: coordinator.OperationSpec('release'))
    def adapter():
        records = OperationJournal(journal.store.path).pending()
        assert len(records) == 1
        assert records[0]['intent']['operation'] == 'release'
        return {'ok': True}

    assert adapter()['ok']
    assert not journal.pending()
    assert coordinator.get_coordinator().snapshot()['active'] is None


def test_failed_intent_write_never_calls_adapter(journal):
    with sqlite3.connect(journal.store.path) as connection:
        connection.execute("CREATE TRIGGER fail_begin BEFORE INSERT ON resource_operations "
                           "BEGIN SELECT RAISE(ABORT, 'storage failed'); END")
    called = Mock()

    @coordinator.coordinated(lambda args: coordinator.OperationSpec('release'))
    def adapter():
        called()
        return {'ok': True}

    with pytest.raises(sqlite3.IntegrityError):
        adapter()
    called.assert_not_called()
    assert coordinator.get_coordinator().snapshot()['active'] is None


def test_failed_completion_write_keeps_live_and_restart_hold(journal):
    with sqlite3.connect(journal.store.path) as connection:
        connection.execute("CREATE TRIGGER fail_finish BEFORE UPDATE ON resource_operations "
                           "BEGIN SELECT RAISE(ABORT, 'storage failed'); END")

    @coordinator.coordinated(lambda args: coordinator.OperationSpec('release'))
    def adapter():
        return {'ok': True}

    with pytest.raises(sqlite3.IntegrityError):
        adapter()
    assert coordinator.get_coordinator().snapshot()['active']['phase'] == 'uncertain'
    registry.delete('operation_journal')
    registry.set('resource_coordinator', ResourceCoordinator())
    coordinator.restore_resource_operations()
    assert coordinator.get_coordinator().snapshot()['active']['journal_id'] == journal.pending()[0]['id']
    with pytest.raises(ResourceDenied):
        with coordinator.get_coordinator().operation(ResourceRequest('start', 'next')):
            pytest.fail('recovered manual operation must block new GPU work')


def test_preflight_denial_without_mutations_does_not_leave_journal(journal, monkeypatch):
    def deny(*args):
        raise ResourceDenied('BUDGET_REJECTED', 'no capacity')

    monkeypatch.setattr(coordinator, 'assess', deny)
    with pytest.raises(ResourceDenied):
        with coordinator.coordinated_operation(coordinator.OperationSpec('load')):
            pytest.fail('must reject')
    assert not journal.pending()
    assert coordinator.get_coordinator().snapshot()['active'] is None


def test_assessment_mutation_failure_retains_hold(journal, monkeypatch):
    def assess(spec, lease):
        lease.transition('releasing')
        assert journal.pending()
        raise TimeoutError('adapter response lost')

    monkeypatch.setattr(coordinator, 'assess', assess)
    with pytest.raises(TimeoutError):
        with coordinator.coordinated_operation(coordinator.OperationSpec('load')):
            pytest.fail('must not enter body')
    assert journal.pending()[0]['state'] == 'uncertain'
    assert coordinator.get_coordinator().snapshot()['active']['phase'] == 'uncertain'


def test_nested_mutations_use_one_outer_journal_record(journal):
    @coordinator.coordinated(lambda args: coordinator.OperationSpec('release'))
    def inner():
        assert len(journal.pending()) == 1
        return {'ok': True}

    @coordinator.coordinated(lambda args: coordinator.OperationSpec('switch'))
    def outer():
        return inner()

    assert outer()['ok']
    assert not journal.pending()


def test_outer_exception_after_nested_completion_is_still_unknown(journal):
    @coordinator.coordinated(lambda args: coordinator.OperationSpec('release'))
    def inner():
        return {'ok': True}

    @coordinator.coordinated(lambda args: coordinator.OperationSpec('switch'))
    def outer():
        inner()
        raise RuntimeError('outer adapter still has an ambiguous outcome')

    with pytest.raises(RuntimeError):
        outer()
    assert journal.pending()[0]['state'] == 'uncertain'
    assert coordinator.get_coordinator().snapshot()['active']['phase'] == 'uncertain'


def test_crash_after_adapter_entered_survives_as_pending_operation(tmp_path):
    path = tmp_path / 'operations.sqlite3'
    marker = tmp_path / 'adapter-entered.txt'
    source = str(Path(__file__).resolve().parents[1])
    code = '''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
os.environ['GMAE_TASK_DB']=sys.argv[2]
from engine import coordinator
coordinator.restore_resource_operations()
coordinator.assess=lambda *args:None
@coordinator.coordinated(lambda args:coordinator.OperationSpec('release'))
def adapter():
    Path(sys.argv[3]).write_text('entered')
    os._exit(0)
adapter()
'''
    subprocess.run([sys.executable, '-c', code, source, str(path), str(marker)], check=True, timeout=10)
    assert marker.read_text() == 'entered'
    pending = OperationJournal(path).pending()
    assert len(pending) == 1 and pending[0]['state'] == 'inflight'
