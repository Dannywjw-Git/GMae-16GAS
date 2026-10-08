"""Measured resident growth, distinct from the model's physical resident size."""
import json
import math
from core.residency import _validate_residency
from core.workload_profile import profile_from_evidence


def residency_key(snapshot):
    _validate_residency(snapshot, snapshot['request_id'])
    if not snapshot['residency_complete']:
        raise ValueError('complete idle unpatched residency required')
    fields = ('role', 'path_sha256', 'file_identity', 'model_bytes', 'resident_bytes')
    return dict(instance=snapshot['backend_instance_id'], epoch=snapshot['load_epoch'],
                observer=snapshot['observer_code_sha256'],
                components=[{key: component[key] for key in fields}
                    for component in sorted(snapshot['components'], key=lambda item: item['role'])])


def conservative_used(sample, total):
    if sample.get('total_mb') != total:
        raise ValueError('device capacity changed')
    if any(type(sample.get(key)) is not int or not 0 <= sample[key] <= total for key in ('used_mb', 'free_mb')):
        raise ValueError('invalid memory counters')
    return max(sample['used_mb'], total - sample['free_mb'])


def phase_profile_from_evidence(payload, margin_mb):
    cold = profile_from_evidence(payload, margin_mb)
    raw = json.loads(payload)
    if raw.get('trial_condition') != 'resident_memory_observed_model_identity_unproven':
        raise ValueError('explicit resident trial required')
    if raw['residency_after']['monotonic_ns'] <= raw['residency_before']['monotonic_ns']:
        raise ValueError('observer time must advance during calibration')
    before, after = residency_key(raw['residency_before']), residency_key(raw['residency_after'])
    if before != after:
        raise ValueError('residency changed during calibration')
    stamps = {tuple(c['file_identity']) for c in before['components']}
    paths = {c['path_sha256'] for c in before['components']}
    if len(stamps) != 1 or len(paths) != 1:
        raise ValueError('components have different source identities')
    total = raw['baseline']['total_mb']
    baseline = conservative_used(raw['baseline'], total)
    peak = max(conservative_used(sample, total) for sample in raw['samples'])
    return {**cold, 'memory_scope': 'measured_resident_increment', 'residency_key': before,
            'growth_mb': max(0, peak - baseline),
            'increment_mb': math.ceil(max(0, peak - baseline) + margin_mb),
            'resident_model_mb': math.ceil(sum(c['resident_bytes'] for c in before['components']) / 1024**2),
            'baseline_mb': baseline, 'conservative_peak_mb': peak,
            'limitations': ['single trial', 'sampling may miss peaks', 'same backend instance and source required',
                            'not an OOM guarantee; external clients are not isolated']}


def match_resident_phase(profile, snapshot, artifact_identity):
    """The host separately hashes the file; observation alone cannot prove content."""
    current, calibrated = residency_key(snapshot), profile['residency_key']
    if current['epoch'] < calibrated['epoch']:
        raise ValueError('observer epoch regressed')
    if {k:v for k,v in current.items() if k != 'epoch'} != {k:v for k,v in calibrated.items() if k != 'epoch'}:
        raise ValueError('fresh residency does not match calibrated state')
    if artifact_identity['model_digest'] != profile['environment']['model_digest']:
        raise ValueError('artifact digest mismatch')
    for component in profile['residency_key']['components']:
        if (component['file_identity'] != artifact_identity['file_identity'] or
                component['path_sha256'] != artifact_identity['path_sha256']):
            raise ValueError('host artifact metadata does not match loaded source')
    return dict(increment_mb=profile['increment_mb'], resident_model_mb=profile['resident_model_mb'],
                basis='verified_resident_growth_plus_margin', evidence_sha256=profile['evidence']['raw_data_sha256'],
                calibration_workflow_sha256=profile['workflow_sha256'])
