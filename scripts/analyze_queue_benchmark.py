"""Validate every raw row before describing one configured GPU strategy experiment."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from run_interleaved_queue_benchmark import ORDER, eligible
from core.workload_profile import execution_configuration_fingerprint, workload_fingerprint
from core.phase_profile import residency_key


def analyze(manifest, payloads):
    if (manifest.get('kind')!='interleaved_formal_queue_benchmark' or manifest.get('status')!='success' or
            manifest.get('plan')!=list(ORDER) or manifest.get('warmup_excluded') is not True):
        raise ValueError('complete predeclared successful benchmark required')
    rows=manifest['rows']
    if len(rows)!=len(ORDER)+1 or len(payloads)!=len(rows):
        raise ValueError('all trials including warmup required')
    identities=set();seeds=set();groups={'resident':[],'conservative':[]};trials=[]
    cold_sources=set();warmup=None;states=set();capacities=set();last_trial_time=-math.inf
    for index,(row,payload) in enumerate(zip(rows,payloads)):
        if hashlib.sha256(payload).hexdigest()!=row['raw_sha256']:
            raise ValueError('raw digest mismatch')
        raw=json.loads(payload)
        mode='resident' if index==0 else ORDER[index-1]
        if row['index']!=index or row['mode']!=mode or row['warmup']!=(index==0):
            raise ValueError('trial order or warmup mismatch')
        eligible(raw,mode)
        state=residency_key(raw['residency_before']);state.pop('epoch')
        states.add(json.dumps(state,sort_keys=True))
        if row['seed'] in seeds or raw['effective_workflow']['5']['inputs']['seed']!=row['seed']:
            raise ValueError('seeds must be distinct and bound to actual workflow')
        seeds.add(row['seed'])
        if workload_fingerprint(raw['effective_workflow'])!=raw['workflow_sha256']:
            raise ValueError('actual workflow digest mismatch')
        identities.add(execution_configuration_fingerprint(raw['effective_workflow']))
        cold_sources.add(raw['profile_reference']['raw_sha256'])
        duration=raw['duration_s']
        if type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0:
            raise ValueError('invalid duration')
        samples=raw['samples'];total=raw['baseline']['total_mb'];previous=-math.inf
        capacities.add(total)
        if samples and samples[0]['monotonic_s']<=last_trial_time:
            raise ValueError('trial sample windows overlap or are out of order')
        if len(samples)<2 or type(total) is not int or total<=0:
            raise ValueError('multiple valid samples required')
        for sample in samples:
            stamp=sample['monotonic_s']
            if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<=previous:
                raise ValueError('sample times must advance')
            previous=stamp
            if (sample['total_mb']!=total or any(type(sample.get(key)) is not int or not 0<=sample[key]<=total for key in ('used_mb','free_mb'))):
                raise ValueError('invalid device counters')
        last_trial_time=samples[-1]['monotonic_s']
        if max(s['used_mb'] for s in samples)!=raw['observed_device_peak_mb']:
            raise ValueError('declared peak mismatch')
        peak=max(max(s['used_mb'],s['total_mb']-s['free_mb']) for s in samples)
        calls=raw['managed_unload_calls']
        if type(calls) is not int or calls<0: raise ValueError('invalid unload count')
        trial=dict(index=index,seed=row['seed'],mode=mode,duration_s=duration,unloads=calls,
                   conservative_peak_mb=peak,sample_count=len(samples),raw_sha256=row['raw_sha256'])
        trials.append(trial)
        if index==0: warmup=trial
        else: groups[mode].append(trial)
    if len(identities)!=1 or len(cold_sources)!=1 or len(states)!=1 or len(capacities)!=1:
        raise ValueError('configuration and cold source must match across strategies')
    summaries={mode:dict(trials=len(items),successes=len(items),median_s=statistics.median(x['duration_s'] for x in items),
        min_s=min(x['duration_s'] for x in items),max_s=max(x['duration_s'] for x in items),
        total_unloads=sum(x['unloads'] for x in items),observed_peak_mb=max(x['conservative_peak_mb'] for x in items)) for mode,items in groups.items()}
    return dict(configuration_sha256=identities.pop(),cold_source_sha256=cold_sources.pop(),warmup=warmup,
                trials=trials,summaries=summaries,generalized_performance_claim=False,
                note='descriptive result for one GPU/configuration; background and caches uncontrolled')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--trials-directory',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args();manifest=json.loads(Path(args.manifest).read_bytes());root=Path(args.trials_directory)
    payloads=[]
    for row in manifest['rows']:
        name=row['raw_file']
        if Path(name).name!=name or '/' in name or '\\' in name: raise ValueError('unsafe raw filename')
        payloads.append((root/name).read_bytes())
    result=analyze(manifest,payloads)
    with Path(args.output).open('x',encoding='utf-8',newline='\n') as file: json.dump(result,file,indent=2)
    print(json.dumps(result['summaries']))


if __name__=='__main__': main()
