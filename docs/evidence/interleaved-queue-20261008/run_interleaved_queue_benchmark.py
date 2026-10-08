"""Predeclared balanced-order formal queue trials under one process ownership."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from run_profiled_queue_trial import APP, ProcessOwnership, run_trial

ORDER = ('conservative', 'resident', 'resident', 'conservative',
         'conservative', 'resident', 'resident', 'conservative')


def eligible(document, mode):
    if (document.get('task_status') != 'done' or document.get('backend_terminal') != 'success' or
            document.get('sampler_cache_hit') is not False or document.get('sampling_errors') != [] or
            document.get('coordination', {}).get('active') is not None):
        raise ValueError('trial not successful, uncached and confirmed idle')
    before=document['residency_before']
    if not before.get('ok') or before.get('residency_complete') is not True:
        raise ValueError('equal fully resident starting condition required')
    scope=document['budget']['measured_profile']['memory_scope']
    expected='measured_resident_increment' if mode=='resident' else 'sampled_whole_device_upper_envelope'
    if scope!=expected:
        raise ValueError('actual admission path differs from assigned strategy')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--trials-directory',required=True)
    parser.add_argument('--conservative-profile',required=True)
    parser.add_argument('--resident-profile',required=True)
    parser.add_argument('--first-seed',type=int,default=57)
    args=parser.parse_args()
    output=Path(args.output)
    if output.exists() or args.first_seed<0:
        raise ValueError('invalid output or seed')
    root=Path(args.trials_directory)
    root.mkdir(parents=True,exist_ok=False)
    profiles={mode: str(Path(getattr(args,mode+'_profile')).resolve()) for mode in ('conservative','resident')}
    document=dict(kind='interleaved_formal_queue_benchmark',recorded_at=datetime.now(timezone.utc).isoformat(),
                  plan=list(ORDER),warmup_excluded=True,randomized=False,rows=[],status='running',
                  limitations=['single GPU and one configuration','background and CPU/disk caches uncontrolled',
                               'same process identity cache; initial verification retained in warmup'])
    owner=ProcessOwnership(APP/'data/tasks.sqlite3').acquire()
    try:
        for index,mode in enumerate(('resident',)+ORDER):
            seed=args.first_seed+index
            path=root/('%02d-%s-seed%d.json'%(index,mode,seed))
            os.environ['GMAE_PROFILE_DIR']=profiles[mode]
            row=dict(index=index,mode=mode,seed=seed,warmup=index==0,raw_file=path.name)
            document['rows'].append(row)
            try:
                trial=run_trial(seed,path,300,owner)
            finally:
                if path.exists(): row['raw_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            eligible(trial,mode)
            print(json.dumps(dict(index=index,mode=mode,duration_s=trial['duration_s'],unloads=trial['managed_unload_calls'])),flush=True)
        document['status']='success'
    except Exception as error:
        document.update(status='failed',error_type=type(error).__name__,error=str(error))
        raise
    finally:
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('x',encoding='utf-8',newline='\n') as file:
            json.dump(document,file,ensure_ascii=False,indent=2)
        # On unknown work, retain ownership through process exit; never replay.


if __name__=='__main__': main()
