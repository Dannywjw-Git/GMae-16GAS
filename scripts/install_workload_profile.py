"""Explicitly activate reviewed raw evidence; never accept an arbitrary peak."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1] / '16gb-ai-studio' / 'vram-console'
sys.path.insert(0, str(APP))
from core.workload_profile import profile_from_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', required=True)
    parser.add_argument('--margin-mb', type=int, default=512)
    parser.add_argument('--destination', default=os.environ.get('GMAE_PROFILE_DIR', str(APP / 'data' / 'profiles')))
    args = parser.parse_args()
    payload = Path(args.raw).read_bytes()
    profile = profile_from_evidence(payload, args.margin_mb)
    digest = hashlib.sha256(payload).hexdigest()
    root = Path(args.destination)
    root.mkdir(parents=True, exist_ok=True)
    raw_file = digest + '-raw.json'
    raw_path = root / raw_file
    if raw_path.exists():
        if raw_path.read_bytes() != payload:
            raise ValueError('installed raw evidence mismatch')
    else:
        with raw_path.open('xb') as output:
            output.write(payload)
    manifest = dict(raw_file=raw_file, raw_sha256=digest, margin_mb=args.margin_mb)
    target = root / (profile['execution_configuration_sha256'] + '.json')
    with target.open('x', encoding='utf-8') as output:
        json.dump(manifest, output)
    print(json.dumps(dict(installed=True, profile_key=profile['execution_configuration_sha256'],
                          raw_sha256=digest)))


if __name__ == '__main__':
    main()
