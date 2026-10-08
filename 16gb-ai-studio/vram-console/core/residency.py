"""Pure observer contract validation; no network or GPU operations."""
import uuid


def _validate_residency(result: dict, request_id: str) -> None:
    """Reject stale echoes and contradictory readiness; artifact hashing is separate."""
    if (type(result.get('schema_version')) is not int or result['schema_version'] != 1 or
            result.get('request_id') != request_id or result.get('warm_admission_enabled') is not False or
            type(result.get('residency_complete')) is not bool):
        raise ValueError('invalid observer contract')
    instance = result['backend_instance_id']
    if str(uuid.UUID(instance)) != instance:
        raise ValueError('invalid backend instance')
    digest = result['observer_code_sha256']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('observer source digest required')
    for key in ('recorded_at_ns', 'monotonic_ns', 'load_epoch', 'active_loads', 'observation_failures', 'unknown_components'):
        if type(result.get(key)) is not int or result[key] < 0:
            raise ValueError('invalid observer counters')
    for key in ('activity', 'activity_after'):
        if any(type(result[key].get(k)) is not int or result[key][k] < 0 for k in ('running', 'pending')):
            raise ValueError('invalid activity counters')
    components = result['components']
    if not isinstance(components, list):
        raise ValueError('invalid components')
    for component in components:
        _validate_component(component)
    unknown = sum(not component['known'] for component in components)
    complete = (len(components) == 3 and not unknown and
        sorted(component['role'] for component in components) == ['clip', 'unet', 'vae'] and
        all(component['fully_resident'] and not component['patched'] for component in components) and
        result['activity'] == result['activity_after'] == {'running': 0, 'pending': 0} and
        not result['active_loads'] and not result['observation_failures'] and not result.get('activity_changed', False))
    if unknown != result['unknown_components'] or result['residency_complete'] != complete:
        raise ValueError('contradictory readiness')


def _validate_component(component: dict) -> None:
    """Validate byte counters without claiming an artifact content digest."""
    if type(component.get('known')) is not bool:
        raise ValueError('component identity missing')
    if not component['known']:
        return
    if (component.get('role') not in ('unet', 'clip', 'vae') or
            component.get('filename') != 'sd_xl_base_1.0.safetensors' or
            component.get('artifact_digest_verified') is not False):
        raise ValueError('unsupported source or verification claim')
    digest = component['path_sha256']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('invalid path identity')
    stamp = component['file_identity']
    if not isinstance(stamp, list) or len(stamp) != 5 or any(type(v) is not int or v < 0 for v in stamp) or stamp[2] <= 0:
        raise ValueError('invalid source file metadata')
    resident, size = component['resident_bytes'], component['model_bytes']
    if type(resident) is not int or type(size) is not int or not 0 <= resident <= size or size <= 0:
        raise ValueError('invalid resident bytes')
    if type(component.get('fully_resident')) is not bool or component['fully_resident'] != (resident == size) or type(component.get('patched')) is not bool:
        raise ValueError('invalid component state')

