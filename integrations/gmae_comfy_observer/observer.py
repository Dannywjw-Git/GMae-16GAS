"""Read-only model provenance tracking; no torch imports or GPU mutations."""
from functools import wraps
import hashlib
import logging
from pathlib import Path
import threading
import time
from typing import Any
import uuid
import weakref

SUPPORTED_CHECKPOINT = 'sd_xl_base_1.0.safetensors'
SCHEMA_VERSION = 1


def file_identity(path: Path) -> tuple[int, ...]:
    """Metadata fences ordinary file replacement; not a content digest."""
    stamp = path.stat()
    return (stamp.st_dev, stamp.st_ino, stamp.st_size, stamp.st_mtime_ns, stamp.st_ctime_ns)


class SourceTracker:
    """Weak references retain provenance without keeping model weights alive."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sources = weakref.WeakKeyDictionary()
        self._epoch = 0
        self._loading = 0
        self._failures = 0
        self._instance = str(uuid.uuid4())

    def begin_load(self) -> None:
        with self._lock:
            self._epoch += 1
            self._loading += 1

    def end_load(self) -> None:
        with self._lock:
            self._loading -= 1

    def observation_failed(self) -> None:
        with self._lock:
            self._failures += 1

    def register_checkpoint(self, path: Path, result: Any, before: tuple[int, ...]) -> None:
        """Bind the standard checkpoint's UNet/CLIP/VAE objects to load-time metadata."""
        if path.name != SUPPORTED_CHECKPOINT:
            return  # Unsupported sources remain unknown in live loaded-model snapshots.
        if file_identity(path) != before:
            raise ValueError('checkpoint changed during load')
        if not isinstance(result, (tuple, list)) or len(result) < 3:
            raise ValueError('unsupported checkpoint loader result')
        for role, item in zip(('unet', 'clip', 'vae'), result[:3]):
            if item is None:
                continue
            patcher = item if role == 'unet' else item.patcher
            root = patcher.model
            source = (path, before, role)
            with self._lock:
                previous = self._sources.get(root, source)
                self._sources[root] = source if previous == source else None

    def _component(self, loaded: Any) -> dict:
        try:
            patcher = loaded.model
            source = self._sources.get(patcher.model)
            if source is None:
                return dict(known=False, reason='untracked_or_ambiguous_source')
            path, stamp, role = source
            if file_identity(path) != stamp:
                return dict(known=False, reason='source_file_changed')
            resident, size = loaded.model_loaded_memory(), loaded.model_memory()
            if type(resident) is not int or type(size) is not int or not 0 <= resident <= size or size <= 0:
                return dict(known=False, reason='invalid_component_memory')
            device = loaded.device
            if getattr(device, 'type', None) != 'cuda' or getattr(device, 'index', None) not in (0, None):
                return dict(known=False, reason='unsupported_device')
            return dict(known=True, role=role, filename=SUPPORTED_CHECKPOINT,
                path_sha256=hashlib.sha256(str(path.resolve()).encode()).hexdigest(),
                file_identity=list(stamp), resident_bytes=resident, model_bytes=size,
                fully_resident=resident == size, patched=bool(patcher.patches),
                artifact_digest_verified=False)
        except Exception as error:
            return dict(known=False, reason='component_unreadable', error_type=type(error).__name__)

    def snapshot(self, loaded_models: list, activity: dict) -> dict:
        """Report unknown/partial state explicitly; never infer identity from history."""
        with self._lock:
            idle = (type(activity.get('running')) is int and activity['running'] == 0 and
                    type(activity.get('pending')) is int and activity['pending'] == 0)
            components = [self._component(model) for model in loaded_models] if idle and not self._loading else []
            unknown = sum(not component['known'] for component in components)
            fully_resident = bool(components) and all(component.get('fully_resident') and
                not component.get('patched') for component in components)
            roles = [component.get('role') for component in components]
            complete_roles = sorted(roles) == ['clip', 'unet', 'vae'] if not unknown else False
            return dict(schema_version=SCHEMA_VERSION, backend_instance_id=self._instance,
                recorded_at_ns=time.time_ns(), monotonic_ns=time.monotonic_ns(),
                load_epoch=self._epoch, active_loads=self._loading, observation_failures=self._failures,
                activity=dict(activity), components=components, unknown_components=unknown,
                residency_complete=idle and not self._loading and not self._failures and not unknown and fully_resident and complete_roles,
                warm_admission_enabled=False,
                limitation='metadata provenance only; host artifact digest and measured phase profile still required')


def wrap_checkpoint_loader(original: Any, tracker: SourceTracker) -> Any:
    """Preserve loader result/errors; observation errors invalidate telemetry only."""
    if getattr(original, '_gmae_residency_observer', False):
        raise ValueError('observer already installed; restart instead of stacking hooks')

    @wraps(original)
    def observed(*args, **kwargs):
        tracker.begin_load()
        path, stamp = None, None
        try:
            try:
                path = Path(args[0] if args else kwargs['ckpt_path'])
                if path.name == SUPPORTED_CHECKPOINT:
                    stamp = file_identity(path)
            except Exception:
                tracker.observation_failed()
                logging.exception('GMae observer could not record source metadata')
            result = original(*args, **kwargs)
            if stamp is not None:
                try:
                    tracker.register_checkpoint(path, result, stamp)
                except Exception:
                    tracker.observation_failed()
                    logging.exception('GMae observer source registration failed')
            return result
        finally:
            tracker.end_load()

    observed._gmae_residency_observer = True
    return observed
