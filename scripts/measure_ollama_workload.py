"""Explicit isolated Ollama calibration; planning estimates are not production evidence."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
from measure_comfy_workload import (APP,get_json,gpu_sample,prepare_unloaded_condition,validate_trial_preflight)
from core.process_ownership import ProcessOwnership
from core.task_store import TaskStore
from core.operation_journal import OperationJournal
from engine import coordinator,budget
from core.config import REGISTRY

MODEL='qwen3.5:9b'
PROMPT='In one short sentence, explain why GPU memory scheduling matters.'


def request_for(ctx):
    if type(ctx) is not int or ctx not in (2048,8192):
        raise ValueError('controlled calibration supports 2048 or 8192 context only')
    return dict(model=MODEL,prompt=PROMPT,think=False,stream=False,keep_alive='30m',
                options=dict(num_ctx=ctx,num_predict=32,temperature=0,seed=20261008))


def planning_registry(ctx,size):
    request_for(ctx)
    if type(size) is not int or not 5*1024**3<size<8*1024**3:
        raise ValueError('installed artifact size outside reviewed planning range')
    peak_mb=math.ceil(size*1.2/1024**2)+2560
    config=deepcopy(REGISTRY)
    model=next(m for m in config['ollama']['models'] if m['id']==MODEL)
    model.update(vram_gb=peak_mb/1024,ctx=ctx,default_ctx=ctx,vram_verified=False,
                 context_vram={str(ctx):peak_mb/1024})
    return config,peak_mb


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ctx',type=int,required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args();body=request_for(args.ctx);output=Path(args.output)
    if output.exists(): raise ValueError('refusing overwrite of evidence')
    document=dict(kind='real_ollama_calibration',recorded_at=datetime.now(timezone.utc).isoformat(),
                  request=body,reserve_mb=2560,production_profile_installed=False,samples=[],sampling_errors=[])
    stop=threading.Event();worker=None
    owner=ProcessOwnership(APP/'data/tasks.sqlite3').acquire()
    previous=(coordinator.REGISTRY,budget.REGISTRY)
    try:
        store=TaskStore(APP/'data/tasks.sqlite3');journal=OperationJournal(store.path)
        validate_trial_preflight(store,journal);coordinator.restore_resource_operations()
        tags=get_json('http://127.0.0.1:11434/api/tags')['models']
        model=next(m for m in tags if m['name']==MODEL)
        config,peak_mb=planning_registry(args.ctx,model['size'])
        document['model_artifact']={k:model[k] for k in ('name','size','digest')}
        document['backend_version']=get_json('http://127.0.0.1:11434/api/version')['version']
        document['planning_peak_mb']=peak_mb
        document['planning_basis']='file_size_times_1.2_plus_2560MiB_unverified'
        document['preparation']=prepare_unloaded_condition(peak_mb+2560)
        validate_trial_preflight(store,journal)
        document['baseline']=gpu_sample()
        coordinator.REGISTRY=budget.REGISTRY=config
        def sample():
            while not stop.is_set():
                try: document['samples'].append(gpu_sample())
                except Exception as error: document['sampling_errors'].append(type(error).__name__)
                stop.wait(0.2)
        worker=threading.Thread(target=sample);worker.start();started=time.monotonic()
        spec=coordinator.OperationSpec('generate','ollama',MODEL,args.ctx,owner='experiment:ollama-calibration')
        with coordinator.coordinated_operation(spec) as lease:
            lease.transition('running')
            req=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(req,timeout=300) as response: result=json.load(response)
            except Exception:
                lease.uncertain('Ollama calibration response unknown; do not replay')
                raise
            if (result.get('done') is not True or type(result.get('eval_count')) is not int or result['eval_count']<=0):
                lease.uncertain('Ollama response cannot confirm completed generation')
                raise ValueError('invalid generation completion')
            document['response_metrics']={k:result.get(k) for k in ('done','done_reason','total_duration','load_duration','prompt_eval_count','prompt_eval_duration','eval_count','eval_duration')}
            document['output_sha256']=hashlib.sha256(result.get('response','').encode()).hexdigest()
            document['resident_after']=get_json('http://127.0.0.1:11434/api/ps')['models']
            if (len(document['resident_after'])!=1 or document['resident_after'][0].get('digest')!=model['digest'] or
                    document['resident_after'][0].get('context_length')!=args.ctx):
                lease.uncertain('resident model/context identity unverified')
                raise ValueError('actual model/context not verified')
            lease.transition('completed')
        document['duration_s']=time.monotonic()-started
        document['status']='success'
    except Exception as error:
        document.update(status='failed',error_type=type(error).__name__,error=str(error))
        raise
    finally:
        stop.set()
        if worker is not None: worker.join(timeout=15)
        document['sampler_stopped']=worker is None or not worker.is_alive()
        coordinator.REGISTRY,budget.REGISTRY=previous
        if document['samples']:
            document['observed_whole_device_peak_mb']=max(max(s['used_mb'],s['total_mb']-s['free_mb']) for s in document['samples'])
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('x',encoding='utf-8',newline='\n') as file: json.dump(document,file,indent=2,ensure_ascii=False)
        print(json.dumps({k:document.get(k) for k in ('status','duration_s','observed_whole_device_peak_mb')}))
        # Keep process ownership until exit; an unknown operation remains durable.


if __name__=='__main__': main()
