"""Run the complete offline suite, including pytest function tests.

Install requirements-dev.txt first. Live GPU scripts require explicit execution.
"""
import argparse
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("module", nargs="?")
parser.add_argument("-v", "--verbose", action="store_true")
parser.add_argument("-q", "--quiet", action="store_true")
args = parser.parse_args()
command = [sys.executable, "-m", "pytest", "-v" if args.verbose else "-q"]
if args.module:
    name = args.module.removeprefix("tests.").removesuffix(".py")
    command.append(str(Path(__file__).resolve().parent / (name + ".py")))
sys.exit(subprocess.call(command, cwd=root))
