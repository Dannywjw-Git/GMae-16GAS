"""Explicit local startup experiment; never installs a production peak automatically."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from measure_comfy_workload import (APP, get_json, gpu_sample, prepare_unloaded_condition,
                                    validate_trial_preflight)
from core.process_ownership import ProcessOwnership
from core.task_store import TaskStore
from core.operation_journal import OperationJournal
from engine.coordinator import OperationSpec, coordinated_operation, restore_resource_operations
from clients.docker_client import container_action, container_target_state
from clients.comfyui_client import residency_snapshot


def wait_ready(before, digest):
    deadline = time.monotonic() + 120
    attempts = []
    while time.monotonic() < deadline:
        try:
            stats = get_json('http://127.0.0.1:8188/system_stats')
            system = {key: stats['system'][key] for key in before}
            if system != before:
                raise ValueError('execution environment changed')
            queue = get_json('http://127.0.0.1:8188/queue')
            if (not isinstance(queue.get('queue_running'), list) or not isinstance(queue.get('queue_pending'), list) or queue['queue_running'] or queue['queue_pending']):
                raise ValueError('external work appeared during startup experiment')
            observer = residency_snapshot()
            if observer.get('ok'):
                if observer['observer_code_sha256'] != digest:
                    raise ValueError('observer source mismatch')
                return dict(system=system, observer=observer, attempts=attempts)
        except ValueError:
            raise
        except Exception as error:
            attempts.append(type(error).__name__)
        time.sleep(1)
    raise RuntimeError('readiness not verified; do not repeat restart blindly')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('refusing overwrite of evidence')
    document = dict(kind='comfy_startup_calibration', recorded_at=datetime.now(timezone.utc).isoformat(),
                    production_profile_installed=False, warm_admission_enabled=False,
                    experimental_capacity_bound_mb=10240, reserve_mb=2560,
                    samples=[], sampling_errors=[])
    stop = threading.Event()
    def sample():
        while not stop.is_set():
            try:
                document['samples'].append(gpu_sample())
            except Exception as error:
                document['sampling_errors'].append(type(error).__name__)
            stop.wait(0.25)
    owner = ProcessOwnership(APP / 'data/tasks.sqlite3').acquire()
    worker = None
    try:
        store, journal = TaskStore(APP / 'data/tasks.sqlite3'), OperationJournal(APP / 'data/tasks.sqlite3')
        validate_trial_preflight(store, journal)
        restore_resource_operations()
        document['preparation'] = prepare_unloaded_condition(10752)
        validate_trial_preflight(store, journal)
        system = get_json('http://127.0.0.1:8188/system_stats')['system']
        before = {key: system[key] for key in ('comfyui_version', 'python_version', 'pytorch_version')}
        document['before_environment'] = before
        document['before_container'] = container_target_state('comfyui')
        if not document['before_container'].get('ok') or not document['before_container'].get('running'):
            raise ValueError('existing container identity not verified')
        source = APP.parents[1] / 'integrations/gmae_comfy_observer'
        digest = hashlib.sha256(b''.join((source / name).read_bytes() for name in ('observer.py', '__init__.py'))).hexdigest()
        document['observer_code_sha256'] = digest
        worker = threading.Thread(target=sample)
        worker.start()
        started = time.monotonic()
        spec = OperationSpec('restart', 'comfyui', owner='experiment:comfy-startup',
                             command_only=True, startup_calibration=True)
        with coordinated_operation(spec) as lease:
            lease.transition('running')
            rc, _ = container_action('comfyui', 'restart', 60)
            document['command_rc'] = rc
            state = container_target_state('comfyui')
            document['after_container'] = state
            if (rc != 0 or not state.get('ok') or not state.get('running') or state.get('paused') or
                    state.get('restarting') or state.get('dead') or
                    state.get('container_id') != document['before_container'].get('container_id')):
                lease.uncertain('startup experiment command/target not confirmed')
                raise RuntimeError('restart command/target unconfirmed')
            lease.transition('completed', target_state=state)
        document['readiness'] = wait_ready(before, digest)
        time.sleep(15)  # Defined post-readiness sampling window, no new GPU work.
        document['duration_s'] = time.monotonic() - started
        document['status'] = 'success'
    except Exception as error:
        document.update(status='failed', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=15)
        document['sampler_stopped'] = worker is None or not worker.is_alive()
        if document['samples']:
            document['observed_whole_device_peak_mb'] = max(max(s['used_mb'], s['total_mb']-s['free_mb']) for s in document['samples'])
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8', newline='\n') as file:
            json.dump(document, file, indent=2, ensure_ascii=False)
        owner.close()
        print(json.dumps({key: document.get(key) for key in ('status', 'command_rc', 'duration_s', 'observed_whole_device_peak_mb')}))


if __name__ == '__main__':
    main()
