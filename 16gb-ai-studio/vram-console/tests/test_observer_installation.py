"""Installation must not replace unrelated existing custom-node files."""
import importlib.util
import hashlib
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('gmae_observer_installer_test', ROOT / 'scripts/install_comfy_observer.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def source(tmp_path):
    for file in installer.FILES:
        (tmp_path / file).write_bytes(b'fixture source')
    return tmp_path


def test_existing_different_code_refuses_without_copy(monkeypatch, source):
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        return 'true' if len(commands) == 1 else '0' * 64
    monkeypatch.setattr(installer, 'command', run)
    with pytest.raises(ValueError, match='refusing overwrite'):
        installer.stage_files(source)
    assert all(command[0] == 'exec' for command in commands)
    assert len(commands) == 2


def test_identical_existing_code_is_idempotent_without_copy(monkeypatch, source):
    commands = []
    digest = hashlib.sha256(b''.join((source / file).read_bytes() for file in installer.FILES)).hexdigest()
    def run(args, **kwargs):
        commands.append(args)
        return 'true' if len(commands) == 1 else digest
    monkeypatch.setattr(installer, 'command', run)
    installer.stage_files(source)
    assert all(command[0] == 'exec' for command in commands)
    assert len(commands) == 2


def test_restart_guard_runs_without_container_command(monkeypatch):
    from contextlib import contextmanager
    visited = []
    @contextmanager
    def guard(spec):
        visited.append((spec.operation, spec.service, spec.command_only))
        yield
    monkeypatch.setattr(installer, 'coordinated_operation', guard)
    monkeypatch.setattr(installer, 'command', lambda *a, **k: pytest.fail('container mutation'))
    installer.check_restart_admission()
    assert visited == [('restart', 'comfyui', True)]


def test_restart_guard_rejection_is_preserved(monkeypatch):
    from contextlib import contextmanager
    from core.resource_coordinator import ResourceDenied
    @contextmanager
    def denied(spec):
        raise ResourceDenied('UNCALIBRATED_STARTUP', 'fixture missing startup profile')
        yield
    monkeypatch.setattr(installer, 'coordinated_operation', denied)
    with pytest.raises(ResourceDenied, match='missing startup profile'):
        installer.check_restart_admission()
