"""Validate limited-context calibration evidence; no production admission export."""
import argparse
import json
import math
from pathlib import Path


def analyze(raw):
    if (raw.get('kind') != 'real_ollama_calibration' or raw.get('status') != 'success'
            or raw.get('sampler_stopped') is not True or raw.get('sampling_errors') != []):
        raise ValueError('incomplete calibration')
    request = raw['request']
    ctx = request['options']['num_ctx']
    if type(ctx) is not int or ctx not in (2048, 8192) or request.get('think') is not False:
        raise ValueError('unsupported request')
    residents = raw['resident_after']
    if (len(residents) != 1 or residents[0]['context_length'] != ctx
            or residents[0]['digest'] != raw['model_artifact']['digest']):
        raise ValueError('model/context mismatch')
    metrics = raw['response_metrics']
    if metrics.get('done') is not True or metrics.get('eval_count') != 32:
        raise ValueError('incomplete controlled output')
    samples = raw['samples']
    previous = raw['baseline']['monotonic_s']
    peaks = []
    for sample in samples:
        values = [sample[k] for k in ('monotonic_s', 'total_mb', 'used_mb', 'free_mb')]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
            raise ValueError('invalid measurement')
        if values[0] <= previous or sample['total_mb'] != raw['baseline']['total_mb']:
            raise ValueError('nonmonotonic or inconsistent sample')
        if max(sample['used_mb'], sample['free_mb']) > sample['total_mb']:
            raise ValueError('invalid capacity')
        previous = values[0]
        peaks.append(max(sample['used_mb'], sample['total_mb'] - sample['free_mb']))
    if not peaks or max(peaks) != raw['observed_whole_device_peak_mb']:
        raise ValueError('peak mismatch')
    return dict(context_length=ctx, prompt_tokens=metrics['prompt_eval_count'],
                output_tokens=metrics['eval_count'], samples=len(samples),
                whole_device_peak_mb=max(peaks), resident_vram_bytes=residents[0]['size_vram'],
                duration_s=raw['duration_s'], production_profile=False,
                limitation='short prompt only; not full-context or worst-case peak')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw')
    args = parser.parse_args()
    print(json.dumps(analyze(json.loads(Path(args.raw).read_text(encoding='utf-8'))), indent=2))
