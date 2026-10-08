"""Experimental mutations require ownership, idle work, and physical evidence."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / 'scripts' / 'measure_comfy_workload.py'
spec = importlib.util.spec_from_file_location('gmae_measurement_conditions', SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def stats(total, free):
    return {'devices': [dict(type='cuda', index=0, torch_vram_total=total, torch_vram_free=free)]}


@pytest.mark.parametrize('document', [stats(True, 0), stats(10, 11), stats(-1, 0),
                                    {'devices': []}, {'devices': stats(10, 0)['devices'] * 2}])
def test_torch_baseline_rejects_missing_ambiguous_or_invalid_memory(document):
    with pytest.raises(ValueError):
        collector.torch_resident_bytes(document)


def test_low_torch_requires_physical_capacity_before_returning(monkeypatch):
    import services.comfy as comfy
    import engine.coordinator as coordination
    monkeypatch.setattr(coordination, 'restore_resource_operations', lambda: None)
    monkeypatch.setattr(coordination, 'get_coordinator', lambda: SimpleNamespace(snapshot=lambda: {'active': None}))
    calls = []
    monkeypatch.setattr(comfy, 'comfy_free', lambda: calls.append('release') or {'ok': True})
    readings = iter([dict(free_mb=5000, utilization=0), dict(free_mb=14000, utilization=0)])
    monkeypatch.setattr(collector, 'gpu_sample', lambda: next(readings))
    monkeypatch.setattr(collector, 'get_json', lambda url: stats(32 * 1024**2, 0))
    monkeypatch.setattr(collector.time, 'sleep', lambda delay: None)
    evidence = collector.prepare_unloaded_condition(10688)
    assert calls == ['release']
    assert len(evidence['readings']) == 2
    assert evidence['condition'] == 'model_unloaded_low_torch_verified'


def test_unknown_operation_prevents_experimental_release(monkeypatch):
    import services.comfy as comfy
    import engine.coordinator as coordination
    monkeypatch.setattr(coordination, 'restore_resource_operations', lambda: None)
    monkeypatch.setattr(coordination, 'get_coordinator', lambda: SimpleNamespace(snapshot=lambda: {'active': {'phase': 'uncertain'}}))
    monkeypatch.setattr(comfy, 'comfy_free', lambda: pytest.fail('must not release'))
    with pytest.raises(RuntimeError, match='unresolved'):
        collector.prepare_unloaded_condition(10688)


@pytest.mark.parametrize('queue,models,containers,pending,tasks', [
    ({'queue_running': None, 'queue_pending': []}, [], {}, [], []),
    ({'queue_running': ['external'], 'queue_pending': []}, [], {}, [], []),
    ({'queue_running': [], 'queue_pending': []}, None, {}, [], []),
    ({'queue_running': [], 'queue_pending': []}, [], {'fooocus': {}}, [], []),
    ({'queue_running': [], 'queue_pending': []}, [], {}, ['unknown'], []),
    ({'queue_running': [], 'queue_pending': []}, [], {}, [], [{'status': 'uncertain'}]),
])
def test_preflight_refuses_unknown_or_non_owned_work(monkeypatch, queue, models, containers, pending, tasks):
    import services.docker as docker
    monkeypatch.setattr(docker, 'docker_containers', lambda strict: containers)
    monkeypatch.setattr(collector, 'get_json', lambda url: queue if url.endswith('/queue') else {'models': models})
    store = SimpleNamespace(TERMINAL={'done', 'failed', 'canceled'}, snapshot=lambda: tasks)
    with pytest.raises(RuntimeError):
        collector.validate_trial_preflight(store, SimpleNamespace(pending=lambda: pending))


def test_acknowledged_unload_with_high_torch_occupancy_times_out(monkeypatch):
    import services.comfy as comfy
    import engine.coordinator as coordination
    monkeypatch.setattr(coordination, 'restore_resource_operations', lambda: None)
    monkeypatch.setattr(coordination, 'get_coordinator', lambda: SimpleNamespace(snapshot=lambda: {'active': None}))
    monkeypatch.setattr(comfy, 'comfy_free', lambda: {'ok': True})
    monkeypatch.setattr(collector, 'gpu_sample', lambda: dict(free_mb=14000, utilization=0))
    monkeypatch.setattr(collector, 'get_json', lambda url: stats(1024**3, 0))
    clock = iter([0, 0, 31])
    monkeypatch.setattr(collector.time, 'monotonic', lambda: next(clock))
    with pytest.raises(RuntimeError, match='no generation submitted'):
        collector.prepare_unloaded_condition(10688)
