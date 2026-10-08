"""Bind the ownership ledger to fresh telemetry and existing service adapters."""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from functools import wraps
import inspect
import math
import time
import uuid
from typing import Callable, Iterator
from core.config import REGISTRY
from core.config import BASE_DIR
import os
from core.registry import registry
from core.resource_coordinator import ResourceCoordinator, ResourceDenied, ResourceLease, ResourceRequest
from core.logger import log_event
from gpu.monitor import gpu_status


@dataclass(frozen=True)
class OperationSpec:
    """Trusted intent; model peak is always resolved from the registry/budget."""

    operation: str
    service: str = "all"
    model: str | None = None
    ctx: int | None = None
    owner: str | None = None
    command_only: bool = False


def get_coordinator() -> ResourceCoordinator:
    """Get the one process-wide ledger, owned by StateRegistry."""
    with registry.lock("resource_coordinator_init"):
        coordinator = registry.get("resource_coordinator")
        if coordinator is None:
            coordinator = ResourceCoordinator()
            registry.set("resource_coordinator", coordinator)
        return coordinator


def restore_resource_operations():
    """Enable write-ahead tracking and recover holds before any startup worker."""
    from core.operation_journal import OperationJournal
    with registry.lock('operation_journal_init'):
        if registry.get('operation_journal') is not None:
            return
        journal = OperationJournal(os.environ.get('GMAE_TASK_DB', os.path.join(BASE_DIR, 'data', 'tasks.sqlite3')))
        for record in journal.pending():
            intent = record['intent']
            if intent['operation'] == 'generate' and intent['owner'].startswith('job:'):
                task = journal.store.get(intent['owner'][4:])
                if task and task['status'] in ('submitting', 'running', 'uncertain'):
                    # The task's durable correlation ID is the stronger recovery
                    # record. queue_restore installs its hold; avoid duplication.
                    continue
                if task and task['status'] in journal.store.TERMINAL:
                    journal.finish(record['id'], True, {'terminal_task': task['id']})
                    continue
            get_coordinator().restore_uncertain(
                ResourceRequest(intent['operation'], intent['owner'], intent['service'], intent.get('model')),
                {'journal_id': record['id'],
                 **{key: record['evidence'][key] for key in ('prompt_id', 'job_id') if key in record['evidence']},
                 'reason': '资源操作在进程退出前未确认结束，须独立核验'})
        registry.set('operation_journal', journal)


class _TrackedLease(ResourceLease):
    """Persist immediately before the first adapter mutation phase."""
    def __init__(self, lease, journal, request, command_only=False):
        super().__init__(lease.coordinator, lease.token, lease.borrowed)
        self.journal = journal
        self.request = request
        self.operation_id = None
        self.command_only = command_only

    def transition(self, phase, **details):
        if (self.journal is not None and not self.borrowed and self.operation_id is None and
                phase in ('running', 'releasing', 'stopping')):
            self.operation_id = self.journal.begin({**asdict(self.request), 'command_only': self.command_only})
        if self.operation_id:
            details['journal_id'] = self.operation_id
        super().transition(phase, **details)

    def checkpoint_end(self, exception=False):
        if self.operation_id is None:
            return
        active = self.coordinator.snapshot()['active']
        confirmed = not exception and active is not None and active['phase'] in ('completed', 'failed')
        if not confirmed:
            self.uncertain((active or {}).get('reason') or '资源操作未确认结束，保留预留')
        try:
            self.journal.finish(self.operation_id, confirmed, active or {})
        except Exception:
            self.uncertain('资源操作结束记录无法保存，保留预留')
            raise


def fresh_gpu() -> dict:
    """Reject absent, stale or malformed readings instead of inventing capacity."""
    gpu = gpu_status(force_refresh=True)
    try:
        total, used, free = (int(gpu[k]) for k in ("total_mb", "used_mb", "free_mb"))
        valid = total > 0 and 0 <= used <= total and 0 <= free <= total
    except (KeyError, TypeError, ValueError, OverflowError):
        valid = False
    if not gpu.get("ok") or gpu.get("stale") or not valid:
        raise ResourceDenied("TELEMETRY_UNAVAILABLE", "新鲜 GPU 遥测不可用，暂停资源操作")
    return {**gpu, "used_mb": max(used, total - free)}


def check_idle(service: str) -> None:
    """Protect known running work; missing Comfy queue telemetry is not idle."""
    from services.docker import docker_containers
    from services.comfy import comfy_queue
    containers = docker_containers(strict=True)
    if service in ("all", "comfyui") and "comfyui" in containers:
        queue = comfy_queue()
        if not queue.get("ok"):
            raise ResourceDenied("ACTIVITY_UNKNOWN", "ComfyUI 执行状态不可用，不能加载或释放")
        running = queue.get("running_count", len(queue.get("running", [])))
        pending = queue.get("pending_count", len(queue.get("pending", [])))
        if running or pending:
            raise ResourceDenied("SERVICE_BUSY", "ComfyUI 存在运行或排队任务，等待执行结束")


def _model_budget(spec: OperationSpec, allow_rejected: bool = False) -> tuple[dict, dict]:
    from engine.budget import budget_engine
    context = {spec.model: spec.ctx} if spec.ctx is not None else None
    result = budget_engine(context, force_refresh=True)
    item = next((m for m in result.get("models", [])
                 if m.get("id") == spec.model and m.get("source") == spec.service), None)
    if not result.get("ok") or item is None:
        raise ResourceDenied("BUDGET_UNAVAILABLE", result.get("error") or "模型未登记或预算缺失")
    context_size = spec.ctx if spec.ctx is not None else item.get("default_ctx", 0)
    if spec.service == "ollama" and context_size > 8192:
        raise ResourceDenied("CONTEXT_LIMIT", "现行显存指南禁止 num_ctx 超过 8192")
    # Capacity is necessary but does not override the project's residency rules.
    # Unknown resident profiles cannot prove that a second large model is safe.
    other_residents = [m for m in result.get("loaded_models", [])
                       if (m.get("source"), m.get("id")) != (spec.service, spec.model)]
    target_large = item.get("vram_gb", 0) >= 5
    conflict = any(m.get("exclusive") or item.get("exclusive") or
                   (target_large and (m.get("vram_gb", 0) >= 5 or m.get("vram_gb", 0) <= 0))
                   for m in other_residents)
    if conflict and item.get("decision") == "ok":
        item = {**item, "decision": "free_L2" if spec.service == "comfyui" else "free_L1",
                "note": "常驻互斥规则要求先释放冲突模型，之后重新核验"}
    if item.get("decision") == "reject" and not allow_rejected:
        raise ResourceDenied("BUDGET_REJECTED", item.get("note", "显存预算不足"), {"budget": item})
    return result, item


def _assess_model(spec: OperationSpec, lease: ResourceLease) -> None:
    result, item = _model_budget(spec)
    peak_mb = math.ceil(float(item["vram_gb"]) * 1024)
    lease.transition("reserved", peak_mb=peak_mb, target_model=spec.model, budget=item)
    if item["decision"].startswith("free"):
        from engine.eviction_guard import gpu_guard_evict
        check_idle("all")
        lease.transition("releasing", reason=item.get("note"))
        released = gpu_guard_evict()
        if not released.get("ok"):
            raise ResourceDenied("RELEASE_FAILED", "显存释放失败，未提交目标负载", {"release": released})
        lease.transition("verifying")
        deadline = time.monotonic() + 5
        while True:
            result, item = _model_budget(spec)
            if item.get("decision") == "ok":
                break
            if time.monotonic() >= deadline:
                raise ResourceDenied("RELEASE_UNVERIFIED", "释放后显存仍未达到预算要求", {"budget": item})
            time.sleep(0.25)
    # A second reading is mandatory even if no release was needed.
    result, item = _model_budget(spec)
    if item.get("decision") != "ok":
        raise ResourceDenied("ADMISSION_CHANGED", "执行前预算发生变化，等待重新准入", {"budget": item})
    lease.transition("reserved", budget=item, available_mb=round(result.get("avail_gb", 0) * 1024))


def _assess_start(spec: OperationSpec, lease: ResourceLease, gpu: dict) -> None:
    config = next((c for c in REGISTRY.get("containers", []) if c.get("name") == spec.service), None)
    if config is None:
        raise ResourceDenied("UNREGISTERED_SERVICE", "服务未登记，拒绝启动: " + spec.service)
    from services.docker import docker_containers
    if spec.operation == "start" and spec.service in docker_containers(strict=True):
        return  # Already running; Docker start is idempotent.
    try:
        peak_gb = float(config["startup_vram_gb"])
        reserve_gb = float(REGISTRY.get("system", {}).get("vram_reserve_gb", 2.5))
        if not math.isfinite(peak_gb) or peak_gb < 0 or not math.isfinite(reserve_gb) or reserve_gb < 0:
            raise ValueError("invalid startup profile")
    except (KeyError, TypeError, ValueError):
        raise ResourceDenied("UNCALIBRATED_STARTUP", "服务启动峰值未校准，请登记 startup_vram_gb")
    peak_mb = math.ceil(peak_gb * 1024)
    if gpu["used_mb"] + peak_mb + math.ceil(reserve_gb * 1024) > gpu["total_mb"]:
        raise ResourceDenied("BUDGET_REJECTED", "服务启动峰值与当前占用超过安全容量")
    lease.transition("reserved", peak_mb=peak_mb, available_mb=gpu["free_mb"])


def assess(spec: OperationSpec, lease: ResourceLease) -> None:
    """Assess while holding ownership, before executing any managed mutation."""
    gpu = fresh_gpu()
    check_idle("all" if spec.operation in ("scene", "combo", "generate", "load") else spec.service)
    if spec.operation in ("load", "generate"):
        _assess_model(spec, lease)
    elif spec.operation in ("start", "restart", "unpause"):
        _assess_start(spec, lease, gpu)
    lease.transition("reserved", telemetry={k: gpu[k] for k in ("total_mb", "used_mb", "free_mb")})


@contextmanager
def coordinated_operation(spec: OperationSpec) -> Iterator[ResourceLease]:
    """Acquire before preflight and keep ownership until the outer operation ends."""
    coordinator = get_coordinator()
    request = ResourceRequest(spec.operation, spec.owner or (spec.operation + ":" + uuid.uuid4().hex[:10]),
                              spec.service, spec.model)
    journal = registry.get('operation_journal')
    tracked = None

    def assessed(lease):
        nonlocal tracked
        tracked = _TrackedLease(lease, journal, request, spec.command_only)
        try:
            assess(spec, tracked)
        except BaseException:
            tracked.checkpoint_end(exception=True)
            raise

    try:
        with coordinator.operation(request, assessed) as lease:
            exception = True
            try:
                log_event("resource_reserved", owner=request.owner, token=lease.token,
                          operation=spec.operation, service=spec.service, model=spec.model)
                yield tracked
                exception = False
            finally:
                tracked.checkpoint_end(exception=exception)
    except ResourceDenied as error:
        log_event("resource_rejected", owner=request.owner, code=error.code, reason=str(error))
        raise


def coordinated(factory: Callable[[dict], OperationSpec | None], shape: str = "dict") -> Callable:
    """Route service mutations through the same ledger; preserve legacy return shapes."""
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapper(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            spec = factory(bound.arguments)
            if spec is None:
                return function(*args, **kwargs)
            try:
                with coordinated_operation(spec) as lease:
                    lease.transition("releasing" if spec.operation == "release" else "running")
                    result = function(*args, **kwargs)
                    ok = result is None or (result.get("ok", False) if isinstance(result, dict) else result[0] == 0)
                    if get_coordinator().snapshot()["active"]["phase"] != "uncertain":
                        lease.transition("completed" if ok else "failed")
                    return result
            except ResourceDenied as error:
                if shape == "tuple":
                    return -1, error.code + ": " + str(error)
                return error.result()
        wrapper.resource_coordinated = True
        return wrapper
    return decorate


def preview(spec: OperationSpec) -> dict:
    """Explain current admission without reserving resources or running release."""
    try:
        gpu = fresh_gpu()
        result, item = _model_budget(spec, allow_rejected=True)
        active = get_coordinator().snapshot()["active"]
        reason = item.get("note", "")
        decision = item["decision"]
        if decision == "reject":
            context = item.get("specified_ctx")
            context_map = item.get("context_vram", {})
            if context and context not in context_map and str(context) not in context_map:
                raise ResourceDenied("BUDGET_REJECTED", reason, {"budget": item})
            peak = item.get("vram_gb", 0)
            config = REGISTRY.get("system", {})
            minimum = (peak + float(config.get("gpu_base_noise_gb", 1))
                       + float(config.get("vram_reserve_gb", 2.5))) * 1024
            if not active or peak <= 0 or minimum > gpu["total_mb"]:
                raise ResourceDenied("BUDGET_REJECTED", reason, {"budget": item})
        if active:
            decision = "waiting_resource"
            reason = "等待 %s 执行结束或状态核验；之后重新读取显存并准入" % active["owner"]
        return {"ok": True, "allowed": True, "execution_ready": not active and item["decision"] == "ok",
                "decision": decision, "reason": reason, "budget": item, "blocker": active,
                "available_gib": result.get("avail_gb"), "reserve_gib": result.get("reserve_gb"),
                "note": "预览不预留资源；实际执行必须重新准入。峰值仅适用于登记配置。"}
    except ResourceDenied as error:
        return {**error.result(), "allowed": False, "reason": str(error)}


def reconcile_uncertain() -> dict:
    """Resolve only a matching terminal Comfy history record, never an empty queue."""
    coordinator = get_coordinator()
    active = coordinator.snapshot()["active"]
    if not active or active["phase"] != "uncertain":
        return {"ok": True, "resolved": False, "message": "没有待核验的执行"}
    prompt_id = active.get("prompt_id")
    if active.get("service") != "comfyui" or not prompt_id:
        if active.get('journal_id'):
            return _reconcile_command_operation(coordinator, active)
        return {"ok": False, "code": "UNCONFIRMED_EXECUTION",
                "error": "该后端未提供可核验的任务结束记录，资源预留继续保留"}
    from clients.comfyui_client import _get
    from urllib.parse import quote
    ok, history, error = _get("/history/" + quote(prompt_id, safe=""))
    record = history.get(prompt_id, {}) if ok and isinstance(history, dict) else {}
    if not isinstance(record, dict):
        record = {}
    status = record.get('status', {}).get('status_str')
    terminal = status in ('success', 'error')
    if not terminal and active.get('job_id'):
        from engine.queue import cancellation_evidence
        from clients.comfyui_client import canceled_job_absent
        if (cancellation_evidence(active['job_id'], active['token'], prompt_id) and
                canceled_job_absent(prompt_id)):
            terminal, status = True, 'canceled'
    if not terminal:
        return {"ok": False, "code": "UNCONFIRMED_EXECUTION",
                "error": error or "尚无对应任务的结束记录，资源预留继续保留"}
    try:
        fresh_gpu()
        from engine.queue import reconcile_task
        if active.get('job_id') and not reconcile_task(
                active['job_id'], active['token'], prompt_id, status):
            return {'ok': False, 'code': 'TASK_EVIDENCE_MISMATCH', 'error': '任务身份不匹配，保留预留'}
        if active.get('journal_id'):
            journal = registry.get('operation_journal')
            if journal is None:
                return {'ok': False, 'code': 'TASK_STORAGE_UNAVAILABLE', 'error': '资源操作账本不可用'}
            journal.finish(active['journal_id'], True, {'terminal': True, 'prompt_id': prompt_id, 'status': status})
        coordinator.resolve(active["token"], {"terminal": True, "prompt_id": prompt_id,
                                             "status": status})
        log_event("resource_reconciled", owner=active["owner"], prompt_id=prompt_id)
        return {"ok": True, "resolved": True, "prompt_id": prompt_id}
    except ResourceDenied as error:
        return error.result()
    except Exception as error:
        return {'ok': False, 'code': 'TASK_STORAGE_UNAVAILABLE', 'error': str(error)}


def reconcile_recovered_operations(limit=32):
    """Bounded startup reconciliation; no watchdog and no blind replay."""
    results = []
    for _ in range(limit):
        active = get_coordinator().snapshot()['active']
        if not active or active['phase'] != 'uncertain':
            break
        result = reconcile_uncertain()
        results.append(result)
        if not result.get('resolved'):
            break
    return results


def _reconcile_command_operation(coordinator, active):
    """Confirm interrupted single-container control only from owned receipts.

    This proves completion of the original control command, not GPU idleness.
    A new operation still passes ordinary fresh admission. Mixed operations,
    scripts, container exec and unconfirmed/nonzero receipts remain blocked.
    """
    try:
        journal = registry.get('operation_journal')
        record = journal.get(active['journal_id']) if journal else None
        if not record or record['intent'].get('command_only') is not True:
            raise ResourceDenied('UNCONFIRMED_EXECUTION', '该操作不具备完整独立命令回执，继续保留预留')
        intent = record['intent']
        if any(intent.get(key) != active.get(key) for key in ('owner', 'operation', 'service', 'model')):
            raise ResourceDenied('UNCONFIRMED_EXECUTION', '操作日志身份不匹配')
        commands = journal.commands(record['id'])
        if len(commands) != 1 or commands[0]['state'] != 'confirmed' or commands[0]['return_code'] != 0:
            raise ResourceDenied('UNCONFIRMED_EXECUTION', '命令仍未确认成功，不能解除预留')
        args = commands[0]['intent']
        permitted = {'start': {'start'}, 'restart': {'restart'}, 'unpause': {'unpause'}, 'release': {'stop', 'pause'}}
        if (len(args) != 3 or os.path.basename(args[0]).lower() not in ('docker', 'docker.exe') or
                args[1] not in permitted.get(intent['operation'], set()) or
                args[2] != intent['service'] or args[2] not in ('comfyui', 'ollama', 'fooocus')):
            raise ResourceDenied('UNCONFIRMED_EXECUTION', '回执不属于支持核验的单条容器控制命令')
        fresh_gpu()
        evidence = {'terminal': True, 'operation_id': record['id'], 'command_id': commands[0]['id'],
                    'status': 'interrupted_operation_command_completed'}
        if record['state'] != 'confirmed':
            journal.finish(record['id'], True, evidence)
        coordinator.resolve(active['token'], evidence)
        return {'ok': True, 'resolved': True, 'operation_id': record['id'],
                'note': '原容器控制命令已结束；中断流程未重放，后续操作仍须重新准入'}
    except ResourceDenied as error:
        return error.result()
    except Exception as error:
        return {'ok': False, 'code': 'TASK_STORAGE_UNAVAILABLE', 'error': str(error)}
