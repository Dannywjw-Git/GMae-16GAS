"""Read-only native process fingerprint tests; never terminate test runner."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('crash_trial',ROOT/'scripts/run_ollama_crash_trial.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_unrelated_pid_rejected_before_native_access():
    with pytest.raises(ValueError,match='launched'):
        module.OwnedController(SimpleNamespace(pid=1),dict(pid=2,parent_pid=3))


@pytest.mark.skipif(os.name!='nt',reason='Windows native process fingerprint')
def test_native_identity_accepts_and_closes_only_matching_self_handle():
    identity=dict(pid=os.getpid(),**module.windows_identity())
    controller=module.OwnedController(SimpleNamespace(pid=os.getpid()),identity)
    assert controller.handle is not None
    controller.close()
    assert controller.handle is None


@pytest.mark.skipif(os.name!='nt',reason='Windows native process fingerprint')
def test_reused_pid_creation_time_mismatch_rejected():
    identity=dict(pid=os.getpid(),**module.windows_identity())
    identity['creation_time']+=1
    with pytest.raises(ValueError,match='creation'):
        module.OwnedController(SimpleNamespace(pid=os.getpid()),identity)
