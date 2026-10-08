"""Validate a real controller loss, unknown hold, exact receipt and recovery chain."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def analyze(raw):
    if (raw.get('kind')!='real_ollama_controller_crash_trial' or raw.get('status')!='success'
            or type(raw.get('controller_exit_code')) is not int or raw['controller_exit_code']==0
            or raw.get('gpu_ownership_reacquired') is not True
            or raw.get('sampler_stopped') is not True or raw.get('sampling_errors')!=[]
            or raw.get('coordination_after') is not None or raw.get('pending_operations_after')!=0):
        raise ValueError('incomplete real crash recovery')
    before=raw['before_crash'];restored=raw['after_restore'];task=raw['task_after']
    if (before['task_status']!='submitting' or before['command_state']!='inflight'
            or before['durable_response_present'] is not False or before['gpu']['used_mb']<4096
            or restored['task_status']!='uncertain' or restored['active']['phase']!='uncertain'
            or restored['active']['service']!='ollama' or restored['active']['job_id']!=before['task_id']
            or raw['initial_reconcile'].get('code')!='UNCONFIRMED_EXECUTION'):
        raise ValueError('fault or unknown hold not proven')
    if (task['id']!=before['task_id'] or task['status']!='done'
            or raw['reconcile'].get('resolved') is not True or raw['reconcile'].get('job_id')!=task['id']
            or raw['reconcile'].get('command_id')!=before['command_id']
            or raw['operation_after']['state']!='confirmed'):
        raise ValueError('recovery task/command mismatch')
    commands=raw['commands_after']
    if (len(commands)!=1 or commands[0]['id']!=before['command_id']
            or commands[0]['state']!='confirmed' or commands[0]['return_code']!=0
            or commands[0]['intent_sha256']!=before['command_intent_sha256']):
        raise ValueError('exact single delegated receipt not proven')
    metrics=task['checkpoint']['backend_completion']['metrics']
    intent=task['intent'];request=intent['effective_workflow']
    digest=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if (intent.get('source')!='ollama' or intent['workflow_sha256']!=digest
            or intent['profile_reference']['workflow_sha256']!=digest
            or not task['checkpoint']['backend_completion']['model']==intent['model']==request['model']):
        raise ValueError('fixed request or model identity mismatch')
    if metrics.get('done') is not True or type(metrics.get('eval_count')) is not int or metrics['eval_count']<=0:
        raise ValueError('full backend completion unverified')
    previous=-1;total=None;peaks=[]
    for sample in raw['samples']:
        values=[sample[k] for k in ('monotonic_s','total_mb','used_mb','free_mb')]
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):
            raise ValueError('invalid GPU sample')
        if values[0]<=previous or (total is not None and total!=values[1]) or max(values[2:])>values[1]:
            raise ValueError('inconsistent GPU sample')
        previous,total=values[:2];peaks.append(max(values[2],total-values[3]))
    if not peaks or max(peaks)!=raw['observed_whole_device_peak_mb']:
        raise ValueError('peak mismatch')
    return dict(controller_exit_code=raw['controller_exit_code'],gpu_at_fault_mb=before['gpu']['used_mb'],
        observed_whole_device_peak_mb=max(peaks),samples=len(peaks),input_tokens=metrics['prompt_eval_count'],
        output_tokens=metrics['eval_count'],delegated_command_count=1,unknown_hold_verified=True,
        recovered_without_replay=True,limitation='one controller crash; worker/host loss and immediate cancellation unverified')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('raw')
    args=parser.parse_args();print(json.dumps(analyze(json.loads(Path(args.raw).read_bytes())),indent=2))
