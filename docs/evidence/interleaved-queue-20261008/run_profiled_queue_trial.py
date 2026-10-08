"""Exercise the formal queue/coordinator with installed evidence and real GPU."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from measure_comfy_workload import APP, get_json, gpu_sample
from clients.comfyui_client import residency_snapshot
from core.process_ownership import ProcessOwnership
from engine.coordinator import restore_resource_operations, get_coordinator
from engine import queue


def run_trial(seed, output, timeout, owner):
    """One formal trial; caller retains the real process lock across a sequence."""
    if not isinstance(owner, ProcessOwnership) or owner.handle is None:
        raise RuntimeError('GPU ownership required')
    if seed < 0 or timeout <= 0:
        raise ValueError('invalid trial arguments')
    output = Path(output)
    if output.exists():
        raise ValueError('refusing to overwrite evidence')
    restore_resource_operations()
    queue.queue_restore()
    if get_coordinator().snapshot()['active'] is not None:
        raise RuntimeError('recovered GPU operation remains unresolved')
    if any(task['status'] not in queue.TaskStore.TERMINAL for task in queue._store().snapshot()):
        raise RuntimeError('unfinished durable task')
    if get_json('http://127.0.0.1:11434/api/ps').get('models'):
        raise RuntimeError('Ollama has resident models; refusing this isolated trial')
    from services.docker import docker_containers
    if 'fooocus' in docker_containers(strict=True):
        raise RuntimeError('Fooocus is running; refusing to affect it')
    backend = get_json('http://127.0.0.1:8188/queue')
    if backend['queue_running'] or backend['queue_pending']:
        raise RuntimeError('ComfyUI is busy')
    samples, errors = [], []
    stop = threading.Event()
    document = dict(kind='real_profiled_queue_trial', recorded_at=datetime.now(timezone.utc).isoformat(),
                    samples=samples, sampling_errors=errors, comparative_result=False)

    def sampler():
        while not stop.is_set():
            try:
                samples.append(gpu_sample())
            except Exception as error:
                errors.append(str(error))
            stop.wait(0.2)

    document['residency_before'] = residency_snapshot()
    document['baseline'] = gpu_sample()
    from services import comfy
    original_free = comfy.comfy_free
    document['managed_unload_calls'] = 0
    def counted_free():
        document['managed_unload_calls'] += 1
        return original_free()
    comfy.comfy_free = counted_free
    thread = threading.Thread(target=sampler)
    thread.start()
    started = time.monotonic()
    try:
        params = dict(prompt='A small red ceramic teapot on a plain wooden table, studio lighting',
                      width=512, height=512, steps=8, cfg=6.0, seed=seed)
        result = queue.queue_enqueue('SDXL', params)
        if not result.get('ok'):
            raise RuntimeError(str(result))
        task_id = result['task']['id']
        document['task_id'] = task_id
        while time.monotonic() - started < timeout:
            saved = queue._store().get(task_id)
            if saved['status'] in queue.TaskStore.TERMINAL:
                checkpoint = saved['checkpoint']
                document['effective_workflow'] = saved['intent']['effective_workflow']
                document['profile_reference'] = saved['intent'].get('profile_reference')
                document.update(task_status=saved['status'], duration_s=time.monotonic() - started,
                    budget=checkpoint.get('budget'), prompt_id=checkpoint.get('prompt_id'),
                    error=checkpoint.get('error', ''), workflow_sha256=saved['intent']['workflow_sha256'])
                if checkpoint.get('prompt_id'):
                    history = get_json('http://127.0.0.1:8188/history/' + checkpoint['prompt_id'])
                    row = history.get(checkpoint['prompt_id'], {})
                    document['backend_terminal'] = row.get('status', {}).get('status_str')
                    cached = [node for kind, details in row.get('status', {}).get('messages', [])
                              if kind == 'execution_cached' for node in details.get('nodes', [])]
                    document['sampler_cache_hit'] = '5' in cached
                break
            time.sleep(0.25)
        else:
            raise RuntimeError('trial timeout; retain durable backend identity, do not replay')
    finally:
        stop.set()
        thread.join(timeout=15)
        document['coordination'] = get_coordinator().snapshot()
        document['residency_after'] = residency_snapshot()
        comfy.comfy_free = original_free
        if samples:
            document['observed_device_peak_mb'] = max(sample['used_mb'] for sample in samples)
        output.parent.mkdir(parents=True, exist_ok=True)
        def redact(value):
            if isinstance(value, dict):
                return {(key + '_sha256' if key in ('token','reservation_token') else key):
                    (hashlib.sha256(str(item).encode()).hexdigest() if key in ('token','reservation_token') else redact(item)) for key,item in value.items()}
            if isinstance(value,list): return [redact(item) for item in value]
            return value
        payload = json.dumps(redact(document), ensure_ascii=False, indent=2, allow_nan=False).encode()
        with output.open('xb') as file:
            file.write(payload)
        # OS ownership lives to process exit, including any daemon queue worker.
        print(json.dumps(dict(evidence=str(output), sha256=hashlib.sha256(payload).hexdigest(),
                              task_status=document.get('task_status'))))
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--profile-dir')
    args = parser.parse_args()
    if args.profile_dir:
        os.environ['GMAE_PROFILE_DIR'] = str(Path(args.profile_dir).resolve())
    owner = ProcessOwnership(APP / 'data' / 'tasks.sqlite3').acquire()
    run_trial(args.seed,args.output,args.timeout,owner)
    # Retain ownership until process exit, including daemon workers on failure.


if __name__ == '__main__':
    main()
