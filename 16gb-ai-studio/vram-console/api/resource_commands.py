"""Dispatch GPU-changing endpoints to a bounded worker while preserving responses."""
from concurrent.futures import TimeoutError
from functools import wraps
from api.response import Response
from core.registry import registry
from core.resource_worker import ResourceCommandWorker
from core.resource_coordinator import ResourceDenied
from engine.coordinator import get_coordinator

COMMAND_RESPONSE_TIMEOUT_S = 90


def get_command_worker() -> ResourceCommandWorker:
    """Return the single command executor held by StateRegistry."""
    with registry.lock("resource_command_worker_init"):
        worker = registry.get("resource_command_worker")
        if worker is None:
            worker = ResourceCommandWorker()
            registry.set("resource_command_worker", worker)
        return worker


def resource_command(function):
    """Read request data on the handler, execute its GPU intent on the worker."""
    @wraps(function)
    def wrapper(req):
        req.body  # Consume the stream before the worker takes this immutable request view.
        active = get_coordinator().snapshot()["active"]
        if active:
            return Response.from_result(ResourceDenied("RESOURCE_BUSY",
                "资源由 %s 持有（%s），等待结束或状态核验" % (active["owner"], active["phase"]),
                {"blocker": active}).result())
        try:
            future = get_command_worker().submit(lambda: function(req))
            return future.result(timeout=COMMAND_RESPONSE_TIMEOUT_S)
        except ResourceDenied as error:
            return Response.from_result(error.result())
        except TimeoutError:
            # Do not cancel: it may already be executing. Its lifetime lease
            # still guards the GPU after this HTTP response ends.
            return Response.error("COMMAND_STILL_RUNNING", "请求等待超时；资源操作仍在执行，请查询资源状态",
                                  details={"coordination": get_coordinator().snapshot()}, http_status=503)
    wrapper.resource_command = True
    return wrapper
