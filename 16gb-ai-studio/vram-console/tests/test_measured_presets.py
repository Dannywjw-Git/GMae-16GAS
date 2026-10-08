"""Installed evidence discovery and immutable preset HTTP submission contracts."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from core.workload_profile import workload_fingerprint
from engine import measured_presets


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setenv('GMAE_PROFILE_DIR', str(tmp_path))
    repo = Path(__file__).resolve().parents[3]
    payload = (repo / 'docs/evidence/ollama-long-profile-20261008/ollama-qwen9b-long8192-20261008.json').read_bytes()
    raw = json.loads(payload)
    key = workload_fingerprint(raw['request'])
    (tmp_path / 'raw.json').write_bytes(payload)
    manifest = dict(raw_file='raw.json', raw_sha256=hashlib.sha256(payload).hexdigest(), margin_mb=512)
    (tmp_path / (key + '.json')).write_text(json.dumps(manifest), encoding='utf-8')
    return tmp_path, key, raw, manifest


def test_catalog_validates_actual_archive_without_live_permission(installed, monkeypatch):
    from engine import profile_admission
    monkeypatch.setattr(profile_admission, '_live_environment', lambda *a: pytest.fail('discovery touched GPU/backend'))
    catalog = measured_presets.public_catalog()
    assert catalog['live_admission_verified'] is False
    assert catalog['rejected_count'] == 0
    item, = catalog['presets']
    assert item['envelope_mb'] == 8833
    assert item['prompt_tokens'] == 6182
    assert 'request' not in item and 'prompt' not in item
    assert measured_presets.resolve_preset(item['id'])['request'] == installed[2]['request']


@pytest.mark.parametrize('damage', ['bytes', 'digest', 'traversal', 'request', 'shape'])
def test_catalog_refuses_damaged_or_mismatched_installation(installed, damage):
    root, key, raw, manifest = installed
    if damage == 'bytes':
        (root / 'raw.json').write_text('{}')
    elif damage == 'digest':
        manifest['raw_sha256'] = '0' * 64
    elif damage == 'traversal':
        manifest['raw_file'] = '../raw.json'
    elif damage == 'request':
        raw['request']['prompt'] += ' changed'
        payload = json.dumps(raw).encode()
        (root / 'raw.json').write_bytes(payload)
        manifest['raw_sha256'] = hashlib.sha256(payload).hexdigest()
    else:
        manifest = []
    (root / (key + '.json')).write_text(json.dumps(manifest))
    assert measured_presets.public_catalog()['presets'] == []
    with pytest.raises(ValueError):
        measured_presets.resolve_preset(key)


def request(body):
    return SimpleNamespace(body=body, body_get=lambda key, default=None: body.get(key, default))


def test_http_submits_exact_server_request_and_idempotency(installed, monkeypatch):
    from api.endpoints import queue
    calls = []
    monkeypatch.setattr(queue, 'queue_enqueue_ollama', lambda body, key: calls.append((body, key)) or {'ok': True, 'task_id': 'job'})
    response = queue.post_queue_preset(request(dict(preset_id=installed[1], idempotency_key='same-key')))
    assert response.status_code == 200
    assert calls == [(installed[2]['request'], 'same-key')]
    # Removing evidence after discovery cannot submit a previously shown preset.
    (installed[0] / 'raw.json').unlink()
    response = queue.post_queue_preset(request(dict(preset_id=installed[1], idempotency_key='same-key')))
    assert response.status_code == 422 and len(calls) == 1


@pytest.mark.parametrize('extra', [{'request': {}}, {'peak_mb': 1}, {'margin_mb': 0}])
def test_http_refuses_client_mutation(installed, monkeypatch, extra):
    from api.endpoints import queue
    monkeypatch.setattr(queue, 'queue_enqueue_ollama', lambda *a: pytest.fail('unexpected enqueue'))
    response = queue.post_queue_preset(request(dict(preset_id=installed[1], **extra)))
    assert response.status_code == 422


def install_comfy(root):
    repo = Path(__file__).resolve().parents[3]
    payload = (repo / 'docs/evidence/sdxl-observer-512-seed51-20261008.json').read_bytes()
    from core.workload_profile import profile_from_evidence
    profile = profile_from_evidence(payload, 512)
    key = profile['execution_configuration_sha256']
    (root / 'comfy-raw.json').write_bytes(payload)
    (root / (key + '.json')).write_text(json.dumps(dict(raw_file='comfy-raw.json',
        raw_sha256=hashlib.sha256(payload).hexdigest(), margin_mb=512)))
    return key, json.loads(payload)['workflow']


def test_mixed_catalog_and_comfy_submission_bind_registered_graph(installed, monkeypatch):
    from api.endpoints import queue
    from engine.queue import REGISTRY, _load_workflow, _apply_params
    from core.workload_profile import execution_configuration_fingerprint
    key, workflow = install_comfy(installed[0])
    catalog = measured_presets.public_catalog()
    assert {p['source'] for p in catalog['presets']} == {'comfyui', 'ollama'}
    item = measured_presets.resolve_preset(key)
    assert item['model'] == 'SDXL' and item['envelope_mb'] == 9217
    assert item['params']['width'] == 512 and item['params']['steps'] == 8
    model = next(m for m in REGISTRY['comfyui']['models'] if m['id'] == item['model'])
    assert execution_configuration_fingerprint(_apply_params(_load_workflow(model['workflow']), item['params'])) == execution_configuration_fingerprint(workflow)
    calls = []
    monkeypatch.setattr(queue, 'queue_enqueue', lambda *args: calls.append(args) or {'ok': True})
    monkeypatch.setattr(queue, 'queue_enqueue_ollama', lambda *a: pytest.fail('wrong backend'))
    assert queue.post_queue_preset(request(dict(preset_id=key, idempotency_key='comfy-key'))).status_code == 200
    assert calls == [('SDXL', item['params'], 'comfy-key')]


def test_comfy_catalog_rejects_graph_outside_registered_template(installed):
    _, workflow = install_comfy(installed[0])
    # Valid-looking control reconstruction cannot allow a different sampler.
    sampler = next(node for node in workflow.values() if node['class_type'] == 'KSampler')
    sampler['inputs']['sampler_name'] = 'unregistered-sampler'
    with pytest.raises(ValueError, match='registered template'):
        measured_presets._comfy_intent(workflow)
