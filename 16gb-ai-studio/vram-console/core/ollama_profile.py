"""Pure validation of exact Ollama requests and content-bound evidence."""
import hashlib
import json
import math
from core.workload_profile import workload_fingerprint, match_profile


def analyze(raw):
    if (raw.get('kind') != 'real_ollama_calibration' or raw.get('status') != 'success'
            or raw.get('sampler_stopped') is not True or raw.get('sampling_errors') != []):
        raise ValueError('incomplete calibration')
    request = raw['request']
    ctx = request['options']['num_ctx']
    if (type(ctx) is not int or ctx not in (2048, 8192) or request.get('think') is not False
            or request.get('model') != 'qwen3.5:9b' or request.get('stream') is not False
            or request['options'].get('num_predict') != 32):
        raise ValueError('unsupported request')
    residents = raw['resident_after']
    if (len(residents) != 1 or residents[0]['context_length'] != ctx
            or residents[0]['digest'] != raw['model_artifact']['digest']):
        raise ValueError('model/context mismatch')
    metrics = raw['response_metrics']
    if (metrics.get('done') is not True or type(metrics.get('eval_count')) is not int
            or not 0<metrics['eval_count']<=32):
        raise ValueError('incomplete controlled output')
    samples = raw['samples']
    previous = raw['baseline']['monotonic_s']
    peaks = []
    for sample in samples:
        values = [sample[k] for k in ('monotonic_s', 'total_mb', 'used_mb', 'free_mb')]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
            raise ValueError('invalid measurement')
        if values[0] <= previous or sample['total_mb'] != raw['baseline']['total_mb']:
            raise ValueError('nonmonotonic or inconsistent sample')
        if max(sample['used_mb'], sample['free_mb']) > sample['total_mb']:
            raise ValueError('invalid capacity')
        previous = values[0]
        peaks.append(max(sample['used_mb'], sample['total_mb'] - sample['free_mb']))
    if not peaks or max(peaks) != raw['observed_whole_device_peak_mb']:
        raise ValueError('peak mismatch')
    if type(raw.get('duration_s')) not in (int,float) or not math.isfinite(raw['duration_s']) or raw['duration_s']<=0:
        raise ValueError('invalid duration')
    return dict(context_length=ctx, prompt_tokens=metrics['prompt_eval_count'],
                output_tokens=metrics['eval_count'], samples=len(samples),
                whole_device_peak_mb=max(peaks), resident_vram_bytes=residents[0]['size_vram'],
                duration_s=raw['duration_s'], production_profile=False,
                limitation=('long synthetic prompt; not full-context or worst-case peak' if raw.get('prompt_kind')=='long' else 'short prompt only; not full-context or worst-case peak'))


def environment_from_identity(gpu, total_mb, artifact, version, manifest_digest):
    required=('container_id','blob_sha256','blob_stat','blob_path_sha256','model_configuration_sha256')
    if any(not isinstance(artifact.get(k),str) or not artifact[k] for k in required):
        raise ValueError('incomplete content identity')
    for digest in (artifact['blob_sha256'],artifact['blob_path_sha256'],
                   artifact['model_configuration_sha256'],manifest_digest,gpu['uuid_sha256']):
        if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid identity digest')
    return dict(gpu=gpu['name']+':'+gpu['uuid_sha256']+':'+str(total_mb),
                driver=gpu['driver'],model_digest=artifact['blob_sha256'],
                backend=workload_fingerprint(dict(artifact=artifact,version=version,
                                                  manifest_digest=manifest_digest)))


def profile_from_evidence(raw_bytes,margin_mb):
    raw=json.loads(raw_bytes);summary=analyze(raw)
    if raw['gpu_identity']!=raw['gpu_identity_after']:
        raise ValueError('GPU changed')
    if (type(margin_mb) is not int or margin_mb<0 or type(summary['prompt_tokens']) is not int
            or not 0<summary['prompt_tokens']<=summary['context_length']):
        raise ValueError('invalid margin or token count')
    if raw['container_backend_version']!='ollama version is '+raw['backend_version']:
        raise ValueError('backend version mismatch')
    preparation=raw['preparation']
    last=preparation['readings'][-1]
    if (preparation['condition']!='model_unloaded_low_torch_verified'
            or preparation['managed_release'].get('ok') is not True
            or last['torch_resident_bytes']>64*1024**2):
        raise ValueError('unloaded baseline not verified')
    environment=environment_from_identity(raw['gpu_identity'],raw['baseline']['total_mb'],
        raw['artifact_identity'],raw['backend_version'],raw['model_artifact']['digest'])
    digest=workload_fingerprint(raw['request'])
    profile=dict(schema_version=1,environment=environment,match_policy='exact',
        workflow_sha256=digest,execution_configuration_sha256=digest,
        peak_mb_samples=[summary['whole_device_peak_mb']],margin_mb=margin_mb,
        evidence=dict(kind='real_gpu',raw_data_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                      recorded_at=raw['recorded_at']),memory_scope='sampled_whole_device_upper_envelope',
        limitations=['single trial','exact prompt and all request parameters only',
                     'sampling may miss peaks','includes background memory',summary['limitation']])
    if not match_profile(profile,raw['request'],environment)['ok']:
        raise ValueError('invalid envelope')
    return profile


def analyze_profiled(raw,calibration_bytes):
    """Verify ordinary measured admission against the referenced public raw."""
    if raw.get('kind')!='real_ollama_profiled_trial':
        raise ValueError('wrong trial kind')
    reference=raw['profile_reference'];profile=profile_from_evidence(calibration_bytes,reference['margin_mb'])
    request=raw['request'];digest=workload_fingerprint(request)
    if (reference['raw_sha256']!=profile['evidence']['raw_data_sha256']
            or reference['workflow_sha256']!=digest or reference['profile_key']!=digest):
        raise ValueError('trial reference mismatch')
    expected=match_profile(profile,request,profile['environment'])
    admission=raw['admission'];measured=admission['budget']['measured_profile']
    if (not expected['ok'] or admission['service']!='ollama' or admission['operation']!='generate'
            or admission['model']!=request['model'] or admission['peak_mb']!=expected['peak_mb']
            or measured['peak_mb']!=expected['peak_mb']
            or measured['evidence_sha256']!=reference['raw_sha256']
            or measured['profile_status']!='raw_evidence_and_live_identity_verified'
            or measured['match_policy']!='exact'):
        raise ValueError('ordinary measured admission not verified')
    calibration=json.loads(calibration_bytes)
    combined={**calibration,**{key:raw[key] for key in ('request','baseline','samples','sampling_errors',
        'sampler_stopped','status','resident_after','response_metrics','duration_s','observed_whole_device_peak_mb')}}
    summary=analyze(combined)
    return {**summary,'admission_peak_mb':expected['peak_mb'],'production_profile':True,
            'limitation':'exact request admission only; not arbitrary conversation or full-context safety'}


