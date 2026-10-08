"""Real sequential SDXL -> Qwen -> SDXL through one durable production queue."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import threading
import time
from measure_comfy_workload import APP,gpu_sample,prepare_unloaded_condition,validate_trial_preflight
from core.process_ownership import ProcessOwnership
from core.task_store import TaskStore
from core.operation_journal import OperationJournal
from engine.coordinator import restore_resource_operations,get_coordinator
from engine import queue
from run_profiled_ollama_trial import redact


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-dir',required=True)
    parser.add_argument('--ollama-raw',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--first-seed',type=int,default=68)
    args=parser.parse_args();output=Path(args.output)
    if output.exists(): raise ValueError('refusing overwrite of evidence')
    os.environ['GMAE_PROFILE_DIR']=str(Path(args.profile_dir).resolve())
    request=json.loads(Path(args.ollama_raw).read_bytes())['request']
    owner=ProcessOwnership(APP/'data/tasks.sqlite3').acquire()
    document=dict(kind='real_mixed_durable_queue_trial',recorded_at=datetime.now(timezone.utc).isoformat(),
                  task_ids=[],samples=[],sampling_errors=[],transitions=[],comparative_result=False)
    stop=threading.Event();worker=None
    try:
        store=TaskStore(APP/'data/tasks.sqlite3');journal=OperationJournal(store.path)
        restore_resource_operations();validate_trial_preflight(store,journal)
        document['preparation']=prepare_unloaded_condition(12800)
        validate_trial_preflight(store,journal)
        queue.queue_restore()
        params=dict(prompt='A small red ceramic teapot on a plain wooden table, studio lighting',
                    width=512,height=512,steps=8,cfg=6.0)
        from engine.profile_admission import select_profile
        model=next(m for m in queue.REGISTRY['comfyui']['models'] if m['id']=='SDXL')
        for seed in (args.first_seed,args.first_seed+1):
            effective=queue._apply_params(queue._load_workflow(model['workflow']),{**params,'seed':seed})
            if select_profile(effective) is None: raise ValueError('exact SDXL Profile required')
        if select_profile(request) is None: raise ValueError('exact Ollama Profile required')
        def sample():
            while not stop.is_set():
                try: document['samples'].append(gpu_sample())
                except Exception as error: document['sampling_errors'].append(type(error).__name__)
                stop.wait(0.2)
        worker=threading.Thread(target=sample);worker.start();started=time.monotonic()
        for source,payload in [('comfyui',{**params,'seed':args.first_seed}),('ollama',request),('comfyui',{**params,'seed':args.first_seed+1})]:
            result=(queue.queue_enqueue('SDXL',payload) if source=='comfyui' else queue.queue_enqueue_ollama(payload))
            if not result.get('ok'): raise RuntimeError('durable acceptance failed: '+str(result))
            document['task_ids'].append(result['task']['id'])
        previous={};deadline=time.monotonic()+900
        while True:
            records=[store.get(tid) for tid in document['task_ids']]
            for record in records:
                if previous.get(record['id'])!=record['status']:
                    document['transitions'].append(dict(task_id=record['id'],source=record['intent'].get('source','comfyui'),
                        status=record['status'],monotonic_s=time.monotonic()))
                    previous[record['id']]=record['status']
            if any(record['status'] in ('failed','uncertain','canceled') for record in records):
                raise RuntimeError('mixed execution did not confirm all successful tasks')
            if (all(record['status']=='done' for record in records)
                    and get_coordinator().snapshot()['active'] is None and journal.pending()==[]):
                break
            if time.monotonic()>deadline: raise TimeoutError('observe same tasks; do not resubmit')
            stop.wait(0.25)
        document.update(status='success',duration_s=time.monotonic()-started)
    except Exception as error:
        document.update(status='failed',error=str(error));raise
    finally:
        stop.set()
        if worker is not None: worker.join(15)
        document['sampler_stopped']=worker is None or not worker.is_alive()
        document['tasks']=[store.get(tid) for tid in document['task_ids']]
        # Keep completion metrics/hash, but no generated LLM output text in public raw.
        for record in document['tasks']:
            result=record['checkpoint'].get('result')
            if record['intent'].get('source')=='ollama' and isinstance(result,dict):
                result.pop('response',None)
        document['coordination_after']=get_coordinator().snapshot()['active']
        document['coordination_events']=get_coordinator().snapshot()['events']
        with store._transaction() as connection:
            document['durable_events']=[dict(row) for tid in document['task_ids'] for row in connection.execute(
                'SELECT sequence,task_id,state,version,timestamp FROM task_events WHERE task_id=? ORDER BY sequence',(tid,))]
        document['pending_operations_after']=len(journal.pending())
        if document['samples']:
            document['observed_whole_device_peak_mb']=max(max(s['used_mb'],s['total_mb']-s['free_mb']) for s in document['samples'])
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('x',encoding='utf-8',newline='\n') as file: json.dump(redact(document),file,indent=2,allow_nan=False)
        print(json.dumps({k:document.get(k) for k in ('status','duration_s','observed_whole_device_peak_mb')}))


if __name__=='__main__': main()
