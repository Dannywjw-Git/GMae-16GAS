"""Offline evidence consistency; these tests do not execute GPU workloads."""
import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('mixed_analyzer',ROOT/'scripts/analyze_mixed_queue_trial.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def pilot():
    return json.loads((ROOT/'docs/evidence/mixed-durable-queue-20261008/pilot.json').read_bytes())


def test_pilot_is_not_upgraded_to_verified_trace_or_comparison():
    summary=module.analyze(pilot(),False)
    assert summary['trace_verified'] is False and summary['comparative_result'] is False
    with pytest.raises((KeyError,ValueError)): module.analyze(pilot())


@pytest.mark.parametrize('change',[
    lambda raw: raw['tasks'][1]['intent'].update(source='comfyui'),
    lambda raw: raw['tasks'][1].update(status='uncertain'),
    lambda raw: raw.update(sampling_errors=['timeout']),
    lambda raw: raw['tasks'][1]['checkpoint']['budget']['measured_profile'].update(evidence_sha256='0'*64),
])
def test_mixed_evidence_rejects_wrong_backend_unconfirmed_or_changed_reference(change):
    raw=pilot();change(raw)
    with pytest.raises(ValueError): module.analyze(raw,False)


@pytest.mark.parametrize('fault',['release','physical','durable'])
def test_verified_trace_refuses_missing_release_capacity_or_submission_boundary(fault):
    raw=json.loads((ROOT/'docs/evidence/mixed-durable-queue-20261008/verified.json').read_bytes())
    assert module.analyze(raw)['verified_switch_releases']==2
    if fault=='release':
        for event in raw['coordination_events']: event.get('details',{}).pop('release_evidence',None)
    elif fault=='physical':
        for event in raw['coordination_events']:
            if 'telemetry' in event.get('details',{}): event['details']['telemetry']['free_mb']=1
    else:
        raw['durable_events']=[event for event in raw['durable_events'] if event['state']!='submitting']
    with pytest.raises(ValueError): module.analyze(raw)
