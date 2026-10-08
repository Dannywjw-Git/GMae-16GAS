"""Ownership invariants tested against real threads, without GPU/network access."""
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from core.resource_coordinator import ResourceCoordinator, ResourceDenied, ResourceRequest


def request(owner="job-a", peak_mb=8192):
    return ResourceRequest("generate", owner, "comfyui", "SDXL", peak_mb)


@pytest.mark.parametrize("field", ["token", "owner", "operation", "service", "model", "phase"])
def test_transition_cannot_overwrite_lease_identity(field):
    coordinator = ResourceCoordinator()
    with coordinator.operation(request()) as lease:
        before = coordinator.snapshot()["active"]
        with pytest.raises(ValueError, match="identity"):
            lease.transition("running", **{field: "forged"}) if field != "phase" else coordinator.transition(lease.token, "running", {field: "forged"})
        assert coordinator.snapshot()["active"] == before


def test_concurrent_requests_cannot_reserve_same_gpu():
    coordinator = ResourceCoordinator()
    entered, finish = threading.Event(), threading.Event()

    def first():
        with coordinator.operation(request()):
            entered.set()
            assert finish.wait(3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(first)
        assert entered.wait(3)
        try:
            with pytest.raises(ResourceDenied, match="job-a") as error:
                with coordinator.operation(request("job-b")):
                    pytest.fail("second execution entered")
            assert error.value.code == "RESOURCE_BUSY"
            assert coordinator.snapshot()["reserved_mb"] == 8192
        finally:
            finish.set()
        future.result(timeout=3)
    assert coordinator.snapshot()["active"] is None


def test_assessment_already_holds_reservation_and_does_not_block_readers():
    coordinator = ResourceCoordinator()
    entered, finish = threading.Event(), threading.Event()

    def assess(lease):
        entered.set()
        assert finish.wait(3)

    def first():
        with coordinator.operation(request(), assess):
            pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(first)
        assert entered.wait(3)
        try:
            assert coordinator.snapshot()["active"]["phase"] == "assessing"
            with pytest.raises(ResourceDenied):
                with coordinator.operation(request("job-b")):
                    pass
        finally:
            finish.set()
        future.result(timeout=3)


def test_nested_release_borrows_owner_and_cannot_drop_root_reservation():
    coordinator = ResourceCoordinator()
    with coordinator.operation(request()) as root:
        with coordinator.operation(ResourceRequest("release", "nested")) as nested:
            assert nested.borrowed and nested.token == root.token
        assert coordinator.snapshot()["active"]["token"] == root.token
    assert coordinator.snapshot()["active"] is None


def test_snapshot_cannot_mutate_ledger_or_event_history():
    coordinator = ResourceCoordinator()
    with coordinator.operation(request()):
        snapshot = coordinator.snapshot()
        snapshot["active"]["peak_mb"] = 0
        snapshot["events"].clear()
        assert coordinator.snapshot()["reserved_mb"] == 8192
        assert coordinator.snapshot()["events"]


def test_assessment_failure_releases_without_executing():
    coordinator = ResourceCoordinator()

    def reject(lease):
        raise ResourceDenied("STALE_TELEMETRY", "stale")

    with pytest.raises(ResourceDenied):
        with coordinator.operation(request(), reject):
            pytest.fail("rejected operation executed")
    assert coordinator.snapshot()["active"] is None


def test_exception_releases_normal_reservation():
    coordinator = ResourceCoordinator()
    with pytest.raises(ValueError):
        with coordinator.operation(request()):
            raise ValueError("failed before execution")
    assert coordinator.snapshot()["active"] is None


def test_timeout_retains_reservation_until_terminal_evidence():
    coordinator = ResourceCoordinator()
    with coordinator.operation(request()) as lease:
        lease.transition("running", prompt_id="full-prompt-id")
        lease.uncertain("history unavailable", prompt_id="full-prompt-id")
    active = coordinator.snapshot()["active"]
    assert active["phase"] == "uncertain"
    with pytest.raises(ResourceDenied):
        with coordinator.operation(request("next")):
            pass
    with pytest.raises(ResourceDenied):
        coordinator.resolve(lease.token, {"terminal": False})
    with pytest.raises(ResourceDenied):
        lease.transition("completed")
    with pytest.raises(ResourceDenied):
        coordinator.resolve(lease.token, {"terminal": True, "prompt_id": "different-job"})
    coordinator.resolve(lease.token, {"terminal": True, "prompt_id": "full-prompt-id"})
    assert coordinator.snapshot()["active"] is None


def test_old_token_cannot_release_or_modify_new_owner():
    coordinator = ResourceCoordinator()
    with coordinator.operation(request()) as old:
        pass
    with coordinator.operation(request("new")) as new:
        with pytest.raises(ResourceDenied):
            coordinator.transition(old.token, "completed")
        assert coordinator.snapshot()["active"]["token"] == new.token


def test_decision_events_are_ordered_and_bounded():
    coordinator = ResourceCoordinator(clock=lambda: 1.0)
    for _ in range(100):
        with coordinator.operation(request()):
            pass
    events = coordinator.snapshot()["events"]
    assert len(events) == coordinator.EVENT_LIMIT
    assert [e["sequence"] for e in events] == sorted(e["sequence"] for e in events)
