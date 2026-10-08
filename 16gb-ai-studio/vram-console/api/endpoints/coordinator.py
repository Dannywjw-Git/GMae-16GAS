"""Ownership, trusted preview and evidence-based reconciliation endpoints."""
from api.router import router
from api.request import Request
from api.response import Response
from engine.coordinator import OperationSpec, get_coordinator, preview, reconcile_uncertain
from core.resource_coordinator import ResourceDenied


@router.get("/api/coordinator")
def get_coordination(req: Request) -> Response:
    """Read ownership even when GPU telemetry is unavailable."""
    return Response.success(get_coordinator().snapshot())


@router.post("/api/coordinator/preview")
def post_preview(req: Request) -> Response:
    """Bind requested controls; caller-provided capacity/profile peaks are ignored."""
    source = req.body_get("source", "comfyui")
    if source not in ("comfyui", "ollama"):
        return Response.error("BAD_REQUEST", "不支持的模型后端")
    context = req.body_get("ctx")
    if context is not None and (isinstance(context, bool) or not isinstance(context, int) or context <= 0):
        return Response.error("BAD_REQUEST", "ctx 必须是正整数")
    model = req.body_get('model', '')
    workflow, reference = None, None
    if source == 'comfyui' and req.body_get('params') is not None:
        from engine.queue import REGISTRY, _load_workflow, _apply_params
        from engine.profile_admission import select_profile
        from core.workload_profile import resource_configuration_fingerprint
        try:
            entry = next((item for item in REGISTRY.get('comfyui', {}).get('models', []) if item['id'] == model), None)
            if not entry or not entry.get('workflow'):
                raise ValueError('模型工作流未登记')
            template = _load_workflow(entry['workflow'])
            if not template:
                raise ValueError('模型工作流缺失')
            workflow = _apply_params(template, req.body_get('params'))
            reference = select_profile(workflow)
            if (reference is None and resource_configuration_fingerprint(workflow) !=
                    resource_configuration_fingerprint(template)):
                raise ResourceDenied('PROFILE_REQUIRED', '参数缺少匹配测量证据，不能预演固定预算')
        except ResourceDenied as error:
            return Response.from_result({**error.result(), 'allowed': False})
        except ValueError as error:
            return Response.error('BAD_REQUEST', str(error))
    return Response.from_result(preview(OperationSpec('generate' if source == 'comfyui' else 'load',
                               source, model, context, workflow=workflow, profile_reference=reference)))


@router.post("/api/coordinator/reconcile")
def post_reconcile(req: Request) -> Response:
    """Client cannot supply terminal evidence or arbitrarily clear a reservation."""
    req.body  # Consume the request stream; never use it as terminal evidence.
    return Response.from_result(reconcile_uncertain())
