"""Register every HTTP endpoint when the dispatcher imports this package."""
from api.router import router
from . import (
    admission, alerts, auth_endpoints, diagnose, events, guard, logs,
    observability, process, qos, queue, registry, scene, service, status,
    stream, system_info, topology, vram,
)

__all__ = ["router"]
