"""Install optional read-only observer into the existing managed ComfyUI container."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from measure_comfy_workload import APP, get_json, validate_trial_preflight
from core.process_ownership import ProcessOwnership
from core.task_store import TaskStore
from core.operation_journal import OperationJournal
from engine.coordinator import OperationSpec, coordinated_operation, restore_resource_operations
from services.docker import docker_action
from clients.comfyui_client import residency_snapshot

DESTINATION = '/opt/ComfyUI/custom_nodes/gmae_comfy_observer'
FILES = ('observer.py', '__init__.py')


def command(args, timeout=120):
    return subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout, check=True).stdout.strip()


def environment():
    stats = get_json('http://127.0.0.1:8188/system_stats')['system']
    return {key: stats[key] for key in ('comfyui_version', 'python_version', 'pytorch_version')}


def stage_files(source):
    """Never overwrite an existing custom-node package with different contents."""
    check = "from pathlib import Path;import json;p=Path(%r);print(json.dumps(p.exists()))" % DESTINATION
    exists = json.loads(command(['exec', 'comfyui', 'python3', '-c', check]))
    if exists:
        code = "from pathlib import Path;import hashlib;p=Path(%r);print(hashlib.sha256(b''.join((p/n).read_bytes() for n in %r)).hexdigest())" % (DESTINATION, FILES)
        remote = command(['exec', 'comfyui', 'python3', '-c', code])
        if remote != hashlib.sha256(b''.join((source / file).read_bytes() for file in FILES)).hexdigest():
            raise ValueError('different observer package exists; refusing overwrite')
        return
    command(['exec', 'comfyui', 'python3', '-c', 'from pathlib import Path;Path(%r).mkdir()' % DESTINATION])
    for file in FILES:
        command(['cp', str(source / file), 'comfyui:' + DESTINATION + '/' + file])


def check_restart_admission():
    """Use the production guard without executing a container command."""
    with coordinated_operation(OperationSpec("restart", "comfyui", command_only=True)):
        pass


def wait_backend(expected, digest):
    deadline = time.monotonic() + 90
    while True:
        try:
            current = environment()
        except Exception:
            current = None
        if current is not None:
            if current != expected:
                raise ValueError('backend execution environment changed after restart; recalibration required')
            probe = residency_snapshot()
            if probe.get('ok'):
                if probe['observer_code_sha256'] != digest:
                    raise ValueError('loaded observer source mismatch')
                return probe
        if time.monotonic() >= deadline:
            raise RuntimeError('backend/observer did not become verifiable; do not repeat restart blindly')
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('refusing overwrite of installation evidence')
    source = APP.parents[1] / 'integrations/gmae_comfy_observer'
    digest = hashlib.sha256(b''.join((source / file).read_bytes() for file in FILES)).hexdigest()
    document = dict(kind='managed_comfy_observer_installation', observer_code_sha256=digest,
                    recorded_at=datetime.now(timezone.utc).isoformat(), warm_admission_enabled=False)
    owner = ProcessOwnership(APP / 'data/tasks.sqlite3').acquire()
    try:
        store, journal = TaskStore(APP / 'data/tasks.sqlite3'), OperationJournal(APP / 'data/tasks.sqlite3')
        validate_trial_preflight(store, journal)
        restore_resource_operations()
        check_restart_admission()
        document['restart_preflight_passed'] = True
        document['before_environment'] = environment()
        stage_files(source)
        document['files_staged'] = True
        # Preserve changes locally; never recreate the container or publish its image.
        tag = 'gmae-comfy-observer:local-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + digest[:8]
        document['private_snapshot_tag'] = tag
        document['private_snapshot_image_id'] = command(['commit', '--no-pause', 'comfyui', tag], timeout=1200).splitlines()[-1]
        validate_trial_preflight(store, journal)
        rc, message = docker_action('comfyui', 'restart')
        document['restart_rc'] = rc
        if rc:
            raise RuntimeError('managed restart rejected or unconfirmed: ' + str(message))
        document['observer'] = wait_backend(document['before_environment'], digest)
        document['after_environment'] = environment()
        document['activation_verified'] = True
    except Exception as error:
        document['activation_verified'] = False
        document['error_type'] = type(error).__name__
        document['error'] = str(error)
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8', newline='\n') as file:
            json.dump(document, file, indent=2, ensure_ascii=False)
        owner.close()
        print(json.dumps(dict(activation_verified=document.get('activation_verified', False), evidence=str(output))))


if __name__ == '__main__':
    main()
