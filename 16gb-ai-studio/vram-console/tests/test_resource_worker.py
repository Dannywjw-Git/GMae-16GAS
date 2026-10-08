"""Real worker lifetimes, bounded overload and HTTP timeout semantics."""
import json
import threading
from unittest.mock import Mock
import pytest
from api import resource_commands
from api.response import Response
from core.resource_coordinator import ResourceDenied, ResourceRequest
from core.resource_worker import ResourceCommandWorker
from engine.coordinator import get_coordinator


def test_worker_overload_and_slot_recovery_after_failure():
    worker = ResourceCommandWorker(capacity=1)
    entered, finish = threading.Event(), threading.Event()

    def failing_command():
        entered.set()
        assert finish.wait(3)
        raise RuntimeError("adapter failed")

    try:
        future = worker.submit(failing_command)
        assert entered.wait(3)
        with pytest.raises(ResourceDenied) as error:
            worker.submit(lambda: pytest.fail("overload executed"))
        assert error.value.code == "COMMAND_QUEUE_FULL"
        finish.set()
        with pytest.raises(RuntimeError, match="adapter failed"):
            future.result(timeout=3)
        assert worker.submit(lambda: "recovered").result(timeout=3) == "recovered"
    finally:
        finish.set()
        worker.shutdown()


def test_request_body_read_on_handler_and_action_runs_on_worker(monkeypatch):
    handler_thread = threading.get_ident()
    worker = ResourceCommandWorker()
    monkeypatch.setattr(resource_commands, "get_command_worker", lambda: worker)

    class Request:
        @property
        def body(self):
            assert threading.get_ident() == handler_thread
            return {"action": "release"}

    @resource_commands.resource_command
    def action(request):
        assert threading.get_ident() != handler_thread
        return Response.success({"executed": True})

    try:
        assert action(Request()).status_code == 200
    finally:
        worker.shutdown()


def test_http_timeout_keeps_inflight_reservation(monkeypatch):
    worker = ResourceCommandWorker()
    monkeypatch.setattr(resource_commands, "get_command_worker", lambda: worker)
    monkeypatch.setattr(resource_commands, "COMMAND_RESPONSE_TIMEOUT_S", 0.05)
    entered, finish = threading.Event(), threading.Event()

    @resource_commands.resource_command
    def action(request):
        with get_coordinator().operation(ResourceRequest("release", "slow-command")):
            entered.set()
            assert finish.wait(3)
        return Response.success()

    try:
        response = action(Mock(body={}))
        assert entered.is_set()
        assert response.status_code == 503
        assert json.loads(response.body)["error"]["code"] == "COMMAND_STILL_RUNNING"
        assert get_coordinator().snapshot()["active"]["owner"] == "slow-command"
        assert action(Mock(body={})).status_code == 409
    finally:
        finish.set()
        worker.shutdown()
    assert get_coordinator().snapshot()["active"] is None


def test_overload_is_http_429_and_not_success():
    response = Response.from_result(ResourceDenied("COMMAND_QUEUE_FULL", "full").result())
    assert response.status_code == 429
    assert json.loads(response.body)["ok"] is False
