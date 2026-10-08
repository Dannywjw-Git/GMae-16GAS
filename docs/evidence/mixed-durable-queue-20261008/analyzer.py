"""Review raw sequential task, admission, release and physical evidence."""
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'16gb-ai-studio/vram-console'))
from core.workload_profile import workload_fingerprint


def analyze(raw,require_trace=True):
    if (raw.get('kind')!='real_mixed_durable_queue_trial' or raw.get('status')!='success'
            or raw.get('sampler_stopped') is not True or raw.get('sampling_errors')!=[]
            or raw.get('coordination_after') is not None or raw.get('pending_operations_after')!=0):
        raise ValueError('incomplete or unconfirmed trial')
    tasks=raw['tasks'];ids=raw['task_ids']
    if len(tasks)!=3 or len(set(ids))!=3 or [t['id'] for t in tasks]!=ids:
        raise ValueError('wrong task sequence')
    if [t['intent'].get('source','comfyui') for t in tasks]!=['comfyui','ollama','comfyui']:
        raise ValueError('wrong backend order')
    rows=[];previous_end=0
    for task in tasks:
        intent=task['intent'];checkpoint=task['checkpoint'];budget=checkpoint['budget']
        if (task['status']!='done' or workload_fingerprint(intent['effective_workflow'])!=intent['workflow_sha256']
                or checkpoint['started']<previous_end or checkpoint['ended']<checkpoint['started']
                or budget['profile_status']!='raw_evidence_and_live_identity_verified'
                or budget['measured_profile']['evidence_sha256']!=intent['profile_reference']['raw_sha256']):
            raise ValueError('task completion/order/evidence mismatch')
        previous_end=checkpoint['ended']
        rows.append(dict(source=intent.get('source','comfyui'),model=intent['model'],
                         post_admission_task_s=checkpoint['ended']-checkpoint['started'],
                         measured_budget_mb=budget['measured_profile']['peak_mb']))
    samples=raw['samples'];previous=-1;total=None;peaks=[];free=[]
    for sample in samples:
        values=[sample[k] for k in ('monotonic_s','total_mb','used_mb','free_mb')]
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):
            raise ValueError('invalid sample')
        if values[0]<=previous or (total is not None and values[1]!=total) or max(values[2:])>values[1]:
            raise ValueError('inconsistent sample')
        previous,total=values[:2];peaks.append(max(values[2],total-values[3]));free.append(values[3])
    if not peaks or max(peaks)!=raw['observed_whole_device_peak_mb'] or min(free)<2560:
        raise ValueError('peak or observed reserve mismatch')
    if type(raw.get('duration_s')) not in (int,float) or not math.isfinite(raw['duration_s']) or raw['duration_s']<=0:
        raise ValueError('invalid duration')
    verified_releases=0
    if require_trace:
        events=raw['coordination_events'];durable=raw['durable_events']
        if any(b['sequence']<=a['sequence'] or b['monotonic_s']<a['monotonic_s'] for a,b in zip(events,events[1:])):
            raise ValueError('nonmonotonic coordination trace')
        for task in tasks:
            states=[e['state'] for e in sorted(durable,key=lambda e:e['sequence']) if e['task_id']==task['id']]
            if any(state not in states for state in ('queued','precheck','submitting','running','done')):
                raise ValueError('missing durable boundary')
            indices=[states.index(state) for state in ('queued','precheck','submitting','running','done')]
            if indices!=sorted(indices): raise ValueError('wrong durable state order')
            owner='job:'+task['id']
            owned=[e for e in events if e.get('owner')==owner]
            acquisitions=[e for e in owned if e['event']=='acquired' and e.get('operation')=='generate']
            if (len(acquisitions)!=1 or acquisitions[0].get('service')!=task['intent'].get('source','comfyui')
                    or acquisitions[0].get('model')!=task['intent']['model']):
                raise ValueError('wrong owned acquisition')
            if not any(e['event']=='released' for e in owned): raise ValueError('ownership not released')
            admissions=[e['details'] for e in owned if e['event']=='transition'
                        and e.get('phase')=='reserved' and 'telemetry' in e.get('details',{})]
            if not admissions: raise ValueError('missing final physical admission')
            # Nested managed releases borrow this owner's capability and emit
            # their own telemetry; the final gate follows all release gates.
            admission=admissions[-1]
            if admission['telemetry']['free_mb']<rows[ids.index(task['id'])]['measured_budget_mb']+2560:
                raise ValueError('physical capacity not verified')
            if task['id']!=ids[0]:
                releases=[e['details']['release_evidence'] for e in owned if e['event']=='transition'
                    and 'release_evidence' in e.get('details',{})]
                if len(releases)!=1 or releases[0].get('ok') is not True or any(a['rc']!=0 for a in releases[0]['actions']):
                    raise ValueError('switch release not verified')
                verified_releases+=1
    return dict(tasks=rows,observed_whole_device_peak_mb=max(peaks),minimum_observed_free_mb=min(free),
                samples=len(samples),duration_s=raw['duration_s'],verified_switch_releases=verified_releases,
                trace_verified=require_trace,comparative_result=False,
                limitation='single sequential workload; no throughput baseline or OOM guarantee')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw');parser.add_argument('--pilot',action='store_true')
    args=parser.parse_args()
    print(json.dumps(analyze(json.loads(Path(args.raw).read_bytes()),not args.pilot),indent=2))
