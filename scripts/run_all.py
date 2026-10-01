"""One command from an empty machine to a built dashboard.

    python scripts/run_all.py

Starts PostgreSQL, downloads and verifies the dataset, loads the star schema,
runs the quality checks and the tests, and writes docs/index.html.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
STEPS = [
    ["docker", "compose", "up", "-d", "--wait", "db"],
    [PY, "scripts/download_data.py"],
    [PY, "-m", "analytics.etl"],
    [PY, "-m", "analytics.quality"],
    [PY, "-m", "pytest", "-q"],
    [PY, "-m", "analytics.findings"],
    [PY, "-m", "analytics.dashboard"],
]


def main() -> int:
    for cmd in STEPS:
        print(f"\n$ {' '.join(Path(c).name if c == PY else c for c in cmd)}", flush=True)
        code = subprocess.call(cmd, cwd=ROOT)
        if code:
            print(f"step failed with exit code {code}")
            return code
    print("\ndone: open docs/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
