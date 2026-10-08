"""Ownership, trusted preview and evidence-based reconciliation endpoints."""
from api.router import router
from api.request import Request
from api.response import Response
from engine.coordinator import OperationSpec, get_coordinator, preview, reconcile_uncertain


@router.get("/api/coordinator")
def get_coordination(req: Request) -> Response:
    """Read ownership even when GPU telemetry is unavailable."""
    return Response.success(get_coordinator().snapshot())


@router.post("/api/coordinator/preview")
def post_preview(req: Request) -> Response:
    """Only model identity/context are inputs; caller-provided capacity is ignored."""
    source = req.body_get("source", "comfyui")
    if source not in ("comfyui", "ollama"):
        return Response.error("BAD_REQUEST", "不支持的模型后端")
    context = req.body_get("ctx")
    if context is not None and (isinstance(context, bool) or not isinstance(context, int) or context <= 0):
        return Response.error("BAD_REQUEST", "ctx 必须是正整数")
    return Response.from_result(preview(OperationSpec("generate" if source == "comfyui" else "load",
                               source, req.body_get("model", ""), context)))


@router.post("/api/coordinator/reconcile")
def post_reconcile(req: Request) -> Response:
    """Client cannot supply terminal evidence or arbitrarily clear a reservation."""
    req.body  # Consume the request stream; never use it as terminal evidence.
    return Response.from_result(reconcile_uncertain())
