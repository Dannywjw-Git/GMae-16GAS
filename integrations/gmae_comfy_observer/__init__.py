"""Optional ComfyUI custom-node package: observation only, no generation nodes."""
import asyncio
import hashlib
from pathlib import Path
import uuid
from aiohttp import web
import comfy.model_management as model_management
import comfy.sd as sd
from server import PromptServer
from .observer import SourceTracker, wrap_checkpoint_loader

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


def install_observer():
    """Install once at backend startup; unsupported snapshots remain unverified."""
    tracker = SourceTracker()
    sd.load_checkpoint_guess_config = wrap_checkpoint_loader(sd.load_checkpoint_guess_config, tracker)
    root = Path(__file__).parent
    digest = hashlib.sha256(b''.join((root / file).read_bytes() for file in ('observer.py', '__init__.py'))).hexdigest()

    def activity():
        running, pending = PromptServer.instance.prompt_queue.get_current_queue()
        if not isinstance(running, list) or not isinstance(pending, list):
            raise ValueError('unsupported backend activity snapshot')
        return dict(running=len(running), pending=len(pending))

    def read_snapshot():
        before = activity()
        result = tracker.snapshot(list(model_management.current_loaded_models), before)
        after = activity()
        if after != before:
            result['residency_complete'] = False
            result['activity_changed'] = True
        result['activity_after'] = after
        result['observer_code_sha256'] = digest
        return result

    @PromptServer.instance.routes.get('/gmae/residency')
    async def get_residency(request):
        request_id = request.query.get('request_id', '')
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError('canonical request UUID required')
        except ValueError:
            return web.json_response({'error': 'invalid_request_id'}, status=400)
        try:
            result = await asyncio.wait_for(asyncio.to_thread(read_snapshot), timeout=3)
            return web.json_response({**result, 'request_id': request_id}, headers={'Cache-Control': 'no-store'})
        except Exception as error:
            return web.json_response({'error': 'residency_unavailable', 'error_type': type(error).__name__},
                                     status=503, headers={'Cache-Control': 'no-store'})
    return tracker


install_observer()
