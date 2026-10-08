"""Synthetic fixtures exercise matching logic, never performance evidence."""
import copy
import pytest
from core.workload_profile import workload_fingerprint, match_profile


@pytest.fixture
def inputs():
    workflow = {'1': {'class_type': 'EmptyLatentImage',
                      'inputs': {'width': 512, 'height': 512, 'batch_size': 1}}}
    environment = dict(gpu='test-gpu', driver='test-driver', backend='test-backend',
                       model_digest='test-model')
    profile = dict(schema_version=1, environment=environment.copy(),
                   workflow_sha256=workload_fingerprint(workflow),
                   evidence=dict(kind='real_gpu', raw_data_sha256='a' * 64,
                                 recorded_at='synthetic-test-only'),
                   peak_mb_samples=[1000, 1100.1], margin_mb=100)
    return workflow, environment, profile


def test_matching_envelope(inputs):
    workflow, environment, profile = inputs
    original = copy.deepcopy(profile)
    assert match_profile(profile, workflow, environment)['peak_mb'] == 1201
    assert profile == original


@pytest.mark.parametrize('field', ['width', 'height', 'batch_size'])
def test_parameter_changes_reject(inputs, field):
    workflow, environment, profile = inputs
    workflow['1']['inputs'][field] += 1
    assert not match_profile(profile, workflow, environment)['ok']


@pytest.mark.parametrize('field', ['gpu', 'driver', 'backend', 'model_digest'])
def test_environment_changes_reject(inputs, field):
    workflow, environment, profile = inputs
    environment[field] = 'different'
    assert not match_profile(profile, workflow, environment)['ok']


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), -1, 0, '100'])
def test_invalid_samples_reject(inputs, value):
    workflow, environment, profile = inputs
    profile['peak_mb_samples'] = [value]
    assert not match_profile(profile, workflow, environment)['ok']


def test_simulated_evidence_reject(inputs):
    workflow, environment, profile = inputs
    profile['evidence']['kind'] = 'simulation'
    assert not match_profile(profile, workflow, environment)['ok']


def test_canonical_hash_and_nonfinite():
    assert workload_fingerprint({'b': 2, 'a': 1}) == workload_fingerprint({'a': 1, 'b': 2})
    with pytest.raises(ValueError):
        workload_fingerprint({'x': float('nan')})
