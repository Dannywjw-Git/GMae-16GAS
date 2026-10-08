"""Compare observed loading conditions; never attribute them to scheduler gains."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
from measure_comfy_workload import APP
from core.workload_profile import profile_from_evidence


def analyze(payloads):
    groups = {}
    trials = []
    for payload in payloads:
        raw = json.loads(payload)
        profile = profile_from_evidence(payload, 0)
        duration = raw.get('duration_s')
        if type(duration) not in (int, float) or not 0 < duration < float('inf'):
            raise ValueError('finite positive trial duration required')
        condition = raw.get('trial_condition')
        if condition not in ('model_unloaded_low_torch_verified',
                             'resident_memory_observed_model_identity_unproven'):
            raise ValueError('explicit loading condition required')
        baseline = raw['baseline']['used_mb']
        resident = raw.get('baseline_torch_resident_bytes')
        if type(baseline) is not int or not 0 <= baseline <= raw['baseline']['total_mb']:
            raise ValueError('invalid baseline memory')
        if type(resident) is not int or resident < 0:
            raise ValueError('baseline torch occupancy required')
        if condition == 'model_unloaded_low_torch_verified':
            preparation = raw.get('preparation', {})
            readings = preparation.get('readings', [])
            if (preparation.get('condition') != condition or
                    preparation.get('managed_release', {}).get('ok') is not True or not readings or
                    readings[-1].get('torch_resident_bytes', float('inf')) > 64 * 1024**2 or
                    resident > 64 * 1024**2):
                raise ValueError('unloaded condition requires preparation and fresh low-torch evidence')
        elif resident <= 64 * 1024**2:
            raise ValueError('resident condition requires substantial observed torch occupancy')
        trial = dict(raw_sha256=hashlib.sha256(payload).hexdigest(), condition=condition,
                     duration_s=duration, baseline_device_mb=baseline,
                     baseline_torch_resident_bytes=resident,
                     observed_device_peak_mb=raw['observed_device_peak_mb'],
                     observed_growth_mb=max(0, raw['observed_device_peak_mb'] - baseline),
                     sample_count=len(raw['samples']), sampler_cache_hit=False)
        trials.append(trial)
        identity = json.dumps(dict(configuration=profile['execution_configuration_sha256'],
                                   environment=profile['environment']), sort_keys=True)
        group = groups.setdefault(identity, dict(execution_configuration_sha256=profile['execution_configuration_sha256'],
                                                environment=profile['environment'], conditions={}))
        group['conditions'].setdefault(condition, []).append(trial)
    results = []
    for group in groups.values():
        summaries = {}
        for condition, rows in group.pop('conditions').items():
            durations = [row['duration_s'] for row in rows]
            summaries[condition] = dict(trials=len(rows), median_duration_s=statistics.median(durations),
                min_duration_s=min(durations), max_duration_s=max(durations),
                observed_device_peak_mb=max(row['observed_device_peak_mb'] for row in rows),
                max_observed_growth_mb=max(row['observed_growth_mb'] for row in rows))
        results.append({**group, 'conditions': summaries})
    return dict(kind='observed_loading_condition_analysis', groups=results, trials=trials,
                scheduler_benefit_proven=False, residency_identity_proven=False,
                limitations=['samples can miss transient peaks', 'CPU/disk caches uncontrolled',
                             'loading conditions differ; no scheduler speedup claim',
                             'observed growth is not a reusable warm admission budget',
                             'small uncontrolled-background experiment; no statistical guarantee'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', nargs='+', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = analyze([Path(file).read_bytes() for file in args.raw])
    with Path(args.output).open('x', encoding='utf-8', newline='\n') as file:
        json.dump(result, file, indent=2, allow_nan=False)
    print(json.dumps(dict(groups=len(result['groups']), trials=len(result['trials']), scheduler_benefit_proven=False)))


if __name__ == '__main__':
    main()
