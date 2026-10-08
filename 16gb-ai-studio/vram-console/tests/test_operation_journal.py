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
    # These boundary tests inject subprocess.run locally. The supervisor path
    # is separately covered with real independent processes.
    registry.get('operation_journal').supervised = False
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


def test_command_receipt_is_committed_before_spawn(journal, monkeypatch):
    from core import utils

    def run(args, **kwargs):
        pending = journal.pending()
        commands = OperationJournal(journal.store.path).commands(pending[0]['id'])
        assert len(commands) == 1 and commands[0]['state'] == 'inflight'
        assert commands[0]['intent'] == args
        return subprocess.CompletedProcess(args, 0, 'ok', '')

    monkeypatch.setattr(utils.subprocess, 'run', run)
    with coordinator.coordinated_operation(coordinator.OperationSpec('release')) as lease:
        lease.transition('releasing')
        operation_id = journal.pending()[0]['id']
        assert utils.run_args(['docker', 'stop', 'managed-test']) == (0, 'ok')
        assert journal.commands(operation_id)[0]['state'] == 'confirmed'
        lease.transition('completed')
    assert not journal.pending()


def test_command_intent_failure_prevents_process_spawn(journal, monkeypatch):
    from core import utils
    with sqlite3.connect(journal.store.path) as connection:
        connection.execute("CREATE TRIGGER fail_command BEFORE INSERT ON resource_commands "
                           "BEGIN SELECT RAISE(ABORT, 'command storage failed'); END")
    spawn = Mock()
    monkeypatch.setattr(utils.subprocess, 'run', spawn)
    with coordinator.coordinated_operation(coordinator.OperationSpec('release')) as lease:
        lease.transition('releasing')
        rc, _ = utils.run_args(['docker', 'stop', 'managed-test'])
        assert rc == -2
        lease.transition('failed')
    spawn.assert_not_called()


def test_real_command_timeout_cannot_be_reclassified_as_known_failure(journal):
    from core import utils

    @coordinator.coordinated(lambda args: coordinator.OperationSpec('release'))
    def adapter():
        rc, output = utils.run_args([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=0.1)
        return {'ok': rc == 0, 'output': output}

    assert adapter()['ok'] is False
    active = coordinator.get_coordinator().snapshot()['active']
    assert active['phase'] == 'uncertain'
    commands = journal.commands(active['journal_id'])
    assert commands[0]['state'] == 'uncertain' and commands[0]['return_code'] == -1
    with pytest.raises(ResourceDenied):
        with coordinator.get_coordinator().operation(ResourceRequest('start', 'next')):
            pytest.fail('timeout must retain ownership')


def test_failed_command_receipt_write_retains_inflight_identity(journal, monkeypatch):
    from core import utils
    with sqlite3.connect(journal.store.path) as connection:
        connection.execute("CREATE TRIGGER fail_receipt BEFORE UPDATE ON resource_commands "
                           "BEGIN SELECT RAISE(ABORT, 'receipt storage failed'); END")
    monkeypatch.setattr(utils.subprocess, 'run', lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0, 'accepted', ''))
    with coordinator.coordinated_operation(coordinator.OperationSpec('release')) as lease:
        lease.transition('releasing')
        assert utils.run_args(['docker', 'stop', 'managed-test'])[0] == -2
    active = coordinator.get_coordinator().snapshot()['active']
    assert active['phase'] == 'uncertain'
    assert journal.commands(active['journal_id'])[0]['state'] == 'inflight'


def test_unconfirmed_command_prevents_forced_operation_confirmation(journal):
    operation_id = journal.begin({'operation': 'release', 'owner': 'test', 'service': 'all'})
    journal.command_begin(operation_id, ['docker', 'stop', 'managed-test'])
    from core.task_store import TaskConflict
    with pytest.raises(TaskConflict, match='unconfirmed'):
        journal.finish(operation_id, True, {'terminal': True})
    assert journal.pending()


def test_read_only_docker_query_does_not_create_mutation_receipt(journal, monkeypatch):
    from core import utils
    monkeypatch.setattr(utils.subprocess, 'run', lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 1, '', 'unavailable'))
    with coordinator.coordinated_operation(coordinator.OperationSpec('release')) as lease:
        lease.transition('releasing')
        operation_id = journal.pending()[0]['id']
        assert utils.run_args(['docker', 'ps'])[0] == 1
        assert not journal.commands(operation_id)
        lease.transition('failed')
    assert not journal.pending()


@pytest.mark.parametrize('return_code', [1, -9])
def test_nonzero_mutation_exit_keeps_receipt_unknown(journal, monkeypatch, return_code):
    from core import utils
    monkeypatch.setattr(utils.subprocess, 'run', lambda args, **kwargs:
                        subprocess.CompletedProcess(args, return_code, '', 'failure'))
    with coordinator.coordinated_operation(coordinator.OperationSpec('release')) as lease:
        lease.transition('releasing')
        assert utils.run_args(['docker', 'stop', 'managed-test'])[0] == return_code
    active = coordinator.get_coordinator().snapshot()['active']
    assert active['phase'] == 'uncertain'
    assert journal.commands(active['journal_id'])[0]['return_code'] == return_code
