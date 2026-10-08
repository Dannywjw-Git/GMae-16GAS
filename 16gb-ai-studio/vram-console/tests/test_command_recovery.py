"""Only trusted single-container receipts may release recovered manual holds."""
from dataclasses import asdict
import sqlite3

import pytest
from core.operation_journal import OperationJournal
from core.registry import registry
from core.resource_coordinator import ResourceRequest, ResourceDenied
from engine import coordinator


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    previous = registry.get('operation_journal')
    journal = OperationJournal(tmp_path / 'operations.sqlite3')
    registry.set('operation_journal', journal)
    monkeypatch.setattr(coordinator, 'fresh_gpu', lambda: {'ok': True})
    yield journal
    if previous is None:
        registry.delete('operation_journal')
    else:
        registry.set('operation_journal', previous)


def held(journal, args=None, command_only=True, return_code=0, completed=True):
    request = ResourceRequest('release', 'original-owner', 'comfyui')
    operation_id = journal.begin({**asdict(request), 'command_only': command_only})
    command_id = journal.command_begin(operation_id, args or ['docker', 'stop', 'comfyui'], supervised=True)
    if completed:
        journal.command_claim(command_id)
        journal.command_finish(command_id, return_code, 'receipt')
    lease = coordinator.get_coordinator().restore_uncertain(request, {'journal_id': operation_id})
    return operation_id, command_id, lease


def test_completed_owned_control_receipt_resolves_without_replaying(recovery):
    operation_id, command_id, _ = held(recovery)
    result = coordinator.reconcile_recovered_operations()[0]
    assert result['resolved']
    assert recovery.get(operation_id)['state'] == 'confirmed'
    assert coordinator.get_coordinator().snapshot()['active'] is None
    assert len(recovery.commands(operation_id)) == 1


def test_startup_reconciliation_stops_on_unknown_receipt(recovery):
    held(recovery, completed=False)
    results = coordinator.reconcile_recovered_operations()
    assert len(results) == 1 and results[0]['code'] == 'UNCONFIRMED_EXECUTION'
    assert coordinator.get_coordinator().snapshot()['active'] is not None


def test_late_worker_receipt_can_resolve_existing_hold(recovery):
    operation_id, command_id, _ = held(recovery, completed=False)
    assert coordinator.reconcile_uncertain()['code'] == 'UNCONFIRMED_EXECUTION'
    assert coordinator.get_coordinator().snapshot()['active'] is not None
    assert recovery.command_claim(command_id) == ['docker', 'stop', 'comfyui']
    recovery.command_finish(command_id, 0, 'completed-after-parent-exit')
    assert coordinator.reconcile_uncertain()['resolved']
    assert len(recovery.commands(operation_id)) == 1


@pytest.mark.parametrize('return_code', [-1, 1, -9])
def test_unknown_or_failed_receipt_does_not_resolve(recovery, return_code):
    held(recovery, return_code=return_code)
    assert coordinator.reconcile_uncertain()['code'] == 'UNCONFIRMED_EXECUTION'
    assert coordinator.get_coordinator().snapshot()['active'] is not None


@pytest.mark.parametrize('args', [['docker', 'exec', 'comfyui', 'sh', '-c', 'anything'],
                                 ['docker', 'stop', 'other-container'], ['python', '-c', 'pass']])
def test_unqualified_command_cannot_use_control_recovery(recovery, args):
    held(recovery, args=args)
    assert coordinator.reconcile_uncertain()['code'] == 'UNCONFIRMED_EXECUTION'


def test_mixed_operation_does_not_resolve_from_one_command(recovery):
    held(recovery, command_only=False)
    assert coordinator.reconcile_uncertain()['code'] == 'UNCONFIRMED_EXECUTION'


def test_unavailable_gpu_evidence_retains_completed_command_hold(recovery, monkeypatch):
    held(recovery)

    def unavailable():
        raise ResourceDenied('TELEMETRY_UNAVAILABLE', 'no fresh reading')

    monkeypatch.setattr(coordinator, 'fresh_gpu', unavailable)
    assert coordinator.reconcile_uncertain()['code'] == 'TELEMETRY_UNAVAILABLE'
    assert coordinator.get_coordinator().snapshot()['active'] is not None


def test_operation_terminal_write_failure_keeps_hold_and_allows_retry(recovery):
    operation_id, _, _ = held(recovery)
    with sqlite3.connect(recovery.store.path) as connection:
        connection.execute("CREATE TRIGGER fail_recovery BEFORE UPDATE ON resource_operations "
                           "BEGIN SELECT RAISE(ABORT, 'recovery storage failed'); END")
    assert coordinator.reconcile_uncertain()['code'] == 'TASK_STORAGE_UNAVAILABLE'
    assert coordinator.get_coordinator().snapshot()['active'] is not None
    with sqlite3.connect(recovery.store.path) as connection:
        connection.execute('DROP TRIGGER fail_recovery')
    assert coordinator.reconcile_uncertain()['resolved']
    assert recovery.get(operation_id)['state'] == 'confirmed'
