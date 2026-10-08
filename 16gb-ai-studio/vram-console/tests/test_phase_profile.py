"""Reject unsafe resident reuse; fixture traces are not new performance runs."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from core.phase_profile import phase_profile_from_evidence, match_resident_phase

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def trace():
    return json.loads((ROOT / 'docs/evidence/sdxl-observer-resident-512-seed52-20261008.json').read_bytes())


def build(trace):
    return phase_profile_from_evidence(json.dumps(trace).encode(), 512)


def test_increment_is_distinct_from_large_model_size(trace):
    profile = build(trace)
    assert profile['increment_mb'] == 1184
    assert profile['resident_model_mb'] > 5 * 1024
    source = trace['residency_before']['components'][0]
    result = match_resident_phase(profile, trace['residency_after'],
        dict(model_digest=trace['model_artifact']['sha256'], file_identity=source['file_identity'], path_sha256=source['path_sha256']))
    assert result['increment_mb'] < result['resident_model_mb']


@pytest.mark.parametrize('change', ['restart', 'reload', 'unknown', 'partial', 'busy', 'file', 'observer'])
def test_changed_or_unverified_state_cannot_reuse(trace, change):
    profile = build(trace)
    snapshot = deepcopy(trace['residency_after'])
    if change == 'restart': snapshot['backend_instance_id'] = '00000000-0000-0000-0000-000000000000'
    elif change == 'reload': snapshot['load_epoch'] += 1
    elif change == 'unknown': snapshot['components'][0]['known'] = False
    elif change == 'partial': snapshot['components'][0]['resident_bytes'] -= 1
    elif change == 'busy': snapshot['activity']['running'] = 1
    elif change == 'file': snapshot['components'][0]['file_identity'][4] += 1
    else: snapshot['observer_code_sha256'] = '0' * 64
    source = trace['residency_before']['components'][0]
    with pytest.raises(ValueError):
        match_resident_phase(profile, snapshot, dict(model_digest=trace['model_artifact']['sha256'], file_identity=source['file_identity'], path_sha256=source['path_sha256']))


def test_free_counter_cannot_create_extra_capacity(trace):
    base = trace['baseline']['used_mb']
    trace['baseline']['free_mb'] = trace['baseline']['total_mb'] - base
    for sample in trace['samples']:
        sample['free_mb'] = sample['total_mb'] - sample['used_mb'] - 300
    assert build(trace)['increment_mb'] == 1484


def test_content_digest_is_required_separately(trace):
    profile = build(trace)
    source = trace['residency_before']['components'][0]
    with pytest.raises(ValueError, match='artifact digest'):
        match_resident_phase(profile, trace['residency_after'],dict(model_digest='0'*64,file_identity=source['file_identity'],path_sha256=source['path_sha256']))
