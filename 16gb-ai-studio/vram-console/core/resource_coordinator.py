"""Single-GPU ownership ledger, independent of HTTP, GPU and service adapters."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
import threading
import time
import uuid
from typing import Callable, Iterator


@dataclass(frozen=True)
class ResourceRequest:
    """An intent; peak MiB is filled from trusted profiles, never HTTP callers."""

    operation: str
    owner: str
    service: str = "all"
    model: str | None = None
    peak_mb: int = 0


class ResourceDenied(RuntimeError):
    """A rejected intent with a stable code and an explainable snapshot."""

    def __init__(self, code: str, reason: str, details: dict | None = None):
        super().__init__(reason)
        self.code = code
        self.details = details or {}

    def result(self) -> dict:
        """Return the service/API representation of this rejection."""
        return {"ok": False, "code": self.code, "error": str(self),
                "busy": self.code == "RESOURCE_BUSY", "coordination": deepcopy(self.details)}


class ResourceLease:
    """A capability owned by one operation until execution is confirmed terminal."""

    def __init__(self, coordinator: "ResourceCoordinator", token: str, borrowed: bool):
        self.coordinator = coordinator
        self.token = token
        self.borrowed = borrowed

    def transition(self, phase: str, **details) -> None:
        """Record progress without relinquishing the reservation."""
        self.coordinator.transition(self.token, phase, details)

    def uncertain(self, reason: str, **details) -> None:
        """Retain ownership when timeout/transport failure leaves execution unknown."""
        self.transition("uncertain", reason=reason, **details)


class ResourceCoordinator:
    """Serialize managed GPU mutations and keep immutable read snapshots.

    MVP deliberately admits one operation at a time, including its full task
    lifetime. Slow adapter calls happen outside the ledger lock, so readers and
    rejected callers stay responsive. Nested calls borrow only the calling
    thread's capability, never another caller's reservation.
    """

    PHASES = frozenset({"assessing", "reserved", "releasing", "verifying",
                        "running", "stopping", "failed", "completed", "uncertain"})
    EVENT_LIMIT = 256

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._lock = threading.RLock()
        self._local = threading.local()
        self._clock = clock
        self._active: dict | None = None
        self._events: list[dict] = []
        self._sequence = 0
        self._recovered = []

    def restore_uncertain(self, request: ResourceRequest, details: dict) -> ResourceLease:
        """Install a trusted startup hold without executing or assessing a job.

        Multiple crash records remain blocked until each has terminal evidence;
        resolve moves to the next hold under the same lock, without a free gap.
        """
        with self._lock:
            token = uuid.uuid4().hex
            record = {**deepcopy(details), **asdict(request), 'token': token,
                      'phase': 'uncertain', 'started_monotonic_s': self._clock()}
            if self._active is None:
                self._active = record
            elif self._active['phase'] == 'uncertain':
                self._recovered.append(record)
            else:
                raise ResourceDenied('RESOURCE_BUSY', '恢复前已有正在执行的资源预留')
            self._record('restored', token=token, owner=request.owner)
            return ResourceLease(self, token, False)

    def _record(self, event: str, **details) -> None:
        self._sequence += 1
        self._events.append({"sequence": self._sequence, "monotonic_s": self._clock(),
                             "event": event, **deepcopy(details)})
        self._events = self._events[-self.EVENT_LIMIT:]

    def snapshot(self) -> dict:
        """Return isolated ownership, reservation and bounded decision history."""
        with self._lock:
            return deepcopy({"gpu_id": 0, "policy": "serial", "active": self._active,
                             "reserved_mb": (self._active or {}).get("peak_mb", 0),
                             "sequence": self._sequence, "events": self._events,
                             "recovery_pending": self._recovered})

    def current_token(self) -> str | None:
        """Return only this thread's live capability, if any."""
        with self._lock:
            token = getattr(self._local, "token", None)
            return token if self._active and self._active["token"] == token else None

    def _acquire(self, request: ResourceRequest) -> ResourceLease:
        with self._lock:
            token = self.current_token()
            if self._active:
                if token and self._active["phase"] != "uncertain":
                    return ResourceLease(self, token, True)
                blocker = deepcopy(self._active)
                reason = "GPU 资源由 %s 持有（%s），等待执行结束或状态核验" % (
                    blocker["owner"], blocker["phase"])
                self._record("rejected", owner=request.owner, reason=reason,
                             code="RESOURCE_BUSY", blocker=blocker["token"])
                raise ResourceDenied("RESOURCE_BUSY", reason, {"blocker": blocker})
            token = uuid.uuid4().hex
            self._active = {**asdict(request), "token": token, "phase": "assessing",
                            "started_monotonic_s": self._clock()}
            self._record("acquired", **self._active)
            return ResourceLease(self, token, False)

    def transition(self, token: str, phase: str, details: dict | None = None) -> None:
        """Update a live capability; unknown phases/tokens cannot mutate ownership."""
        if phase not in self.PHASES:
            raise ValueError("unknown coordination phase: " + phase)
        with self._lock:
            if not self._active or self._active["token"] != token:
                raise ResourceDenied("INVALID_LEASE", "资源预留已失效")
            if self._active["phase"] == "uncertain" and phase != "uncertain":
                raise ResourceDenied("UNCONFIRMED_EXECUTION", "状态未知的预留只能凭结束证据解除")
            protected = {"token", "owner", "operation", "service", "model", "started_monotonic_s", "phase"}
            if any(value != self._active.get(key) for key, value in (details or {}).items() if key in protected):
                raise ValueError("lease identity cannot be changed by transition metadata")
            self._active = {**self._active, **deepcopy(details or {}), "phase": phase}
            self._record("transition", token=token, owner=self._active["owner"],
                         phase=phase, details=details or {})

    def _finish(self, token: str, outcome: str) -> None:
        with self._lock:
            if not self._active or self._active["token"] != token:
                return
            if self._active["phase"] == "uncertain":
                self._record("retained", token=token, reason=self._active.get("reason"))
                return
            self._record("released", token=token, owner=self._active["owner"], outcome=outcome)
            self._active = None

    def resolve(self, token: str, evidence: dict) -> None:
        """Release uncertain ownership only after a trusted adapter proves termination."""
        with self._lock:
            if not self._active or self._active["token"] != token or self._active["phase"] != "uncertain":
                raise ResourceDenied("INVALID_LEASE", "没有对应的待核验任务")
            if evidence.get("terminal") is not True:
                raise ResourceDenied("UNCONFIRMED_EXECUTION", "执行结束尚未得到确认")
            if self._active.get("prompt_id") and evidence.get("prompt_id") != self._active["prompt_id"]:
                raise ResourceDenied("UNCONFIRMED_EXECUTION", "结束证据不属于当前任务")
            self._record("resolved", token=token, evidence=evidence)
            self._active = self._recovered.pop(0) if self._recovered else None

    @contextmanager
    def operation(self, request: ResourceRequest,
                  assess: Callable[[ResourceLease], None] | None = None) -> Iterator[ResourceLease]:
        """Atomically own the GPU before assessment and keep it through adapter calls.

        Assessment may raise ResourceDenied; exceptions release ordinary leases,
        while explicitly uncertain executions remain reserved for reconciliation.
        """
        lease = self._acquire(request)
        previous = getattr(self._local, "token", None)
        self._local.token = lease.token
        outcome = "completed"
        try:
            if assess:
                assess(lease)
            if not lease.borrowed:
                lease.transition("reserved")
            yield lease
        except BaseException:
            outcome = "failed"
            raise
        finally:
            self._local.token = previous
            if not lease.borrowed:
                self._finish(lease.token, outcome)
