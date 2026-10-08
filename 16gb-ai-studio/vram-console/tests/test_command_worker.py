"""Independent-process evidence for command supervision and no duplicate spawn."""
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from core.command_worker import launch, run_supervised
from core.operation_journal import OperationJournal
from core.registry import registry
from core import utils
from engine import coordinator


def operation(journal):
    return journal.begin({'operation': 'release', 'owner': 'test', 'service': 'all'})


def test_supervised_success_is_saved_before_return(tmp_path):
    journal = OperationJournal(tmp_path / 'operations.sqlite3')
    operation_id = operation(journal)
    command_id, result = run_supervised(journal, operation_id, [sys.executable, '-c', "print('saved')"], 5)
    assert result == (0, 'saved')
    assert OperationJournal(journal.store.path).command_result(command_id) == result
    assert journal.commands(operation_id)[0]['state'] == 'confirmed'


def test_duplicate_supervisors_cannot_execute_twice(tmp_path):
    journal = OperationJournal(tmp_path / 'operations.sqlite3')
    operation_id = operation(journal)
    marker = tmp_path / 'executed.txt'
    code = "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.open('a').write('x')"
    command_id = journal.command_begin(operation_id, [sys.executable, '-c', code, str(marker)], supervised=True)
    worker = str(Path(__file__).resolve().parents[1] / 'core' / 'command_worker.py')
    args = [sys.executable, worker, str(journal.store.path), command_id, '5']
    processes = [subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(2)]
    for process in processes:
        assert process.wait(timeout=10) == 0
    assert marker.read_text() == 'x'
    assert journal.command_result(command_id)[0] == 0


def test_parent_process_exit_does_not_prevent_completion_receipt(tmp_path):
    path = tmp_path / 'operations.sqlite3'
    marker = tmp_path / 'finished.txt'
    identity = tmp_path / 'command-id.txt'
    source = str(Path(__file__).resolve().parents[1])
    code = '''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from core.operation_journal import OperationJournal
from core.command_worker import launch
journal=OperationJournal(sys.argv[2])
operation_id=journal.begin({'operation':'release','owner':'parent','service':'all'})
command="import time,sys; from pathlib import Path; time.sleep(0.4); Path(sys.argv[1]).write_text('finished'); print('completed')"
command_id,process=launch(journal,operation_id,[sys.executable,'-c',command,sys.argv[3]],5)
Path(sys.argv[4]).write_text(command_id)
os._exit(0)
'''
    subprocess.run([sys.executable, '-c', code, source, str(path), str(marker), str(identity)], check=True, timeout=10)
    journal = OperationJournal(path)
    command_id = identity.read_text()
    deadline = time.monotonic() + 10
    result = None
    while result is None and time.monotonic() < deadline:
        result = journal.command_result(command_id)
        if result is None:
            time.sleep(0.03)
    assert result == (0, 'completed')
    assert marker.read_text() == 'finished'
    # The supervisor proves command completion; it does not assert that the
    # interrupted higher-level operation ran every remaining step.
    assert journal.pending()[0]['state'] == 'inflight'


def test_worker_timeout_persists_unknown_result(tmp_path):
    journal = OperationJournal(tmp_path / 'operations.sqlite3')
    operation_id = operation(journal)
    command_id, result = run_supervised(journal, operation_id,
                                        [sys.executable, '-c', 'import time; time.sleep(10)'], 0.1)
    assert result == (-1, 'TIMEOUT')
    assert journal.commands(operation_id)[0]['state'] == 'uncertain'
    assert journal.command_result(command_id) == result


def test_result_insert_failure_cannot_publish_a_success(tmp_path):
    journal = OperationJournal(tmp_path / 'operations.sqlite3')
    operation_id = operation(journal)
    marker = tmp_path / 'actually-executed.txt'
    with sqlite3.connect(journal.store.path) as connection:
        connection.execute("CREATE TRIGGER fail_result BEFORE INSERT ON resource_command_results "
                           "BEGIN SELECT RAISE(ABORT, 'result storage failed'); END")
    code = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('executed')"
    with pytest.raises(RuntimeError, match='without durable receipt'):
        run_supervised(journal, operation_id, [sys.executable, '-c', code, str(marker)], 5)
    assert marker.read_text() == 'executed'
    assert journal.commands(operation_id)[0]['state'] == 'inflight'


def test_production_run_args_uses_supervisor_and_releases_after_receipt(tmp_path, monkeypatch):
    previous = registry.get('operation_journal')
    journal = OperationJournal(tmp_path / 'operations.sqlite3')
    registry.set('operation_journal', journal)
    monkeypatch.setattr(coordinator, 'assess', lambda *args: None)
    try:
        with coordinator.coordinated_operation(coordinator.OperationSpec('release')) as lease:
            lease.transition('releasing')
            operation_id = journal.pending()[0]['id']
            assert utils.run_args([sys.executable, '-c', "print('production-path')"], 5) == (0, 'production-path')
            assert journal.commands(operation_id)[0]['state'] == 'confirmed'
            lease.transition('completed')
        assert not journal.pending()
        assert coordinator.get_coordinator().snapshot()['active'] is None
    finally:
        if previous is None:
            registry.delete('operation_journal')
        else:
            registry.set('operation_journal', previous)


def test_old_inflight_command_cannot_be_claimed_for_replay(tmp_path):
    journal = OperationJournal(tmp_path / 'operations.sqlite3')
    command_id = journal.command_begin(operation(journal), [sys.executable, '-c', 'pass'])
    assert journal.command_claim(command_id) is None
    assert journal.command_result(command_id) is None
