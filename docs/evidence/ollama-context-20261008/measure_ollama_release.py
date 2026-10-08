"""Record managed Ollama release separately from physical reclamation."""
import argparse
import json
from pathlib import Path
import time
from measure_comfy_workload import APP, get_json, gpu_sample
from core.process_ownership import ProcessOwnership
from core.operation_journal import OperationJournal
from core.task_store import TaskStore
from engine.coordinator import restore_resource_operations
from services.ollama import ollama_stop_all


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('refusing overwrite of evidence')
    owner = ProcessOwnership(APP / 'data/tasks.sqlite3').acquire()
    document = dict(kind='real_ollama_release', readings=[])
    try:
        restore_resource_operations()
        document['resident_before'] = get_json('http://127.0.0.1:11434/api/ps')['models']
        document['command_result'] = ollama_stop_all()
        if document['command_result'][0] != 0:
            raise RuntimeError('managed release command failed')
        deadline = time.monotonic() + 30
        while True:
            models = get_json('http://127.0.0.1:11434/api/ps')['models']
            sample = gpu_sample()
            document['readings'].append(dict(models=models, gpu=sample))
            if models == [] and sample['free_mb'] >= 12800 and sample['utilization'] <= 20:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('physical reclamation not verified')
            time.sleep(0.25)
        store = TaskStore(APP / 'data/tasks.sqlite3')
        document['pending_operations'] = len(OperationJournal(store.path).pending())
        if document['pending_operations']:
            raise RuntimeError('unconfirmed resource operation remains')
        document['status'] = 'success'
    except Exception as error:
        document.update(status='failed', error=str(error))
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8', newline='\n') as file:
            json.dump(document, file, indent=2)
        print(json.dumps({'status': document['status'], 'readings': len(document['readings'])}))
        # Ownership remains held until process exit, including failure paths.


if __name__ == '__main__':
    main()
