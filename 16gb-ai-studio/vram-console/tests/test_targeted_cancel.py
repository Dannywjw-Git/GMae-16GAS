"""Cancellation transport must remain ID-specific and cannot prove completion."""
from io import BytesIO
import json
import urllib.error
from unittest.mock import Mock
import uuid

import pytest
from clients import comfyui_client as client


def test_cancel_uses_only_job_specific_endpoint(monkeypatch):
    prompt_id = str(uuid.uuid4())
    transport = Mock(return_value=BytesIO(b'{"cancelled":true}'))
    monkeypatch.setattr(client.urllib.request, 'urlopen', transport)
    result = client.cancel_job(prompt_id)
    request = transport.call_args.args[0]
    assert request.full_url == client.COMFY_BASE + '/api/jobs/' + prompt_id + '/cancel'
    assert request.method == 'POST' and json.loads(request.data) == {}
    assert result['acknowledged'] is True and result['prompt_id'] == prompt_id
    assert 'terminal' not in result


@pytest.mark.parametrize('status', [404, 405])
def test_unsupported_route_never_falls_back_to_interrupt(monkeypatch, status):
    transport = Mock(side_effect=urllib.error.HTTPError('cancel', status, 'unsupported', {}, None))
    monkeypatch.setattr(client.urllib.request, 'urlopen', transport)
    assert client.cancel_job(str(uuid.uuid4()))['code'] == 'CANCEL_UNSUPPORTED'
    transport.assert_called_once()


@pytest.mark.parametrize('payload', [b'{}', b'{"cancelled":"true"}', b'[]', b'not-json'])
def test_malformed_ack_is_never_success(monkeypatch, payload):
    monkeypatch.setattr(client.urllib.request, 'urlopen', lambda *args, **kwargs: BytesIO(payload))
    assert client.cancel_job(str(uuid.uuid4()))['code'] == 'CANCEL_UNCONFIRMED'


def test_timeout_cannot_prove_cancel(monkeypatch):
    monkeypatch.setattr(client.urllib.request, 'urlopen', Mock(side_effect=TimeoutError('lost response')))
    assert client.cancel_job(str(uuid.uuid4()))['code'] == 'CANCEL_UNCONFIRMED'


@pytest.mark.parametrize('prompt_id', ['', 'partial-id', '../interrupt', 123])
def test_invalid_id_never_reaches_backend(monkeypatch, prompt_id):
    transport = Mock()
    monkeypatch.setattr(client.urllib.request, 'urlopen', transport)
    assert client.cancel_job(prompt_id)['code'] == 'INVALID_BACKEND_ID'
    transport.assert_not_called()


@pytest.mark.parametrize('snapshot', [{}, {'queue_running': [], 'queue_pending': None},
                                    {'queue_running': [[1]], 'queue_pending': []}])
def test_malformed_queue_cannot_prove_absence(monkeypatch, snapshot):
    monkeypatch.setattr(client, '_get', lambda path: (True, snapshot, ''))
    assert not client.canceled_job_absent('target')


def test_strict_queue_tracks_running_and_pending_ids(monkeypatch):
    monkeypatch.setattr(client, '_get', lambda path: (
        True, {'queue_running': [[1, 'running']], 'queue_pending': [[2, 'pending']]}, ''))
    assert not client.canceled_job_absent('running')
    assert not client.canceled_job_absent('pending')
    assert client.canceled_job_absent('target')
