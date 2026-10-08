"""Validate actual Ollama calibration without extrapolating prompt coverage."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"16gb-ai-studio/vram-console"))
from core.ollama_profile import analyze


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw')
    args = parser.parse_args()
    print(json.dumps(analyze(json.loads(Path(args.raw).read_text(encoding='utf-8'))), indent=2))
