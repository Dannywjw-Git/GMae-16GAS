"""Installed real-format evidence with mocked live adapters; not GPU execution."""
from collections import deque
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from core.registry import registry
from core.resource_coordinator import ResourceDenied
from core.workload_profile import profile_from_evidence, execution_configuration_fingerprint
from engine import profile_admission, coordinator, queue


@pytest.fixture
def installed(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[3]
    payload = (repo / 'docs/evidence/sdxl-512-8steps-seed44-2026-10-08.json').read_bytes()
    raw = json.loads(payload)
    profile = profile_from_evidence(payload, 512)
    key = profile['execution_configuration_sha256']
    monkeypatch.setenv('GMAE_PROFILE_DIR', str(tmp_path))
    (tmp_path / 'raw.json').write_bytes(payload)
    manifest = dict(raw_file='raw.json', raw_sha256=hashlib.sha256(payload).hexdigest(), margin_mb=512)
    (tmp_path / (key + '.json')).write_text(json.dumps(manifest))
    monkeypatch.setattr(profile_admission, '_live_environment', lambda raw: profile['environment'].copy())
    return raw, profile, tmp_path


def test_installed_evidence_recomputed_and_seed_reuse(installed):
    raw, profile, _ = installed
    wf = raw['workflow']
    wf['5']['inputs']['seed'] = 45
    reference = profile_admission.select_profile(wf)
    measured = profile_admission.measured_budget(wf, reference)
    assert measured['peak_mb'] == 9649
    assert measured['workflow_sha256'] == reference['workflow_sha256']
    assert measured['calibration_workflow_sha256'] != measured['workflow_sha256']
    wf['4']['inputs']['width'] = 1024
    assert profile_admission.select_profile(wf) is None


def test_prompt_change_requires_new_evidence(installed):
    raw, _, _ = installed
    raw['workflow']['2']['inputs']['text'] = 'different prompt'
    assert profile_admission.select_profile(raw['workflow']) is None


def test_preview_binds_actual_parameters_without_enqueuing(installed, monkeypatch):
    from types import SimpleNamespace
    from api.endpoints import coordinator as endpoint
    raw, _, _ = installed
    body = dict(source='comfyui', model='SDXL', params={**raw['parameters'], 'seed': 46})
    request = SimpleNamespace(body_get=lambda key, default=None: body.get(key, default))
    preview = Mock(return_value={'ok': True, 'allowed': True})
    enqueue = Mock()
    monkeypatch.setattr(endpoint, 'preview', preview)
    monkeypatch.setattr(queue, 'queue_enqueue', enqueue)
    response = endpoint.post_preview(request)
    assert response.status_code == 200
    spec = preview.call_args.args[0]
    assert spec.workflow['5']['inputs']['seed'] == 46
    assert spec.profile_reference is not None
    enqueue.assert_not_called()
    body['params']['width'] = 768
    preview.reset_mock()
    response = endpoint.post_preview(request)
    assert json.loads(response.body)['error']['code'] == 'PROFILE_REQUIRED'
    preview.assert_not_called()


def test_changed_evidence_and_live_identity_fail_closed(installed, monkeypatch):
    raw, profile, root = installed
    reference = profile_admission.select_profile(raw['workflow'])
    monkeypatch.setattr(profile_admission, '_live_environment', lambda raw: {**profile['environment'], 'driver': 'changed'})
    with pytest.raises(ResourceDenied, match='environment mismatch'):
        profile_admission.measured_budget(raw['workflow'], reference)
    (root / 'raw.json').write_bytes(b'changed')
    with pytest.raises(ResourceDenied):
        profile_admission.measured_budget(raw['workflow'], reference)


def test_changed_margin_cannot_replace_accepted_reference(installed):
    raw, _, root = installed
    reference = profile_admission.select_profile(raw['workflow'])
    target = root / (execution_configuration_fingerprint(raw['workflow']) + '.json')
    manifest = json.loads(target.read_bytes())
    manifest['margin_mb'] = 1024
    target.write_text(json.dumps(manifest))
    with pytest.raises(ResourceDenied, match='changed or disappeared'):
        profile_admission.measured_budget(raw['workflow'], reference)


def test_release_waits_through_temporarily_rejected_budget(monkeypatch):
    from core.resource_coordinator import ResourceCoordinator, ResourceRequest
    item = dict(vram_gb=9, note='await physical telemetry')
    budget = Mock(side_effect=[({}, {**item, 'decision': 'free_L2'}),
                              ({}, {**item, 'decision': 'reject'}),
                              ({}, {**item, 'decision': 'ok'}),
                              ({}, {**item, 'decision': 'ok'})])
    monkeypatch.setattr(coordinator, '_model_budget', budget)
    monkeypatch.setattr(coordinator, 'check_idle', lambda service: None)
    monkeypatch.setattr('engine.eviction_guard.gpu_guard_evict', lambda: {'ok': True})
    monkeypatch.setattr(coordinator.time, 'sleep', lambda seconds: None)
    with ResourceCoordinator().operation(ResourceRequest('generate', 'test')) as lease:
        coordinator._assess_model(coordinator.OperationSpec('generate', 'comfyui', 'SDXL'), lease)
    assert budget.call_args_list[1].kwargs['allow_rejected'] is True


def test_formal_queue_uses_measured_override_and_persists_decision(installed, monkeypatch, tmp_path):
    raw, _, _ = installed
    registry.delete('task_store')
    state = dict(tasks={}, task_queue=deque(), worker_alive=False, restored=True)
    monkeypatch.setattr(queue, '_queue_state', state)
    monkeypatch.setattr(queue, '_tasks', state['tasks'])
    monkeypatch.setattr(queue, '_task_queue', state['task_queue'])
    monkeypatch.setattr(queue, '_start_worker', lambda: None)
    monkeypatch.setenv('GMAE_TASK_DB', str(tmp_path / 'tasks.sqlite3'))
    monkeypatch.setattr(queue, 'REGISTRY', {'comfyui': {'models': [{'id': 'SDXL', 'workflow': 'sdxl_t2i.json'}]}})
    monkeypatch.setattr(coordinator, 'check_idle', lambda service: None)
    monkeypatch.setattr(coordinator, 'fresh_gpu', lambda: dict(total_mb=16380, used_mb=1024, free_mb=15356))
    budget = Mock(return_value=dict(ok=True, models=[dict(id='SDXL', source='comfyui', decision='ok',
                                                        vram_gb=9649 / 1024)], loaded_models=[]))
    monkeypatch.setattr('engine.budget.budget_engine', budget)
    monkeypatch.setattr(queue, '_queue_submit_comfy', lambda wf, sid: (sid, None))
    monkeypatch.setattr(queue, '_queue_wait', lambda *args: 'done')
    monkeypatch.setattr(queue, 'update_gen_stats', lambda *args: None)
    try:
        params = {**raw['parameters'], 'seed': 45}
        result = queue.queue_enqueue('SDXL', params)
        assert result['ok']
        task = queue._tasks[result['task']['id']]
        queue._run_task(task)
        assert task['status'] == 'done'
        assert task['budget']['profile_status'] == 'raw_evidence_and_live_identity_verified'
        assert budget.call_args.kwargs['peak_overrides'] == {('comfyui', 'SDXL'): 9649 / 1024}
        assert queue._store().get(task['id'])['checkpoint']['budget']['measured_profile']['evidence_sha256']
    finally:
        registry.delete('task_store')
