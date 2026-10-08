"""Bootstrap planning is explicitly unverified and cannot exceed the safe context."""
import importlib.util
from pathlib import Path
import sys
import pytest
from copy import deepcopy
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


def example_raw():
    return dict(kind='real_ollama_calibration',status='success',sampler_stopped=True,
                sampling_errors=[],request=calibration.request_for(2048),
                model_artifact=dict(digest='test-only'),
                resident_after=[dict(context_length=2048,digest='test-only',size_vram=5000)],
                response_metrics=dict(done=True,eval_count=32,prompt_eval_count=24),
                baseline=dict(monotonic_s=1,total_mb=16380),
                samples=[dict(monotonic_s=2,total_mb=16380,used_mb=8000,free_mb=8000)],
                observed_whole_device_peak_mb=8380,duration_s=1)


@pytest.mark.parametrize('change',[
    lambda raw: raw.update(sampling_errors=['TimeoutError']),
    lambda raw: raw['resident_after'][0].update(context_length=8192),
    lambda raw: raw['samples'][0].update(monotonic_s=1),
    lambda raw: raw.update(observed_whole_device_peak_mb=8000),
])
def test_analysis_rejects_incomplete_or_inconsistent_evidence(change):
    from analyze_ollama_calibration import analyze
    raw=deepcopy(example_raw());change(raw)
    with pytest.raises(ValueError): analyze(raw)


def test_analysis_keeps_short_prompt_limit_and_conservative_count():
    from analyze_ollama_calibration import analyze
    result=analyze(example_raw())
    assert result['whole_device_peak_mb']==8380
    assert result['production_profile'] is False
    assert 'short prompt' in result['limitation']


def test_long_prompt_is_deterministic_and_does_not_claim_token_count():
    first=calibration.request_for(8192,'long')
    assert first==calibration.request_for(8192,'long')
    assert len(first['prompt'])>len(calibration.request_for(2048,'long')['prompt'])
    assert first['options']['num_ctx']==8192 and first['options']['num_predict']==32


def test_blob_mutation_is_rejected(monkeypatch):
    digest='a'*64
    outputs=iter(['container','1:2:3:4:5',digest+'  blob','1:2:4:4:5'])
    monkeypatch.setattr(calibration,'docker_read',lambda args: next(outputs))
    with pytest.raises(ValueError,match='changed'):
        calibration.artifact_identity(dict(modelfile='FROM /models/blobs/sha256-'+digest,details={}))


def test_blob_digest_mismatch_is_rejected(monkeypatch):
    outputs=iter(['container','stat','b'*64+'  blob','stat','container'])
    monkeypatch.setattr(calibration,'docker_read',lambda args: next(outputs))
    with pytest.raises(ValueError,match='content'):
        calibration.artifact_identity(dict(modelfile='FROM /models/blobs/sha256-'+'a'*64,details={}))


def test_missing_blob_identity_cannot_fall_back_to_model_name():
    with pytest.raises(ValueError,match='identify'):
        calibration.artifact_identity(dict(modelfile='FROM qwen3.5:9b',details={}))
