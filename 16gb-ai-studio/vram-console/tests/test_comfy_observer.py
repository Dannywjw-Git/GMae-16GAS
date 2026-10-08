"""Pure object/metadata tests; no ComfyUI, torch, GPU or service required."""
import gc
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import weakref
import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('gmae_observer_pure', ROOT / 'integrations/gmae_comfy_observer/observer.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class Model:
    pass


class Loaded:
    def __init__(self, patcher, resident=100, size=100):
        self.model, self.resident, self.size = patcher, resident, size
        self.device = SimpleNamespace(type='cuda', index=0)

    def model_loaded_memory(self):
        return self.resident

    def model_memory(self):
        return self.size


@pytest.fixture
def tracked(tmp_path):
    path = tmp_path / observer.SUPPORTED_CHECKPOINT
    path.write_bytes(b'unit fixture, not a real model')
    patchers = [SimpleNamespace(model=Model(), patches={}) for _ in range(3)]
    outputs = (patchers[0], SimpleNamespace(patcher=patchers[1]), SimpleNamespace(patcher=patchers[2]))
    tracker = observer.SourceTracker()
    loader = observer.wrap_checkpoint_loader(lambda *a, **k: outputs, tracker)
    assert loader(path) is outputs
    return tracker, path, [Loaded(patcher) for patcher in patchers]


def snapshot(tracker, loaded):
    return tracker.snapshot(loaded, dict(running=0, pending=0))


def test_complete_source_is_observation_not_admission(tracked):
    tracker, path, loaded = tracked
    result = snapshot(tracker, loaded)
    assert result['residency_complete'] is True
    assert result['warm_admission_enabled'] is False
    assert result['unknown_components'] == 0
    assert {component['role'] for component in result['components']} == {'unet', 'clip', 'vae'}
    assert all(not component['artifact_digest_verified'] for component in result['components'])
    assert str(path) not in str(result)


def test_old_objects_are_not_relabelled_using_filename():
    tracker = observer.SourceTracker()
    result = snapshot(tracker, [Loaded(SimpleNamespace(model=Model(), patches={}))])
    assert result['unknown_components'] == 1
    assert result['residency_complete'] is False


def test_file_change_invalidates_cached_object(tracked):
    tracker, path, loaded = tracked
    path.write_bytes(b'changed fixture with a different size')
    result = snapshot(tracker, loaded)
    assert result['unknown_components'] == 3
    assert result['residency_complete'] is False


@pytest.mark.parametrize('resident,size', [(1, 100), (0, 100), (101, 100), (True, 100), (100, 0)])
def test_partial_or_malformed_memory_cannot_claim_complete(tracked, resident, size):
    tracker, _, loaded = tracked
    loaded[0].resident, loaded[0].size = resident, size
    assert snapshot(tracker, loaded)['residency_complete'] is False


def test_patched_component_is_not_original_checkpoint(tracked):
    tracker, _, loaded = tracked
    loaded[0].model.patches = {'lora': 'synthetic'}
    assert snapshot(tracker, loaded)['residency_complete'] is False


def test_missing_component_cannot_claim_whole_checkpoint(tracked):
    tracker, _, loaded = tracked
    assert snapshot(tracker, loaded[:1])['residency_complete'] is False


def test_busy_or_loading_snapshot_is_incomplete(tracked):
    tracker, _, loaded = tracked
    assert tracker.snapshot(loaded, dict(running=1, pending=0))['residency_complete'] is False
    tracker.begin_load()
    assert snapshot(tracker, loaded)['residency_complete'] is False
    tracker.end_load()


def test_restarts_get_distinct_instance_identity():
    assert snapshot(observer.SourceTracker(), [])['backend_instance_id'] != snapshot(observer.SourceTracker(), [])['backend_instance_id']


def test_tracker_does_not_keep_weights_alive(tmp_path):
    path = tmp_path / observer.SUPPORTED_CHECKPOINT
    path.write_bytes(b'fixture')
    tracker = observer.SourceTracker()
    root = Model()
    reference = weakref.ref(root)
    patcher = SimpleNamespace(model=root, patches={})
    tracker.register_checkpoint(path, (patcher, None, None), observer.file_identity(path))
    del patcher, root
    gc.collect()
    assert reference() is None


def test_original_loader_exception_is_preserved_and_load_ends(tmp_path):
    error = RuntimeError('original loader failure')
    def original(*args):
        raise error
    tracker = observer.SourceTracker()
    wrapped = observer.wrap_checkpoint_loader(original, tracker)
    with pytest.raises(RuntimeError) as result:
        wrapped(tmp_path / 'unsupported.safetensors')
    assert result.value is error
    assert snapshot(tracker, [])['active_loads'] == 0


def test_metadata_failure_preserves_loader_result_but_invalidates_observation(tmp_path):
    tracker = observer.SourceTracker()
    sentinel = object()
    wrapped = observer.wrap_checkpoint_loader(lambda *args: sentinel, tracker)
    assert wrapped(tmp_path / observer.SUPPORTED_CHECKPOINT) is sentinel
    assert snapshot(tracker, [])['observation_failures'] == 1


def test_duplicate_hook_refused():
    tracker = observer.SourceTracker()
    wrapped = observer.wrap_checkpoint_loader(lambda *args: None, tracker)
    with pytest.raises(ValueError, match='already installed'):
        observer.wrap_checkpoint_loader(wrapped, tracker)
