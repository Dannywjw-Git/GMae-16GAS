"""Fail CI on undefined names and syntax errors; report legacy lint warnings."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
source = root / "16gb-ai-studio" / "vram-console"
result = subprocess.run([sys.executable, "-m", "pyflakes", *[
    str(source / name) for name in ("core", "engine", "services", "api", "clients", "gpu")
]], capture_output=True, text=True)
if result.stderr:
    print(result.stderr)
    sys.exit(1)
lines = result.stdout.splitlines()
warnings = ("imported but unused", "assigned to but never used", "f-string is missing placeholders",
            "`global ", "redefinition of unused")
errors = [line for line in lines if not any(w in line for w in warnings)]
print("Legacy lint warnings: %d; blocking errors: %d" % (len(lines)-len(errors), len(errors)))
for line in errors:
    print(line)
sys.exit(bool(errors))
