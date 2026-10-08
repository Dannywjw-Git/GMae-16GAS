import json
import pytest
from clients import docker_client


def test_exact_fresh_container_state(monkeypatch):
    payload = [{'Name': '/comfyui', 'Id': 'a' * 64,
                'State': dict(Running=False, Paused=False, Restarting=False, Dead=False)}]
    calls = []
    monkeypatch.setattr(docker_client, 'run_args', lambda args, timeout: (
        calls.append(args) or 0, json.dumps(payload)))
    result = docker_client.container_target_state('comfyui')
    assert result['ok'] and result['running'] is False
    assert calls[0][1:] == ['inspect', '--type', 'container', 'comfyui']


@pytest.mark.parametrize('output', ['[]', 'invalid', '[{}]',
    json.dumps([dict(Name='/other', Id='a' * 64, State={})]),
    json.dumps([dict(Name='/comfyui', Id='a' * 64, State=dict(Running='false'))])])
def test_malformed_or_wrong_target_never_proves_state(monkeypatch, output):
    monkeypatch.setattr(docker_client, 'run_args', lambda *args: (0, output))
    assert not docker_client.container_target_state('comfyui')['ok']
