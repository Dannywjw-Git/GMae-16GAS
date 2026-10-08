"""Review archived real evidence; offline tests are not new GPU fault runs."""
import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('crash_analyzer',ROOT/'scripts/analyze_ollama_crash_trial.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@pytest.mark.parametrize('fault',['no_fault','no_hold','wrong_receipt','new_request'])
def test_crash_chain_rejects_missing_fault_hold_or_changed_receipt(fault):
    raw=json.loads((ROOT/'docs/evidence/ollama-crash-recovery-20261008/verified.json').read_bytes())
    assert module.analyze(raw)['recovered_without_replay']
    if fault=='no_fault': raw['controller_exit_code']=0
    elif fault=='no_hold': raw['initial_reconcile']={'ok':True,'resolved':True}
    elif fault=='wrong_receipt': raw['commands_after'][0]['intent_sha256']='0'*64
    else: raw['task_after']['intent']['effective_workflow']['prompt']='different request'
    with pytest.raises(ValueError): module.analyze(raw)


def test_failed_pid_pilot_cannot_be_presented_as_crash_recovery():
    raw=json.loads((ROOT/'docs/evidence/ollama-crash-recovery-20261008/failed-pilot.json').read_bytes())
    with pytest.raises(ValueError): module.analyze(raw)
