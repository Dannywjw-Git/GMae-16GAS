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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    if args.timeout <= 0:
        raise ValueError('timeout must be positive')
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
        queue = get_json('http://127.0.0.1:8188/queue')
        if queue['queue_running'] or queue['queue_pending']:
            raise RuntimeError('ComfyUI is busy')
        if get_json('http://127.0.0.1:11434/api/ps').get('models'):
            raise RuntimeError('Ollama has resident models; refusing mixed baseline')
        system = get_json('http://127.0.0.1:8188/system_stats')
        system.get('system', {}).pop('argv', None)
        document['backend_environment'] = system
        identity = subprocess.run(['nvidia-smi', '--id=0',
            '--query-gpu=name,uuid,driver_version', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        name, gpu_uuid, driver = (part.strip() for part in identity.split(','))
        document['gpu_identity'] = dict(name=name, driver=driver,
            uuid_sha256=hashlib.sha256(gpu_uuid.encode()).hexdigest())
        baseline = gpu_sample()
        if baseline['free_mb'] < 8192 + 2560 or baseline['utilization'] > 20:
            raise RuntimeError('insufficient capacity or active GPU workload')
        document['baseline'] = baseline
        params = dict(prompt='A small red ceramic teapot on a plain wooden table, studio lighting',
                      width=512, height=512, steps=8, cfg=6.0, seed=42)
        wf = _apply_params(json.loads((APP / 'workflows' / 'sdxl_t2i.json').read_text()), params)
        document.update(workflow=wf, workflow_sha256=workload_fingerprint(wf),
                        parameters=params, admission_budget_mb=8192, reserve_mb=2560)
        store = TaskStore(db)
        if OperationJournal(db).pending():
            raise RuntimeError('resource journal contains unconfirmed operations')
        if any(row['status'] not in store.TERMINAL for row in store.snapshot()):
            raise RuntimeError('durable task ledger contains unfinished work')
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
