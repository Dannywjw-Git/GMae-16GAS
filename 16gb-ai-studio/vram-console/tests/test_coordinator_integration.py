"""Exercise real service/queue/coordinator paths with only external adapters faked."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import Mock
import pytest
from core.resource_coordinator import ResourceDenied
from engine import budget, coordinator, queue
from services import comfy, docker, ollama, scene


@pytest.fixture
def gpu_environment(monkeypatch):
    state = {"ok": True, "total_mb": 16384, "used_mb": 1024, "free_mb": 15360,
             "loaded": [], "running": [], "pending": []}
    config = {"system": {"gpu_base_noise_gb": 1, "vram_reserve_gb": 2.5},
              "ollama": {"models": [{"id": "llm", "vram_gb": 8, "ctx": 8192,
                                        "context_vram": {"8192": 8}}]},
              "comfyui": {"models": [{"id": "target", "vram_gb": 8, "workflow": "test.json"}]},
              "containers": [{"name": "comfyui", "startup_vram_gb": 1},
                             {"name": "ollama", "startup_vram_gb": 0}], "scenes": {}}
    read_gpu = lambda **kwargs: {k: v for k, v in deepcopy(state).items()
                                 if k in ("ok", "stale", "total_mb", "used_mb", "free_mb")}
    for module in (coordinator, budget):
        monkeypatch.setattr(module, "REGISTRY", config)
        monkeypatch.setattr(module, "gpu_status", read_gpu)
    monkeypatch.setattr("gpu.monitor.gpu_status", read_gpu)
    monkeypatch.setattr(scene, "REGISTRY", config)
    monkeypatch.setattr(docker, "docker_containers", lambda **kwargs: ["comfyui", "ollama"])
    monkeypatch.setattr(comfy, "comfy_queue", lambda: {"ok": True,
                        "running": state["running"], "pending": state["pending"]})
    monkeypatch.setattr(comfy, "comfy_loaded_models", lambda: {"ok": True, "models": []})
    monkeypatch.setattr(ollama, "ollama_ps", lambda: {"ok": True, "models": state["loaded"]})
    monkeypatch.setattr(ollama, "list_loaded_models", lambda: {"ok": True, "models": state["loaded"]})
    monkeypatch.setattr(budget, "gpu_processes", lambda: {"ok": True,
                        "known_total_mb": sum(int(m.get("size_gb", 0) * 1024) for m in state["loaded"]),
                        "unknown_mb": 0, "desktop_used_mb": 0})
    monkeypatch.setattr(budget, "load_gen_stats", lambda: {})
    monkeypatch.setattr(queue, "_load_workflow", lambda name: {"1": {"inputs": {"text": "hello"}}})
    monkeypatch.setattr(queue, "update_gen_stats", lambda *args: None)
    return state, config


def task():
    return {"id": "coordinator-test", "model": "target", "workflow": "test.json",
            "params": {}, "status": "queued", "error": "", "started": None}


def test_queue_lifetime_blocks_model_load_scene_release_qos_and_reaper(gpu_environment, monkeypatch):
    from engine import qos, reaper
    entered, finish = threading.Event(), threading.Event()
    submit = Mock(return_value=("prompt-full-id", None))
    monkeypatch.setattr(queue, "_queue_submit_comfy", submit)

    def wait(prompt_id, current):
        entered.set()
        assert finish.wait(5)
        return "done"

    monkeypatch.setattr(queue, "_queue_wait", wait)
    current = task()
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(queue._run_task, current)
        assert entered.wait(5)
        try:
            for invoke in (docker.free_all, comfy.comfy_free,
                           lambda: scene.scene_switch("dialogue"),
                           lambda: scene.combo_switch("9b"),
                           lambda: scene.model_action("llm", "load"),
                           lambda: qos.qos_execute_suggestion("any"),
                           lambda: reaper._reap_service("comfyui", 3600),
                           lambda: docker.container_unpause("comfyui")):
                result = invoke()
                assert result["ok"] is False
                assert result.get("code") == "RESOURCE_BUSY" or "RESOURCE_BUSY" in result.get("output", "")
            assert coordinator.get_coordinator().snapshot()["active"]["owner"] == "job:coordinator-test"
            assert coordinator.get_coordinator().snapshot()["reserved_mb"] == 8192
        finally:
            finish.set()
        future.result(timeout=5)
    assert current["status"] == "done"
    assert coordinator.get_coordinator().snapshot()["active"] is None
    submit.assert_called_once()


def test_releasing_models_rechecks_physical_memory_before_submission(gpu_environment, monkeypatch):
    state, config = gpu_environment
    state.update(used_mb=8192, free_mb=8192, loaded=[{"name": "other", "size_gb": 6}])
    monkeypatch.setattr("engine.eviction_guard.gpu_guard_evict", Mock(return_value={"ok": False}))
    submit = Mock()
    monkeypatch.setattr(queue, "_queue_submit_comfy", submit)
    current = task()
    queue._run_task(current)
    assert current["status"] == "failed"
    assert current["coordination"]["code"] == "RELEASE_FAILED"
    submit.assert_not_called()


def test_verified_release_can_submit_and_has_no_gap_in_ownership(gpu_environment, monkeypatch):
    state, config = gpu_environment
    state.update(used_mb=8192, free_mb=8192, loaded=[{"name": "other", "size_gb": 6}])

    def release():
        assert coordinator.get_coordinator().snapshot()["active"]["phase"] == "releasing"
        state.update(used_mb=1024, free_mb=15360, loaded=[])
        return {"ok": True}

    monkeypatch.setattr("engine.eviction_guard.gpu_guard_evict", release)
    monkeypatch.setattr(queue, "_queue_submit_comfy", Mock(return_value=("prompt-id", None)))
    monkeypatch.setattr(queue, "_queue_wait", lambda *args: "done")
    current = task()
    queue._run_task(current)
    assert current["status"] == "done"
    assert current["budget"]["decision"] == "ok"


def test_stale_telemetry_never_calls_release_adapter(gpu_environment, monkeypatch):
    state, config = gpu_environment
    state["stale"] = True
    action = Mock()
    monkeypatch.setattr(docker, "stop_container", action)
    result = docker.container_stop("comfyui")
    assert result["code"] == "TELEMETRY_UNAVAILABLE"
    action.assert_not_called()


def test_pending_external_comfy_task_is_not_treated_as_idle(gpu_environment, monkeypatch):
    state, config = gpu_environment
    state["pending"] = [{"prompt_id": "external-long-id"}]
    release = Mock()
    monkeypatch.setattr(comfy, "free_memory", release)
    result = comfy.comfy_free()
    assert result["code"] == "SERVICE_BUSY"
    release.assert_not_called()


def test_startup_peak_unknown_or_insufficient_never_starts(gpu_environment, monkeypatch):
    state, config = gpu_environment
    action = Mock(return_value=(0, "started"))
    monkeypatch.setattr(docker, "container_action", action)
    monkeypatch.setattr(docker, "docker_containers", lambda **kwargs: [])
    del config["containers"][0]["startup_vram_gb"]
    assert "UNCALIBRATED_STARTUP" in docker.docker_action("comfyui", "start")[1]
    config["containers"][0]["startup_vram_gb"] = 20
    assert "BUDGET_REJECTED" in docker.docker_action("comfyui", "start")[1]
    action.assert_not_called()
    config["containers"][0]["startup_vram_gb"] = 1
    assert docker.docker_action("comfyui", "start")[0] == 0
    action.assert_called_once()


def test_execution_timeout_keeps_reservation_and_blocks_release(gpu_environment, monkeypatch):
    monkeypatch.setattr(queue, "_queue_submit_comfy", Mock(return_value=("prompt-id", None)))
    monkeypatch.setattr(queue, "_queue_wait", lambda *args: "uncertain")
    current = task()
    queue._run_task(current)
    assert current["status"] == "uncertain"
    assert coordinator.get_coordinator().snapshot()["active"]["prompt_id"] == "prompt-id"
    assert docker.free_all()["code"] == "RESOURCE_BUSY"


@pytest.mark.parametrize("failure_site", ["_queue_submit_comfy", "_queue_wait"])
def test_unexpected_execution_exception_keeps_ownership(gpu_environment, monkeypatch, failure_site):
    monkeypatch.setattr(queue, "_queue_submit_comfy", Mock(return_value=("prompt-id", None)))
    monkeypatch.setattr(queue, failure_site, Mock(side_effect=RuntimeError("unexpected adapter failure")))
    current = task()
    queue._run_task(current)
    assert current["status"] == "uncertain"
    assert current["ended"] is None
    assert coordinator.get_coordinator().snapshot()["active"]["phase"] == "uncertain"
    assert docker.free_all()["code"] == "RESOURCE_BUSY"


@pytest.mark.parametrize("terminal", [False, True])
def test_reconciliation_requires_matching_terminal_history(gpu_environment, monkeypatch, terminal):
    monkeypatch.setattr(queue, "_queue_submit_comfy", Mock(return_value=("prompt-id", None)))
    monkeypatch.setattr(queue, "_queue_wait", lambda *args: "uncertain")
    current = task()
    monkeypatch.setitem(queue._tasks, current["id"], current)
    queue._run_task(current)
    history = {"prompt-id": {"status": {"status_str": "success"}}} if terminal else {}
    monkeypatch.setattr("clients.comfyui_client._get", lambda path: (True, history, ""))
    result = coordinator.reconcile_uncertain()
    assert result["ok"] is terminal
    assert (coordinator.get_coordinator().snapshot()["active"] is None) is terminal
    assert current["status"] == ("done" if terminal else "uncertain")


@pytest.mark.parametrize("uncertain", [False, True])
def test_submission_rejection_vs_ambiguous_transport(gpu_environment, monkeypatch, uncertain):
    monkeypatch.setattr(queue, "_queue_submit_comfy", Mock(return_value=(None, {"message": "failure", "uncertain": uncertain})))
    current = task()
    queue._run_task(current)
    assert current["status"] == ("uncertain" if uncertain else "failed")
    assert bool(coordinator.get_coordinator().snapshot()["active"]) is uncertain


def test_cancel_request_does_not_drop_reservation_while_backend_runs(gpu_environment, monkeypatch):
    current = task()
    monkeypatch.setattr(queue, "_queue_submit_comfy", Mock(return_value=("prompt-id", None)))

    def wait(*args):
        current["cancel_requested"] = True
        assert coordinator.get_coordinator().snapshot()["active"]["phase"] == "running"
        return "done"

    monkeypatch.setattr(queue, "_queue_wait", wait)
    queue._run_task(current)
    assert current["status"] == "canceled"
    assert coordinator.get_coordinator().snapshot()["active"] is None


def test_rejected_lease_contains_explanation_and_blocker(gpu_environment):
    with coordinator.coordinated_operation(coordinator.OperationSpec("release", owner="manual-free")):
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(comfy.comfy_free).result(timeout=3)
        assert result["code"] == "RESOURCE_BUSY"
        assert result["coordination"]["blocker"]["owner"] == "manual-free"


def test_failed_optional_release_aborts_combo_before_load(gpu_environment, monkeypatch):
    state, config = gpu_environment
    config["ollama"]["combos"] = {"chat": {"stop": "all", "load": ["llm"]}}
    monkeypatch.setattr(scene, "ollama_tags", lambda: ["llm"])
    monkeypatch.setattr(scene, "ollama_stop_all", lambda: (-1, "release failed"))
    load = Mock()
    monkeypatch.setattr(scene, "load_model_api", load)
    assert scene.combo_switch("chat")["ok"] is False
    load.assert_not_called()


def test_legacy_optional_release_is_required_for_scene_transition(monkeypatch):
    monkeypatch.setitem(scene._STEP_HANDLERS, "vram_release", lambda *args: (-1, "failed"))
    result = scene._execute_step({"action": "vram_release", "critical": False}, {})
    assert result["critical"] is True
    assert result["rc"] == -1


def test_active_owner_does_not_make_uncalibrated_context_admissible(gpu_environment):
    with coordinator.coordinated_operation(coordinator.OperationSpec("release", owner="other-job")):
        result = coordinator.preview(coordinator.OperationSpec("load", "ollama", "llm", 12345))
        assert result["allowed"] is False
        assert coordinator.get_coordinator().snapshot()["active"]["owner"] == "other-job"


def test_docker_query_failure_blocks_mutation_instead_of_implying_idle(gpu_environment, monkeypatch):
    monkeypatch.setattr(docker, "docker_containers", docker_containers_original)
    monkeypatch.setattr("clients.docker_client.running_containers_status",
                        lambda: {"ok": False, "containers": [], "error": "daemon unavailable"})
    action = Mock()
    monkeypatch.setattr(docker, "stop_container", action)
    assert docker.container_stop("comfyui")["code"] == "ACTIVITY_UNKNOWN"
    action.assert_not_called()


docker_containers_original = docker.docker_containers


def test_generic_process_kill_cannot_bypass_ownership(gpu_environment, monkeypatch):
    from api.endpoints import process
    action = Mock()
    monkeypatch.setattr(process.subprocess, "run", action)
    with coordinator.coordinated_operation(coordinator.OperationSpec("release", owner="job")):
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(process.post_process_kill, Mock(body={})).result(timeout=3)
    assert response.status_code == 409
    action.assert_not_called()


@pytest.mark.parametrize("outcome", ["success", "rejected", "unknown"])
def test_real_model_load_handles_definitive_and_ambiguous_responses(gpu_environment, monkeypatch, outcome):
    import urllib.error
    if outcome == "success":
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        request = Mock(return_value=response)
    elif outcome == "rejected":
        request = Mock(side_effect=urllib.error.HTTPError("url", 400, "invalid", {}, None))
    else:
        request = Mock(side_effect=TimeoutError("response lost"))
    monkeypatch.setattr(scene.urllib.request, "urlopen", request)
    with coordinator.coordinated_operation(coordinator.OperationSpec("combo", "ollama", owner="combo")):
        rc, output = scene.load_model_api("llm", 8192)
        assert rc == (0 if outcome == "success" else -1)
        assert coordinator.get_coordinator().snapshot()["active"]["owner"] == "combo"
    request.assert_called_once()
    active = coordinator.get_coordinator().snapshot()["active"]
    assert bool(active) is (outcome == "unknown")
    if active:
        assert active["phase"] == "uncertain"


def test_submit_without_capability_does_not_call_backend(monkeypatch):
    request = Mock()
    monkeypatch.setattr(queue.urllib.request, "urlopen", request)
    with pytest.raises(ResourceDenied) as error:
        queue._queue_submit_comfy({})
    assert error.value.code == "INVALID_LEASE"
    request.assert_not_called()


def test_failed_post_release_model_query_is_not_success(gpu_environment, monkeypatch):
    state, config = gpu_environment
    config["gpu_guard"] = {"managed": [{"name": "ollama", "evict": "stop models"}]}
    monkeypatch.setattr(docker, "REGISTRY", config)
    state.update(used_mb=8192, free_mb=8192)
    monkeypatch.setattr(ollama, "ollama_ps", Mock(side_effect=[
        {"ok": True, "models": [{"name": "llm"}]}, {"ok": False, "models": []}]))

    def stop(names):
        state.update(used_mb=1024, free_mb=15360)
        return 0, "acknowledged"

    monkeypatch.setattr(ollama, "ollama_stop", stop)
    monkeypatch.setattr(docker.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(docker, "_get_memory_percent", lambda: 0)
    monkeypatch.setattr("gpu.monitor.gpu_processes", lambda: {"processes": []})
    result = docker.free_all()
    assert result["ok"] is False
    assert result["actions"][0]["ok"] is False


def test_memory_changed_after_assessment_is_rejected_before_submit(gpu_environment, monkeypatch):
    state, config = gpu_environment
    evaluate = queue._model_budget

    def before_submit(spec):
        state.update(used_mb=12288, free_mb=4096)
        return evaluate(spec)

    monkeypatch.setattr(queue, "_model_budget", before_submit)
    submit = Mock()
    monkeypatch.setattr(queue, "_queue_submit_comfy", submit)
    current = task()
    queue._run_task(current)
    assert current["status"] == "failed"
    submit.assert_not_called()


def test_acknowledged_release_without_reclaimed_memory_cannot_submit(gpu_environment, monkeypatch):
    state, config = gpu_environment
    state.update(used_mb=8192, free_mb=8192, loaded=[{"name": "other", "size_gb": 6}])
    monkeypatch.setattr("engine.eviction_guard.gpu_guard_evict", lambda: {"ok": True})
    monkeypatch.setattr(coordinator.time, "monotonic", Mock(side_effect=[0, 6]))
    submit = Mock()
    monkeypatch.setattr(queue, "_queue_submit_comfy", submit)
    current = task()
    queue._run_task(current)
    assert current["status"] == "failed"
    assert current["coordination"]["code"] == "RELEASE_UNVERIFIED"
    submit.assert_not_called()
