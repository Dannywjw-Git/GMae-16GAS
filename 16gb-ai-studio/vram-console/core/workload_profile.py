"""Exact workload evidence matching; no extrapolation or invented measurements."""
import hashlib
import json
import math


def workload_fingerprint(workflow):
    """Hash the actual backend payload, including model references and parameters."""
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError('workflow must be a nonempty object')
    payload = json.dumps(workflow, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def resource_configuration_fingerprint(workflow):
    """Conservative control identity for legacy estimates, not measured evidence.

    Text/seed/output names may vary; every other input and node identity remains
    bound. This does not assert identical memory use across different prompts.
    """
    normalized = json.loads(json.dumps(workflow, allow_nan=False))
    for node in normalized.values():
        if not isinstance(node, dict):
            raise ValueError('invalid workflow node')
        inputs = node.get('inputs', {})
        if not isinstance(inputs, dict):
            raise ValueError('invalid workflow inputs')
        for key in ('text', 'caption', 'seed', 'noise_seed', 'filename_prefix'):
            inputs.pop(key, None)
    return workload_fingerprint(normalized)


def match_profile(profile, workflow, environment):
    """Return a conservative measured envelope only for an exact evidence match.

    This function validates declared provenance; it cannot authenticate a GPU
    measurement. Evidence ingestion and raw-data review remain separate duties.
    Environment includes hardware, driver, backend and model artifact identities.
    """
    rejected = {'ok': False, 'code': 'PROFILE_UNVERIFIED'}
    if not isinstance(profile, dict) or profile.get('schema_version') != 1:
        return {**rejected, 'reason': 'unsupported profile schema'}
    if not isinstance(environment, dict) or not environment:
        return {**rejected, 'reason': 'missing execution environment'}
    required = ('gpu', 'driver', 'backend', 'model_digest')
    if any(not isinstance(environment.get(key), str) or not environment[key].strip()
           for key in required):
        return {**rejected, 'reason': 'incomplete execution environment'}
    if profile.get('environment') != environment:
        return {**rejected, 'reason': 'execution environment mismatch'}
    if profile.get('workflow_sha256') != workload_fingerprint(workflow):
        return {**rejected, 'reason': 'effective workflow mismatch'}
    evidence = profile.get('evidence')
    if not isinstance(evidence, dict) or evidence.get('kind') != 'real_gpu':
        return {**rejected, 'reason': 'real GPU evidence required'}
    if any(not isinstance(evidence.get(key), str) or not evidence[key].strip()
           for key in ('raw_data_sha256', 'recorded_at')):
        return {**rejected, 'reason': 'missing evidence provenance'}
    digest = evidence['raw_data_sha256']
    if len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest):
        return {**rejected, 'reason': 'invalid evidence digest'}
    samples = profile.get('peak_mb_samples')
    if not isinstance(samples, list) or not samples:
        return {**rejected, 'reason': 'missing peak samples'}
    margin = profile.get('margin_mb')
    values = samples + [margin]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in values):
        return {**rejected, 'reason': 'invalid memory values'}
    if min(samples) <= 0 or margin < 0:
        return {**rejected, 'reason': 'invalid memory range'}
    return {'ok': True, 'peak_mb': math.ceil(max(samples) + margin),
            'basis': 'exact_workflow_measured_envelope', 'sample_count': len(samples),
            'workflow_sha256': profile['workflow_sha256'],
            'evidence_sha256': digest, 'margin_mb': margin,
            'limitation': 'observed peaks plus margin are not an OOM guarantee'}


def profile_from_evidence(raw_bytes, margin_mb):
    """Build a conservative whole-device envelope from one complete raw trial.

    Raw sample consistency is checked; provenance authenticity still requires
    review of the capture process. Whole-device peaks deliberately include noise.
    """
    if not isinstance(raw_bytes, bytes):
        raise ValueError('raw evidence must be bytes')
    raw = json.loads(raw_bytes)
    if (raw.get('kind') != 'real_gpu_baseline' or raw.get('terminal_status') != 'success'
            or raw.get('sampler_cache_hit') is not False or raw.get('sampling_errors') != []):
        raise ValueError('successful uncached trial without sampling errors required')
    workflow = raw['workflow']
    if workload_fingerprint(workflow) != raw.get('workflow_sha256'):
        raise ValueError('workflow digest mismatch')
    if (not isinstance(raw.get('model_artifact'), dict) or
            not isinstance(raw.get('backend_environment'), dict) or
            not raw['backend_environment'].get('launch_args_sha256')):
        raise ValueError('complete model and launch identities required')
    gpu = raw['gpu_identity']
    model_digest = raw['model_artifact']['sha256']
    launch_digest = raw['backend_environment']['launch_args_sha256']
    for digest in (model_digest, launch_digest, gpu['uuid_sha256']):
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('complete artifact/environment identity required')
    samples = raw['samples']
    if not isinstance(samples, list) or len(samples) < 2:
        raise ValueError('multiple samples required')
    previous = -math.inf
    total = raw['baseline']['total_mb']
    if type(total) is not int or total <= 0:
        raise ValueError('invalid device capacity')
    for sample in samples:
        timestamp = sample['monotonic_s']
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp) or timestamp <= previous):
            raise ValueError('sample timestamps must be strictly increasing')
        previous = timestamp
        if sample['total_mb'] != total or type(sample['used_mb']) is not int or not 0 <= sample['used_mb'] <= total:
            raise ValueError('invalid memory samples')
    peak = max(sample['used_mb'] for sample in samples)
    if peak != raw.get('observed_device_peak_mb'):
        raise ValueError('declared peak differs from raw samples')
    system = raw['backend_environment']['system']
    backend = {key: system[key] for key in ('comfyui_version', 'python_version', 'pytorch_version')}
    backend['launch_args_sha256'] = launch_digest
    environment = dict(gpu=gpu['name'] + ':' + gpu['uuid_sha256'] + ':' + str(total),
                       driver=gpu['driver'], model_digest=model_digest,
                       backend=workload_fingerprint({'backend': backend}))
    profile = dict(schema_version=1, environment=environment,
        workflow_sha256=raw['workflow_sha256'], peak_mb_samples=[peak], margin_mb=margin_mb,
        evidence=dict(kind='real_gpu', raw_data_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                      recorded_at=raw['recorded_at']),
        memory_scope='sampled_whole_device_upper_envelope',
        limitations=['single trial', 'sampling may miss peaks', 'includes background memory'])
    if not match_profile(profile, workflow, environment)['ok']:
        raise ValueError('invalid profile envelope')
    return profile
