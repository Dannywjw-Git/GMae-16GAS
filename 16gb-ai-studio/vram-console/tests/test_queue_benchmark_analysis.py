"""Synthetic rows exercise independent evidence validation, not performance."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import pytest
from core.workload_profile import workload_fingerprint

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('gmae_queue_analysis',ROOT/'scripts/analyze_queue_benchmark.py')
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)


@pytest.fixture
def dataset():
    template=json.loads((ROOT/'docs/evidence/phase-queue-seed54-20261008.json').read_bytes())
    workflow=json.loads((ROOT/'docs/evidence/sdxl-observer-resident-512-seed52-20261008.json').read_bytes())['workflow']
    rows=[];payloads=[]
    for index,mode in enumerate(('resident',)+analysis.ORDER):
        raw=json.loads(json.dumps(template));raw['effective_workflow']=json.loads(json.dumps(workflow))
        raw['effective_workflow']['5']['inputs']['seed']=100+index
        raw['workflow_sha256']=workload_fingerprint(raw['effective_workflow'])
        raw['profile_reference']={'raw_sha256':'a'*64}
        raw['duration_s']=index+1;raw['managed_unload_calls']=0 if mode=='resident' else 1
        raw['budget']['measured_profile']['memory_scope']='measured_resident_increment' if mode=='resident' else 'sampled_whole_device_upper_envelope'
        for sample in raw['samples']: sample['monotonic_s']+=index*1000
        payload=json.dumps(raw).encode();payloads.append(payload)
        rows.append(dict(index=index,mode=mode,seed=100+index,warmup=index==0,raw_sha256=hashlib.sha256(payload).hexdigest()))
    return dict(kind='interleaved_formal_queue_benchmark',status='success',plan=list(analysis.ORDER),warmup_excluded=True,rows=rows),payloads


def alter(dataset,index,change):
    manifest,payloads=dataset;raw=json.loads(payloads[index]);change(raw)
    payloads[index]=json.dumps(raw).encode();manifest['rows'][index]['raw_sha256']=hashlib.sha256(payloads[index]).hexdigest()
    return manifest,payloads


def test_warmup_is_retained_but_excluded_from_group_medians(dataset):
    result=analysis.analyze(*dataset)
    assert result['warmup']['duration_s']==1
    assert result['summaries']['resident']['trials']==4
    assert result['summaries']['conservative']['total_unloads']==4
    assert result['generalized_performance_claim'] is False


def test_changed_raw_digest_is_rejected(dataset):
    dataset[1][1]+=b' '
    with pytest.raises(ValueError,match='digest'): analysis.analyze(*dataset)


def test_changed_configuration_is_not_grouped_with_same_model(dataset):
    def change(raw):
        raw['effective_workflow']['4']['inputs']['width']=768
        raw['workflow_sha256']=workload_fingerprint(raw['effective_workflow'])
    with pytest.raises(ValueError,match='configuration'): analysis.analyze(*alter(dataset,1,change))


def test_invalid_duration_cannot_improve_summary(dataset):
    with pytest.raises(ValueError,match='duration'): analysis.analyze(*alter(dataset,1,lambda raw:raw.update(duration_s=True)))


def test_wrong_actual_strategy_is_rejected(dataset):
    with pytest.raises(ValueError,match='actual admission path'):
        analysis.analyze(*alter(dataset,1,lambda raw:raw['budget']['measured_profile'].update(memory_scope='measured_resident_increment')))


def test_failure_cannot_be_hidden_by_manifest_success(dataset):
    with pytest.raises(ValueError): analysis.analyze(*alter(dataset,1,lambda raw:raw.update(task_status='failed')))
