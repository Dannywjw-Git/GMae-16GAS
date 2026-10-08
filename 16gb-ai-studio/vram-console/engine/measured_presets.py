"""Discover installed, content-validated mixed demonstration requests.

Catalog membership is evidence validation, never live execution permission.
No GPU access, backend calls, or model loading occurs during discovery.
"""
import json
import re
from pathlib import Path
from engine.profile_admission import _root, select_profile
from core.workload_profile import profile_from_evidence, execution_configuration_fingerprint


def _comfy_intent(workflow):
    """Invert supported controls only when the registered template reproduces it.

    Never accept arbitrary graphs: all non-control graph differences reject.
    Seed and output-name differences follow the existing measured match policy.
    """
    from engine.queue import REGISTRY, _load_workflow, _apply_params
    for model in REGISTRY.get('comfyui', {}).get('models', []):
        if not model.get('workflow'):
            continue
        template = _load_workflow(model['workflow'])
        if not template:
            continue
        try:
            params = {}
            for node_id, node in template.items():
                inputs = node.get('inputs', {})
                recorded = workflow[node_id]['inputs']
                if 'prompt' not in params:
                    for key in ('text', 'caption'):
                        if key in inputs:
                            params['prompt'] = recorded[key]
                            break
            for key in ('width', 'height', 'steps', 'cfg', 'seed', 'batch_size'):
                values = [node['inputs'][key] for node in workflow.values()
                          if key in node.get('inputs', {}) and not isinstance(node['inputs'][key], list)]
                if values:
                    if any(value != values[0] for value in values):
                        raise ValueError('ambiguous recorded control')
                    params[key] = values[0]
            effective = _apply_params(template, params)
            if execution_configuration_fingerprint(effective) == execution_configuration_fingerprint(workflow):
                return dict(source='comfyui', model=model['id'], params=params), effective
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    raise ValueError('no registered template reproduces the measured graph')


def installed_presets():
    presets, rejected = [], 0
    root = _root()
    for path in sorted(root.glob('*.json')):
        if not re.fullmatch(r'[0-9a-f]{64}', path.stem):
            continue
        try:
            manifest = json.loads(path.read_bytes())
            filename = manifest['raw_file']
            if (not isinstance(filename, str) or '/' in filename or '\\' in filename
                    or ':' in filename or Path(filename).name != filename
                    or filename in ('', '.', '..')):
                raise ValueError('invalid evidence filename')
            payload = (root / filename).read_bytes()
            raw = json.loads(payload)
            if raw.get('kind') == 'real_ollama_calibration':
                from engine.queue import _validate_ollama_request
                request = _validate_ollama_request(raw['request'])
                intent = dict(source='ollama', model=request['model'], request=request,
                    context_length=request['options']['num_ctx'],
                    prompt_tokens=raw['response_metrics']['prompt_eval_count'],
                    max_output_tokens=request['options']['num_predict'])
            elif raw.get('kind') == 'real_gpu_baseline':
                intent, request = _comfy_intent(raw['workflow'])
                intent['width'] = intent['params'].get('width')
                intent['height'] = intent['params'].get('height')
                intent['steps'] = intent['params'].get('steps')
            else:
                continue
            reference = select_profile(request)
            if not reference or reference['profile_key'] != path.stem:
                raise ValueError('installed request identity mismatch')
            profile = profile_from_evidence(payload, reference['margin_mb'])
            if profile['evidence']['raw_data_sha256'] != reference['raw_sha256']:
                raise ValueError('evidence changed during discovery')
            prompt = intent.get('request', {}).get('prompt', intent.get('params', {}).get('prompt', ''))
            presets.append(dict(id=path.stem, **intent,
                prompt_preview=prompt[:160], prompt_characters=len(prompt),
                measured_peak_mb=max(profile['peak_mb_samples']),
                envelope_mb=max(profile['peak_mb_samples']) + profile['margin_mb'],
                evidence_sha256=reference['raw_sha256'],
                recorded_at=profile['evidence']['recorded_at']))
        except (ValueError, KeyError, TypeError, IndexError, AttributeError, OSError, RuntimeError):
            rejected += 1
    return presets, rejected


def public_catalog():
    presets, rejected = installed_presets()
    return dict(presets=[{k: v for k, v in item.items() if k not in ('request', 'params')}
                         for item in presets], rejected_count=rejected,
                live_admission_verified=False,
                limitation='固定测量请求；执行时仍核验模型、运行环境、显存与资源所有权。不能外推任意提示词，也不保证不会 OOM。')


def resolve_preset(preset_id):
    if not isinstance(preset_id, str) or not re.fullmatch(r'[0-9a-f]{64}', preset_id):
        raise ValueError('测量预设标识无效')
    presets, _ = installed_presets()
    for item in presets:
        if item['id'] == preset_id:
            return item
    raise ValueError('测量预设不存在或证据已失效；请先安装本机校准 Profile')
