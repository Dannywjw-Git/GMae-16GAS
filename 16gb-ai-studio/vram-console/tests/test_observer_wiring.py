"""Comfy route/loader bridge contract with isolated framework doubles."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import uuid
import pytest
from clients.comfyui_client import _validate_residency

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    class Model:
        pass
    patchers = [SimpleNamespace(model=Model(), patches={}) for _ in range(3)]
    outputs = (patchers[0], SimpleNamespace(patcher=patchers[1]), SimpleNamespace(patcher=patchers[2]))
    class Loaded:
        device = SimpleNamespace(type='cuda', index=0)
        def __init__(self, patcher):
            self.model = patcher
        def model_loaded_memory(self):
            return 100
        def model_memory(self):
            return 100
    queue = SimpleNamespace(get_current_queue=lambda: ([], []))
    handlers = {}
    def route(path):
        def register(function):
            handlers[path] = function
            return function
        return register
    server = ModuleType('server')
    server.PromptServer = SimpleNamespace(instance=SimpleNamespace(prompt_queue=queue,
        routes=SimpleNamespace(get=route)))
    sd = ModuleType('comfy.sd')
    sd.load_checkpoint_guess_config = lambda *args, **kwargs: outputs
    mm = ModuleType('comfy.model_management')
    mm.current_loaded_models = [Loaded(patcher) for patcher in patchers]
    comfy = ModuleType('comfy')
    comfy.__path__ = []
    comfy.sd, comfy.model_management = sd, mm
    aiohttp = ModuleType('aiohttp')
    aiohttp.web = SimpleNamespace(json_response=lambda payload, status=200, headers=None:
                                 SimpleNamespace(payload=payload, status=status, headers=headers or {}))
    for name, module in [('server', server), ('comfy', comfy), ('comfy.sd', sd),
                         ('comfy.model_management', mm), ('aiohttp', aiohttp)]:
        monkeypatch.setitem(sys.modules, name, module)
    name = 'gmae_observer_bridge_' + uuid.uuid4().hex
    path = ROOT / 'integrations/gmae_comfy_observer/__init__.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    checkpoint = tmp_path / 'sd_xl_base_1.0.safetensors'
    checkpoint.write_bytes(b'synthetic loader fixture')
    assert sd.load_checkpoint_guess_config(checkpoint) is outputs
    return handlers['/gmae/residency'], queue


def test_route_matches_host_validator_and_is_never_admission(bridge):
    handler, _ = bridge
    request_id = str(uuid.uuid4())
    result = asyncio.run(handler(SimpleNamespace(query={'request_id': request_id})))
    assert result.status == 200 and result.headers['Cache-Control'] == 'no-store'
    _validate_residency(result.payload, request_id)
    assert result.payload['residency_complete'] is True
    assert result.payload['warm_admission_enabled'] is False


def test_missing_nonce_is_rejected_before_snapshot(bridge):
    handler, _ = bridge
    assert asyncio.run(handler(SimpleNamespace(query={}))).status == 400


def test_activity_change_invalidates_complete_snapshot(bridge):
    handler, queue = bridge
    snapshots = iter([([], []), (['new_job'], [])])
    queue.get_current_queue = lambda: next(snapshots)
    request_id = str(uuid.uuid4())
    result = asyncio.run(handler(SimpleNamespace(query={'request_id': request_id})))
    assert result.payload['activity_changed'] is True
    assert result.payload['residency_complete'] is False
    _validate_residency(result.payload, request_id)


def test_backend_activity_failure_returns_unavailable_without_details(bridge):
    handler, queue = bridge
    def fail():
        raise RuntimeError('private backend detail')
    queue.get_current_queue = fail
    result = asyncio.run(handler(SimpleNamespace(query={'request_id': str(uuid.uuid4())})))
    assert result.status == 503
    assert 'private backend detail' not in str(result.payload)
