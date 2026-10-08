"""Actual HTTP routing on an ephemeral local socket, without GPU adapter calls."""
import http.client
from http.server import ThreadingHTTPServer
import json
import threading
from unittest.mock import Mock
import pytest
from api import routes
from core.resource_coordinator import ResourceRequest
from engine.coordinator import get_coordinator


@pytest.fixture
def http_endpoint(monkeypatch):
    monkeypatch.setattr(routes, "API_TOKEN", "test-only-token")
    server = ThreadingHTTPServer(('127.0.0.1', 0), routes.Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()

    def request(method, path, body=None, authenticated=True):
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['X-API-Key'] = 'test-only-token'
        try:
            connection.request(method, path, json.dumps(body) if body is not None else None, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    try:
        yield request
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.parametrize('method,path', [('GET', '/api/coordinator'),
    ('POST', '/api/coordinator/preview'), ('POST', '/api/coordinator/reconcile')])
def test_coordinator_routes_require_authentication(http_endpoint, method, path):
    status, body = http_endpoint(method, path, authenticated=False)
    assert status == 401
    assert body['ok'] is False


def test_read_ownership_does_not_require_gpu_telemetry(http_endpoint, monkeypatch):
    read = Mock(side_effect=AssertionError('GPU query is forbidden for ledger reads'))
    monkeypatch.setattr('engine.coordinator.gpu_status', read)
    with get_coordinator().operation(ResourceRequest('generate', 'http-job', 'comfyui', peak_mb=8192)):
        status, body = http_endpoint('GET', '/api/coordinator')
        assert status == 200
        assert body['data']['active']['owner'] == 'http-job'
        assert body['data']['reserved_mb'] == 8192
    read.assert_not_called()


def test_busy_mutation_is_http_error_with_blocker_and_no_adapter(http_endpoint, monkeypatch):
    action = Mock(side_effect=AssertionError('busy request reached adapter'))
    monkeypatch.setattr('api.endpoints.vram.free_all', action)
    with get_coordinator().operation(ResourceRequest('generate', 'http-job', 'comfyui')):
        status, body = http_endpoint('POST', '/api/free')
        assert status == 409
        assert body['ok'] is False
        assert body['error']['code'] == 'RESOURCE_BUSY'
        assert body['error']['details']['coordination']['blocker']['owner'] == 'http-job'
    action.assert_not_called()


def test_client_terminal_claim_cannot_clear_uncertain_ownership(http_endpoint, monkeypatch):
    with get_coordinator().operation(ResourceRequest('generate', 'http-job', 'comfyui')) as lease:
        lease.uncertain('history unavailable', prompt_id='real-prompt')
    monkeypatch.setattr('clients.comfyui_client._get', lambda path: (True, {}, ''))
    status, body = http_endpoint('POST', '/api/coordinator/reconcile',
                                {'terminal': True, 'token': lease.token, 'prompt_id': 'real-prompt'})
    assert status == 409
    assert body['ok'] is False
    assert get_coordinator().snapshot()['active']['token'] == lease.token


def test_qos_get_observes_without_releasing_gpu(http_endpoint, monkeypatch):
    monkeypatch.setattr('engine.qos.gpu_status', lambda: {'ok': True, 'free_mb': 1})
    action = Mock(side_effect=AssertionError('GET must not release resources'))
    monkeypatch.setattr('engine.qos._auto_protect_run', action)
    status, body = http_endpoint('GET', '/api/qos/check')
    assert status == 200
    assert body['data']['level'] == 'emergency'
    action.assert_not_called()
