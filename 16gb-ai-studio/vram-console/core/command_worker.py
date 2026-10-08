"""One-shot durable command supervisor; no automatic replay during recovery.

The supervisor owns subprocess lifetime and stores completion independently of
the server. Atomic claim prevents duplicate supervisors executing the same ID.
If the worker dies or a remote request outlives its CLI, the record stays unknown.
"""
import os
import math
from pathlib import Path
import subprocess
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.operation_journal import OperationJournal


def execute(path, command_id, timeout):
    journal = OperationJournal(path)
    args = journal.command_claim(command_id)
    if args is None:
        return False
    try:
        executable = os.path.basename(str(args[0])).lower()
        text_options = {"encoding": "utf-8", "errors": "replace"} if executable in ("docker", "docker.exe") else {}
        process = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=timeout, **text_options)
        return_code = process.returncode
        output = ((process.stdout or '') + (process.stderr or '')).strip()
    except subprocess.TimeoutExpired:
        return_code, output = -1, 'TIMEOUT'
    except Exception as error:
        return_code, output = -2, str(error)
    # If storage fails, exit without pretending that the parent can confirm the
    # command. The committed inflight record remains the recovery blocker.
    journal.command_finish(command_id, return_code, output)
    return True


def launch(journal, operation_id, args, timeout):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('command timeout must be a positive finite number')
    command_id = journal.command_begin(operation_id, args, supervised=True)
    options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
               'close_fds': True}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), str(journal.store.path.resolve()), command_id, str(timeout)],
        **options)
    return command_id, process


def run_supervised(journal, operation_id, args, timeout):
    command_id, process = launch(journal, operation_id, args, timeout)
    deadline = time.monotonic() + timeout + 12
    while time.monotonic() < deadline:
        result = journal.command_result(command_id)
        if result is not None:
            # A result is committed before the supervisor exits. Reap the local
            # child without requiring it for trust in the durable receipt.
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            return command_id, result
        if process.poll() is not None:
            # Re-read after exit, since a commit may race the preceding read.
            result = journal.command_result(command_id)
            if result is not None:
                return command_id, result
            raise RuntimeError('command supervisor exited without durable receipt: ' + command_id)
        time.sleep(0.05)
    # Do not kill the worker or overwrite its record: it may still commit the
    # result, including after the server is gone.
    raise RuntimeError('command supervisor result unavailable: ' + command_id)


if __name__ == '__main__':
    execute(sys.argv[1], sys.argv[2], float(sys.argv[3]))
