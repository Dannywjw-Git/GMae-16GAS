"""Read-only whole-device budget diagnostic, not verified formal admission."""
import argparse
import json
from pathlib import Path
from measure_comfy_workload import APP
from core.workload_profile import profile_from_evidence
from engine.budget import budget_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', required=True)
    parser.add_argument('--margin-mb', type=int, default=512)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('refusing to overwrite diagnostic')
    payload = Path(args.raw).read_bytes()
    raw = json.loads(payload)
    if raw.get('model_artifact', {}).get('filename') != 'sd_xl_base_1.0.safetensors':
        raise ValueError('this diagnostic only supports measured SDXL')
    profile = profile_from_evidence(payload, args.margin_mb)
    peak = max(profile['peak_mb_samples']) + profile['margin_mb']
    budget = budget_engine(force_refresh=True, peak_overrides={('comfyui', 'SDXL'): peak / 1024})
    if not budget.get('ok'):
        raise ValueError('fresh budget unavailable')
    item = next(model for model in budget['models'] if model['source'] == 'comfyui' and model['id'] == 'SDXL')
    result = dict(kind='readonly_whole_device_budget_diagnostic', formal_admission_verified=False,
        measured_peak_with_margin_mb=peak, source_evidence_sha256=profile['evidence']['raw_data_sha256'],
        budget={key:budget.get(key) for key in ['ok','total_gb','used_gb','avail_gb','reserve_gb','noise_gb']},
        target={key:item.get(key) for key in ['id','source','loaded','vram_gb','decision','need_free_gb','gap_gb','note']})
    with output.open('x', encoding='utf-8', newline='\n') as file:
        json.dump(result, file, indent=2, ensure_ascii=False)
    print(json.dumps(dict(formal_admission_verified=False, decision=item['decision'])))


if __name__ == '__main__':
    main()
