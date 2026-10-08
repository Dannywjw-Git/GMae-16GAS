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


def complete_raw():
    raw=example_raw()
    raw.update(gpu_identity=dict(name='fixture',driver='fixture',uuid_sha256='1'*64),
        artifact_identity=dict(container_id='fixture',blob_sha256='2'*64,blob_stat='fixture',
            blob_path_sha256='3'*64,model_configuration_sha256='4'*64,model_details={}),
        backend_version='fixture',container_backend_version='ollama version is fixture',
        recorded_at='2026-10-08T00:00:00Z',
        preparation=dict(condition='model_unloaded_low_torch_verified',managed_release=dict(ok=True),
                         readings=[dict(torch_resident_bytes=0)]))
    raw['gpu_identity_after']=raw['gpu_identity'].copy()
    raw['model_artifact']['digest']='5'*64
    raw['resident_after'][0]['digest']='5'*64
    return raw


def test_exact_ollama_profile_rejects_changed_prompt_and_environment():
    import json
    from core.ollama_profile import profile_from_evidence
    from core.workload_profile import match_profile
    raw=complete_raw();profile=profile_from_evidence(json.dumps(raw).encode(),512)
    assert match_profile(profile,raw['request'],profile['environment'])['peak_mb']==8892
    changed=deepcopy(raw['request']);changed['prompt']+='changed'
    assert not match_profile(profile,changed,profile['environment'])['ok']
    assert not match_profile(profile,raw['request'],{**profile['environment'],'driver':'changed'})['ok']


def test_legacy_calibration_without_gpu_identity_cannot_create_profile():
    import json
    from core.ollama_profile import profile_from_evidence
    with pytest.raises(KeyError): profile_from_evidence(json.dumps(example_raw()).encode(),512)


def test_installed_ollama_raw_is_pinned_and_revalidated(tmp_path,monkeypatch):
    import hashlib,json
    from core.ollama_profile import profile_from_evidence
    from engine import profile_admission
    from core.resource_coordinator import ResourceDenied
    raw=complete_raw();payload=json.dumps(raw).encode();profile=profile_from_evidence(payload,512)
    key=profile['workflow_sha256']
    (tmp_path/'raw.json').write_bytes(payload)
    (tmp_path/(key+'.json')).write_text(json.dumps(dict(raw_file='raw.json',
        raw_sha256=hashlib.sha256(payload).hexdigest(),margin_mb=512)))
    monkeypatch.setenv('GMAE_PROFILE_DIR',str(tmp_path))
    monkeypatch.setattr(profile_admission,'_live_environment',lambda raw:profile['environment'])
    reference=profile_admission.select_profile(raw['request'])
    assert profile_admission.measured_budget(raw['request'],reference)['peak_mb']==8892
    (tmp_path/'raw.json').write_bytes(payload+b' ')
    with pytest.raises(ResourceDenied): profile_admission.measured_budget(raw['request'],reference)


def test_ollama_profile_cannot_authorize_different_coordinator_context():
    from engine.coordinator import OperationSpec,_model_budget
    from core.resource_coordinator import ResourceDenied
    with pytest.raises(ResourceDenied,match='请求'):
        _model_budget(OperationSpec('generate','ollama',calibration.MODEL,8192,
            workflow=calibration.request_for(2048),profile_reference=dict(fake=True)))


def test_ollama_profile_cannot_authorize_comfyui_operation():
    from engine.coordinator import OperationSpec,_model_budget
    from core.resource_coordinator import ResourceDenied
    with pytest.raises(ResourceDenied,match='跨服务'):
        _model_budget(OperationSpec('generate','comfyui','SDXL',
            workflow=calibration.request_for(2048),profile_reference=dict(fake=True)))


def test_completed_generation_may_stop_before_maximum_output():
    from core.ollama_profile import analyze
    raw=example_raw();raw['response_metrics']['eval_count']=24
    assert analyze(raw)['output_tokens']==24
    raw['response_metrics']['eval_count']=33
    with pytest.raises(ValueError): analyze(raw)


@pytest.mark.parametrize('change',[
    lambda raw: raw['admission']['budget']['measured_profile'].update(profile_status='estimate'),
    lambda raw: raw['request'].update(prompt='a different request'),
    lambda raw: raw['profile_reference'].update(raw_sha256='0'*64),
])
def test_archived_profiled_trial_rejects_changed_admission_or_reference(change):
    import json
    from core.ollama_profile import analyze_profiled
    directory=ROOT/'docs/evidence/ollama-long-profile-20261008'
    payload=(directory/'ollama-qwen9b-long8192-20261008.json').read_bytes()
    raw=json.loads((directory/'ollama-qwen9b-profiled8192-20261008.json').read_bytes())
    assert analyze_profiled(raw,payload)['admission_peak_mb']==8833
    change(raw)
    with pytest.raises(ValueError): analyze_profiled(raw,payload)
