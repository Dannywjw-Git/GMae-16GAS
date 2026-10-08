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
