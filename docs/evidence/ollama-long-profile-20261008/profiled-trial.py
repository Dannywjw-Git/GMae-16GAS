"""Execute an exact installed Ollama Profile through ordinary measured admission."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
from measure_comfy_workload import APP, get_json, gpu_sample, prepare_unloaded_condition, validate_trial_preflight
from core.process_ownership import ProcessOwnership
from core.task_store import TaskStore
from core.operation_journal import OperationJournal
from core.ollama_profile import profile_from_evidence
from engine.coordinator import OperationSpec, coordinated_operation, restore_resource_operations, get_coordinator
from engine.profile_admission import select_profile


def redact(value):
    if isinstance(value,dict):
        return {(key+'_sha256' if key in ('token','reservation_token') else key):
                (hashlib.sha256(str(item).encode()).hexdigest() if key in ('token','reservation_token') else redact(item))
                for key,item in value.items()}
    if isinstance(value,list): return [redact(item) for item in value]
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',required=True)
    parser.add_argument('--profile-dir',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args();output=Path(args.output)
    if output.exists(): raise ValueError('refusing overwrite of evidence')
    raw=json.loads(Path(args.raw).read_bytes());request=raw['request']
    os.environ['GMAE_PROFILE_DIR']=str(Path(args.profile_dir).resolve())
    reference=select_profile(request)
    if reference is None: raise ValueError('exact installed Profile required')
    profile=profile_from_evidence(Path(args.raw).read_bytes(),reference['margin_mb'])
    if profile['evidence']['raw_data_sha256']!=reference['raw_sha256']:
        raise ValueError('provided evidence differs from installed evidence')
    owner=ProcessOwnership(APP/'data/tasks.sqlite3').acquire()
    document=dict(kind='real_ollama_profiled_trial',request=request,profile_reference=reference,
                  samples=[],sampling_errors=[])
    stop=threading.Event();worker=None
    try:
        store=TaskStore(APP/'data/tasks.sqlite3');journal=OperationJournal(store.path)
        restore_resource_operations();validate_trial_preflight(store,journal)
        document['preparation']=prepare_unloaded_condition(max(profile['peak_mb_samples'])+reference['margin_mb']+2560)
        validate_trial_preflight(store,journal)
        document['baseline']=gpu_sample()
        def sample():
            while not stop.is_set():
                try: document['samples'].append(gpu_sample())
                except Exception as error: document['sampling_errors'].append(type(error).__name__)
                stop.wait(0.2)
        worker=threading.Thread(target=sample);worker.start();started=time.monotonic()
        spec=OperationSpec('generate','ollama',request['model'],request['options']['num_ctx'],
                           owner='experiment:profiled-ollama',workflow=request,profile_reference=reference)
        with coordinated_operation(spec) as lease:
            document['admission']=get_coordinator().snapshot()['active']
            lease.transition('running')
            rpc=urllib.request.Request('http://127.0.0.1:11434/api/generate',
                data=json.dumps(request).encode(),headers={'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(rpc,timeout=300) as response: result=json.load(response)
            except Exception:
                lease.uncertain('profiled Ollama response unknown; do not replay');raise
            document['response_metrics']={key:result.get(key) for key in
                ('done','done_reason','prompt_eval_count','eval_count','total_duration','load_duration','prompt_eval_duration','eval_duration')}
            resident=get_json('http://127.0.0.1:11434/api/ps')['models']
            document['resident_after']=resident
            if (result.get('done') is not True or type(result.get('eval_count')) is not int
                    or result['eval_count']<=0 or len(resident)!=1
                    or resident[0].get('digest')!=raw['model_artifact']['digest']
                    or resident[0].get('context_length')!=request['options']['num_ctx']):
                lease.uncertain('generation/model/context completion unverified')
                raise ValueError('unverified completion')
            document['output_sha256']=hashlib.sha256(result.get('response','').encode()).hexdigest()
            lease.transition('completed')
        document.update(status='success',duration_s=time.monotonic()-started)
    except Exception as error:
        document.update(status='failed',error_type=type(error).__name__,error=str(error));raise
    finally:
        stop.set()
        if worker is not None: worker.join(15)
        document['sampler_stopped']=worker is None or not worker.is_alive()
        if document['samples']:
            document['observed_whole_device_peak_mb']=max(max(s['used_mb'],s['total_mb']-s['free_mb']) for s in document['samples'])
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('x',encoding='utf-8',newline='\n') as file:
            json.dump(redact(document),file,indent=2,allow_nan=False)
        print(json.dumps({key:document.get(key) for key in ('status','duration_s','observed_whole_device_peak_mb')}))


if __name__=='__main__': main()
