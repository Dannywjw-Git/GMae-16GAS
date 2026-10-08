"""Bootstrap planning is explicitly unverified and cannot exceed the safe context."""
import importlib.util
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('gmae_ollama_calibration',ROOT/'scripts/measure_ollama_workload.py')
calibration=importlib.util.module_from_spec(spec);spec.loader.exec_module(calibration)


@pytest.mark.parametrize('ctx',[True,8193,16384,0,-1])
def test_unsupported_context_rejected_before_mutation(ctx):
    with pytest.raises(ValueError): calibration.request_for(ctx)


def test_planning_copy_does_not_forge_verified_production_profile():
    original=next(m for m in calibration.REGISTRY['ollama']['models'] if m['id']==calibration.MODEL)
    before=original.copy()
    config,peak=calibration.planning_registry(8192,6594463106)
    model=next(m for m in config['ollama']['models'] if m['id']==calibration.MODEL)
    assert model['vram_verified'] is False and model['context_vram']=={'8192':peak/1024}
    assert original==before
    assert calibration.request_for(8192)['think'] is False
