"""Synthetic condition annotations test grouping, not real performance claims."""
import importlib.util
import json
from pathlib import Path
import sys
import pytest
from core.workload_profile import workload_fingerprint

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('gmae_trial_analysis', ROOT / 'scripts' / 'analyze_workload_trials.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def synthetic_fixture(seed=100, width=512, driver=None):
    raw = json.loads((ROOT / 'docs/evidence/sdxl-512-8steps-seed44-2026-10-08.json').read_bytes())
    raw['workflow']['5']['inputs']['seed'] = seed
    raw['workflow']['4']['inputs']['width'] = width
    raw['workflow_sha256'] = workload_fingerprint(raw['workflow'])
    raw['trial_condition'] = 'resident_memory_observed_model_identity_unproven'
    raw['baseline_torch_resident_bytes'] = 1024**3
    if driver:
        raw['gpu_identity']['driver'] = driver
    return raw


def test_seed_reuse_groups_but_parameter_and_environment_changes_do_not():
    payloads = [json.dumps(synthetic_fixture(seed=100)).encode(),
                json.dumps(synthetic_fixture(seed=101)).encode(),
                json.dumps(synthetic_fixture(width=768)).encode(),
                json.dumps(synthetic_fixture(driver='other')).encode()]
    result = analysis.analyze(payloads)
    assert len(result['groups']) == 3
    assert sorted(group['conditions']['resident_memory_observed_model_identity_unproven']['trials']
                  for group in result['groups']) == [1, 1, 2]
    assert result['scheduler_benefit_proven'] is False
    assert result['residency_identity_proven'] is False


def test_unload_label_without_physical_preparation_is_rejected():
    raw = synthetic_fixture()
    raw['trial_condition'] = 'model_unloaded_low_torch_verified'
    raw['baseline_torch_resident_bytes'] = 0
    with pytest.raises(ValueError, match='preparation'):
        analysis.analyze([json.dumps(raw).encode()])


@pytest.mark.parametrize('duration', [True, float('nan')])
def test_invalid_duration_cannot_enter_comparison(duration):
    raw = synthetic_fixture()
    raw['duration_s'] = duration
    with pytest.raises(ValueError, match='duration'):
        analysis.analyze([json.dumps(raw).encode()])


def test_resident_label_with_zero_torch_memory_is_rejected():
    raw = synthetic_fixture()
    raw['baseline_torch_resident_bytes'] = 0
    with pytest.raises(ValueError, match='substantial'):
        analysis.analyze([json.dumps(raw).encode()])
