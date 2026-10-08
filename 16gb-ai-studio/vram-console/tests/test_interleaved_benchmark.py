"""Reject misleading benchmark rows; fixtures are not GPU evidence."""
import importlib.util
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('gmae_interleaved',ROOT/'scripts/run_interleaved_queue_benchmark.py')
benchmark=importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def fixture(mode='resident'):
    return dict(task_status='done',backend_terminal='success',sampler_cache_hit=False,sampling_errors=[],
        coordination=dict(active=None),residency_before=dict(ok=True,residency_complete=True),
        budget=dict(measured_profile=dict(memory_scope='measured_resident_increment' if mode=='resident' else 'sampled_whole_device_upper_envelope')))


@pytest.mark.parametrize('field,value',[('task_status','failed'),('backend_terminal','error'),('sampler_cache_hit',True),('sampling_errors',['unavailable'])])
def test_failed_or_cached_trial_cannot_enter_success_comparison(field,value):
    row=fixture();row[field]=value
    with pytest.raises(ValueError): benchmark.eligible(row,'resident')


def test_wrong_actual_strategy_is_not_mislabeled_resident():
    with pytest.raises(ValueError,match='actual admission path'):
        benchmark.eligible(fixture('conservative'),'resident')


def test_unconfirmed_execution_stops_benchmark():
    row=fixture();row['coordination']['active']={'phase':'uncertain'}
    with pytest.raises(ValueError): benchmark.eligible(row,'resident')


def test_unverified_start_cannot_be_compared_to_verified_resident_start():
    row=fixture();row['residency_before']['residency_complete']=False
    with pytest.raises(ValueError): benchmark.eligible(row,'resident')
