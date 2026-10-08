"""Explicit controlled Comfy baseline; raw samples are not comparative results."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

APP = Path(__file__).resolve().parents[1] / '16gb-ai-studio' / 'vram-console'
sys.path.insert(0, str(APP))
from core.process_ownership import ProcessOwnership
from core.task_store import TaskStore
from core.task_dispatch import TaskDispatcher
from core.operation_journal import OperationJournal
from core.workload_profile import workload_fingerprint
from engine.queue import _apply_params


def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def gpu_sample():
    result = subprocess.run(['nvidia-smi', '--id=0',
        '--query-gpu=memory.total,memory.used,memory.free,utilization.gpu',
        '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10, check=True)
    total, used, free, utilization = map(int, result.stdout.strip().split(','))
    if total <= 0 or not 0 <= used <= total or not 0 <= free <= total:
        raise ValueError('invalid GPU counters')
    return dict(monotonic_s=time.monotonic(), total_mb=total, used_mb=used,
                free_mb=free, utilization=utilization)


def torch_resident_bytes(stats):
    """Fresh CUDA 0 allocation, not an assertion of checkpoint identity."""
    devices = [device for device in stats.get('devices', [])
               if device.get('type') == 'cuda' and device.get('index') == 0]
    if len(devices) != 1:
        raise ValueError('unique CUDA 0 memory telemetry required')
    total, free = devices[0].get('torch_vram_total'), devices[0].get('torch_vram_free')
    if type(total) is not int or type(free) is not int or not 0 <= free <= total:
        raise ValueError('invalid torch memory counters')
    return total - free


def validate_trial_preflight(store, journal):
    """Refuse non-owned work before any experimental release or submission."""
    queue = get_json('http://127.0.0.1:8188/queue')
    if (not isinstance(queue.get('queue_running'), list) or
            not isinstance(queue.get('queue_pending'), list)):
        raise RuntimeError('invalid ComfyUI activity telemetry')
    if queue['queue_running'] or queue['queue_pending']:
        raise RuntimeError('ComfyUI is busy')
    models = get_json('http://127.0.0.1:11434/api/ps').get('models')
    if not isinstance(models, list) or models:
        raise RuntimeError('Ollama activity missing or resident; refusing isolated baseline')
    from services.docker import docker_containers
    if 'fooocus' in docker_containers(strict=True):
        raise RuntimeError('Fooocus is running; refusing to affect it')
    if journal.pending():
        raise RuntimeError('resource journal contains unconfirmed operations')
    if any(row['status'] not in store.TERMINAL for row in store.snapshot()):
        raise RuntimeError('durable task ledger contains unfinished work')


def prepare_unloaded_condition(required_free_mb):
    """Managed /free plus physical and torch evidence; CPU/disk caches uncontrolled."""
    from engine.coordinator import restore_resource_operations, get_coordinator
    from services.comfy import comfy_free
    restore_resource_operations()
    if get_coordinator().snapshot()['active'] is not None:
        raise RuntimeError('unresolved GPU operation')
    started = time.monotonic()
    release = comfy_free()
    if not release.get('ok'):
        raise RuntimeError('managed unload failed or unverified')
    deadline = time.monotonic() + 30
    readings = []
    while True:
        sample = gpu_sample()
        resident = torch_resident_bytes(get_json('http://127.0.0.1:8188/system_stats'))
        readings.append(dict(gpu=sample, torch_resident_bytes=resident))
        if resident <= 64 * 1024 * 1024 and sample['free_mb'] >= required_free_mb and sample['utilization'] <= 20:
            return dict(condition='model_unloaded_low_torch_verified', duration_s=time.monotonic() - started,
                        managed_release=release, readings=readings,
                        limitation='low torch occupancy does not prove CPU/disk caches cold')
        if time.monotonic() >= deadline:
            raise RuntimeError('unload did not reach physical/torch baseline; no generation submitted')
        time.sleep(0.25)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--seed', type=int, default=42)
    conditions = parser.add_mutually_exclusive_group()
    conditions.add_argument('--resident-baseline', action='store_true',
                        help='explicit small resident-model trial; not a cold-load budget')
    conditions.add_argument('--prepare-unloaded', action='store_true',
                        help='explicit managed unload with physical and low-torch verification')
    parser.add_argument('--width', type=int, default=512)
    parser.add_argument('--height', type=int, default=512)
    parser.add_argument('--steps', type=int, default=8)
    parser.add_argument('--cfg', type=float, default=6.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        raise ValueError('timeout must be positive')
    if args.seed < 0:
        raise ValueError('seed must be nonnegative')
    params = dict(prompt='A small red ceramic teapot on a plain wooden table, studio lighting',
                  width=args.width, height=args.height, steps=args.steps, cfg=args.cfg, seed=args.seed)
    # Validate and bind controls before acquiring ownership or changing backend state.
    wf = _apply_params(json.loads((APP / 'workflows' / 'sdxl_t2i.json').read_text()), params)
    if args.width > 1024 or args.height > 1024 or args.steps > 20:
        raise ValueError('controlled collector supports at most 1024x1024 and 20 steps')
    output = Path(args.output)
    if output.exists():
        raise ValueError('refusing to overwrite experiment evidence')
    db = APP / 'data' / 'tasks.sqlite3'
    owner = ProcessOwnership(db).acquire()
    stop = threading.Event()
    samples, sampling_errors = [], []
    document = dict(schema_version=1, kind='real_gpu_baseline',
        collector_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        recorded_at=datetime.now(timezone.utc).isoformat(), samples=samples,
        sampling_errors=sampling_errors, comparative_result=False,
        limitations=['single run', 'sampled whole-device memory includes desktop/background activity',
                     'sampling can miss transient peaks', 'no cold-cache or OOM guarantee'])
    thread = None
    try:
        store = TaskStore(db)
        validate_trial_preflight(store, OperationJournal(db))
        system = get_json('http://127.0.0.1:8188/system_stats')
        launch_args = system.get('system', {}).pop('argv', None)
        system['launch_args_sha256'] = hashlib.sha256(json.dumps(launch_args, sort_keys=True).encode()).hexdigest()
        document['backend_environment'] = system
        model_path = '/opt/ComfyUI/models/checkpoints/sd_xl_base_1.0.safetensors'
        digest_result = subprocess.run(['docker', 'exec', 'comfyui', 'sha256sum', model_path],
            capture_output=True, text=True, timeout=120, check=True)
        model_digest = digest_result.stdout.split()[0]
        if len(model_digest) != 64 or any(c not in '0123456789abcdef' for c in model_digest):
            raise ValueError('invalid model digest')
        document['model_artifact'] = dict(filename='sd_xl_base_1.0.safetensors', sha256=model_digest)
        identity = subprocess.run(['nvidia-smi', '--id=0',
            '--query-gpu=name,uuid,driver_version', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        name, gpu_uuid, driver = (part.strip() for part in identity.split(','))
        document['gpu_identity'] = dict(name=name, driver=driver,
            uuid_sha256=hashlib.sha256(gpu_uuid.encode()).hexdigest())
        required_free = 4096 if args.resident_baseline else 8192 + 2560
        if args.prepare_unloaded:
            # Identity hashing can be slow; recheck work immediately before mutation.
            validate_trial_preflight(store, OperationJournal(db))
            document['preparation'] = prepare_unloaded_condition(required_free)
        baseline = gpu_sample()
        document['baseline_torch_resident_bytes'] = torch_resident_bytes(
            get_json('http://127.0.0.1:8188/system_stats'))
        if baseline['free_mb'] < required_free or baseline['utilization'] > 20:
            raise RuntimeError('insufficient capacity or active GPU workload')
        document['trial_condition'] = ('model_unloaded_low_torch_verified' if args.prepare_unloaded else
            'resident_memory_observed_model_identity_unproven' if args.resident_baseline else
            'cache_condition_uncontrolled')
        document['required_free_mb'] = required_free
        document['baseline'] = baseline
        document.update(workflow=wf, workflow_sha256=workload_fingerprint(wf),
                        parameters=params, experimental_cold_planning_estimate_mb=8192, reserve_mb=2560)
        validate_trial_preflight(store, OperationJournal(db))
        task, _ = store.accept(dict(model='SDXL', workflow='sdxl_t2i.json', params=params,
            effective_workflow=wf, workflow_sha256=workload_fingerprint(wf)))
        task = store.checkpoint(task['id'], task['version'], 'precheck', {'experiment': True})
        document['task_id'] = task['id']

        def sample_loop():
            while not stop.is_set():
                try:
                    samples.append(gpu_sample())
                except Exception as error:
                    sampling_errors.append(str(error))
                stop.wait(0.2)

        thread = threading.Thread(target=sample_loop)
        thread.start()
        started = time.monotonic()

        def submit(workflow, sid):
            request = urllib.request.Request('http://127.0.0.1:8188/prompt',
                data=json.dumps(dict(prompt=workflow, prompt_id=sid, client_id='gmae-baseline')).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response).get('prompt_id'), None

        task = TaskDispatcher(store).dispatch(task, wf, submit)
        pid = task['checkpoint']['prompt_id']
        document['prompt_id'] = pid
        while time.monotonic() - started < args.timeout:
            row = get_json('http://127.0.0.1:8188/history/' + pid).get(pid)
            if row and row.get('status', {}).get('status_str') in ('success', 'error'):
                status = row['status']['status_str']
                store.checkpoint(task['id'], task['version'], 'done' if status == 'success' else 'failed',
                    {'experiment_terminal': status})
                document.update(terminal_status=status, duration_s=time.monotonic() - started,
                                output_node_ids=sorted((row.get('outputs') or {}).keys()))
                cached = [node for kind, details in row.get('status', {}).get('messages', [])
                          if kind == 'execution_cached' for node in details.get('nodes', [])]
                document['cached_node_ids'] = cached
                document['sampler_cache_hit'] = '5' in cached
                break
            time.sleep(0.5)
        else:
            store.checkpoint(task['id'], task['version'], 'uncertain', {'error': 'experiment timeout'})
            raise RuntimeError('timeout: backend execution unknown, do not replay')
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=15)
        if samples:
            document['observed_device_peak_mb'] = max(sample['used_mb'] for sample in samples)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        with output.open('xb') as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        owner.close()
        print(json.dumps(dict(evidence=str(output), sha256=hashlib.sha256(payload).hexdigest(),
            terminal=document.get('terminal_status'), samples=len(samples))))


if __name__ == '__main__':
    main()
