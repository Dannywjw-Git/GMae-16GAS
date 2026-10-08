"""Synthetic observer responses verify rejection, not GPU residency or performance."""
from copy import deepcopy
from urllib.parse import parse_qs, urlparse
import uuid
import pytest
from clients import comfyui_client as client


def fixture():
    components = [dict(known=True, role=role, filename='sd_xl_base_1.0.safetensors',
        path_sha256='0' * 64, file_identity=[1, 1, 100, 1, 1], resident_bytes=100,
        model_bytes=100, fully_resident=True, patched=False, artifact_digest_verified=False)
        for role in ('unet', 'clip', 'vae')]
    return dict(schema_version=1, backend_instance_id=str(uuid.uuid4()), observer_code_sha256='1'*64,
        recorded_at_ns=1, monotonic_ns=1, load_epoch=1, active_loads=0, observation_failures=0,
        unknown_components=0, components=components, activity={'running':0,'pending':0},
        activity_after={'running':0,'pending':0}, residency_complete=True, warm_admission_enabled=False)


def provide(monkeypatch, response, stale=False):
    def get(path, timeout):
        assert timeout == 3
        value = deepcopy(response)
        value['request_id'] = str(uuid.uuid4()) if stale else parse_qs(urlparse(path).query)['request_id'][0]
        return True, value, ''
    monkeypatch.setattr(client, '_get', get)


def test_available_observation_does_not_enable_warm_admission(monkeypatch):
    provide(monkeypatch, fixture())
    result = client.residency_snapshot()
    assert result['ok'] is True
    assert result['residency_complete'] is True
    assert result['warm_admission_enabled'] is False


def test_stale_echo_is_rejected(monkeypatch):
    provide(monkeypatch, fixture(), stale=True)
    assert client.residency_snapshot()['code'] == 'RESIDENCY_UNVERIFIED'


@pytest.mark.parametrize('change', [
    lambda r: r.update(schema_version=True),
    lambda r: r.update(warm_admission_enabled=True),
    lambda r: r.update(unknown_components=1),
    lambda r: r['components'][0].update(resident_bytes=101),
    lambda r: r['components'][0].update(resident_bytes=50, fully_resident=False),
    lambda r: r['components'][0].update(artifact_digest_verified=True),
    lambda r: r['components'][0].update(file_identity=[1,1,-1,1,1]),
    lambda r: r['components'][0].update(path_sha256='bad'),
    lambda r: r['components'][0].update(role='clip'),
    lambda r: r['activity'].update(running=1),
    lambda r: r.update(observation_failures=1),
])
def test_inconsistent_or_unsupported_observation_rejected(monkeypatch, change):
    response = fixture()
    change(response)
    provide(monkeypatch, response)
    assert client.residency_snapshot()['code'] == 'RESIDENCY_UNVERIFIED'


def test_unknown_components_are_available_but_not_complete(monkeypatch):
    response = fixture()
    response.update(components=[dict(known=False, reason='untracked_or_ambiguous_source')],
                    unknown_components=1, residency_complete=False)
    provide(monkeypatch, response)
    result = client.residency_snapshot()
    assert result['ok'] is True and result['residency_complete'] is False


def test_optional_route_unavailable_is_explicit(monkeypatch):
    monkeypatch.setattr(client, '_get', lambda *args, **kwargs: (False, None, '404'))
    assert client.residency_snapshot()['code'] == 'RESIDENCY_UNAVAILABLE'


def test_host_endpoint_only_reads_and_returns_unavailable(monkeypatch):
    import json
    from api.endpoints.coordinator import get_residency
    monkeypatch.setattr(client, 'residency_snapshot', lambda: dict(ok=False, code='RESIDENCY_UNAVAILABLE', error='not installed'))
    response = get_residency(None)
    assert response.status_code == 422
    assert json.loads(response.body)['error']['code'] == 'RESIDENCY_UNAVAILABLE'
