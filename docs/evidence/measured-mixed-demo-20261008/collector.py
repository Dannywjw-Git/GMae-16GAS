"""Record installed evidence discovery, not live admission or a GPU benchmark."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / '16gb-ai-studio/vram-console'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-dir', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('refusing to overwrite evidence')
    os.environ['GMAE_PROFILE_DIR'] = str(Path(args.profile_dir).resolve())
    from engine.measured_presets import public_catalog
    source = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout.strip()
    document = dict(kind='installed_measured_preset_catalog',
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    source_commit=source, gpu_experiment=False, catalog=public_catalog())
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(recorded=True, presets=len(document['catalog']['presets']),
                         rejected=document['catalog']['rejected_count'], gpu_experiment=False)))


if __name__ == '__main__':
    main()
