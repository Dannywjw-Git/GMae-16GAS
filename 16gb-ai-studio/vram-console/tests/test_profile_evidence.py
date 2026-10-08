"""Synthetic evidence fixtures validate ingestion, not GPU performance."""
import hashlib
import json
import pytest
from core.workload_profile import profile_from_evidence, workload_fingerprint


@pytest.fixture
def raw():
    workflow = {'1': {'inputs': {'width': 512}}}
    return dict(kind='real_gpu_baseline', terminal_status='success', sampler_cache_hit=False,
        sampling_errors=[], workflow=workflow, workflow_sha256=workload_fingerprint(workflow),
        gpu_identity=dict(name='synthetic', uuid_sha256='a' * 64, driver='test'),
        model_artifact=dict(sha256='b' * 64),
        backend_environment=dict(launch_args_sha256='c' * 64,
            system=dict(comfyui_version='test', python_version='test', pytorch_version='test')),
        baseline=dict(total_mb=16000), observed_device_peak_mb=9000,
        recorded_at='synthetic-test-only', samples=[dict(monotonic_s=1, total_mb=16000, used_mb=8000),
                                                   dict(monotonic_s=2, total_mb=16000, used_mb=9000)])


def encode(raw):
    return json.dumps(raw).encode()


def test_profile_binds_raw_bytes_and_peak(raw):
    payload = encode(raw)
    profile = profile_from_evidence(payload, 512)
    assert profile['peak_mb_samples'] == [9000]
    assert profile['evidence']['raw_data_sha256'] == hashlib.sha256(payload).hexdigest()
    assert profile['memory_scope'] == 'sampled_whole_device_upper_envelope'


@pytest.mark.parametrize('key,value', [('sampler_cache_hit', True), ('terminal_status', 'error'),
    ('sampling_errors', ['failure']), ('observed_device_peak_mb', 8000),
    ('workflow_sha256', 'd' * 64), ('samples', [])])
def test_incomplete_or_inconsistent_evidence_rejected(raw, key, value):
    raw[key] = value
    with pytest.raises(ValueError):
        profile_from_evidence(encode(raw), 512)


def test_missing_artifact_identity_rejected(raw):
    del raw['model_artifact']
    with pytest.raises(ValueError):
        profile_from_evidence(encode(raw), 512)


def test_time_and_memory_corruption_rejected(raw):
    raw['samples'][1]['monotonic_s'] = 1
    with pytest.raises(ValueError):
        profile_from_evidence(encode(raw), 512)
    raw['samples'][1]['monotonic_s'] = 2
    raw['samples'][1]['used_mb'] = 99999
    with pytest.raises(ValueError):
        profile_from_evidence(encode(raw), 512)
