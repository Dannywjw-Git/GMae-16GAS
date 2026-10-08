"""Actual task controls and immutable backend payloads, without GPU execution."""
import copy
import pytest
from engine.queue import _apply_params


def workflow():
    return {'p': {'inputs': {'text': 'positive'}}, 'n': {'inputs': {'text': 'negative'}},
            'latent': {'inputs': {'width': 1024, 'height': 1024, 'batch_size': 1,
                                  'length': 17}},
            'sampler': {'inputs': {'seed': 42, 'steps': 25, 'cfg': 6.0}},
            'audio': {'inputs': {'seconds': 30, 'max_duration': 30}}}


def test_requested_controls_reach_backend_inputs():
    original = workflow()
    before = copy.deepcopy(original)
    result = _apply_params(original, dict(prompt='new', width=512, height=768,
                                         batch_size=2, seed=1, steps=12, cfg=0,
                                         frames=33, duration=10))
    assert result['p']['inputs']['text'] == 'new'
    assert result['n']['inputs']['text'] == 'negative'
    assert result['latent']['inputs'] == dict(width=512, height=768, batch_size=2, length=33)
    assert result['sampler']['inputs'] == dict(seed=1, steps=12, cfg=0)
    assert result['audio']['inputs']['seconds'] == 10
    assert result['audio']['inputs']['max_duration'] == 10
    assert original == before


@pytest.mark.parametrize('params', [dict(width=True), dict(height=1.5), dict(steps=0),
    dict(seed=-1), dict(cfg=float('nan')), dict(frames=float('inf')),
    dict(duration=-1), dict(width='512'), dict(prompt=3), dict(unknown=1)])
def test_invalid_requested_controls_reject(params):
    with pytest.raises(ValueError):
        _apply_params(workflow(), params)


def test_unavailable_control_and_linked_inputs_reject():
    with pytest.raises(ValueError, match='没有可绑定'):
        _apply_params({'1': {'inputs': {'width': ['2', 0]}}}, {'width': 512})
    with pytest.raises(ValueError, match='没有可绑定'):
        _apply_params({'1': {'inputs': {'text': 'test'}}}, {'steps': 5})
