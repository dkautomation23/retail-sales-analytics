"""Release gate: every claim in the README is re-checked against the code and the data.

    python check.py

Needs the warehouse loaded (python scripts/run_all.py). Prints ALL CHECKS PASSED
only if every check below passes; exit code 1 otherwise.

Checks 7 and 8 use the maintainer's scanners, found next to this repository or
through SECRET_SCANNER / PRIVACY_SCAN. Without them the run ends with
"CHECKS PASSED, 2 SKIPPED", never with ALL CHECKS PASSED.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
MAX_TRACKED_BYTES = 5 * 1024 * 1024
SECRET_SCANNER = Path(os.environ.get("SECRET_SCANNER", ROOT.parent / "repo-secret-scanner" / "scan.py"))
PRIVACY_SCAN = Path(os.environ.get("PRIVACY_SCAN", ROOT.parent / "_tools" / "privacy_scan.py"))

# Secret-scanner findings reviewed by hand and known to be harmless, as
# "path:line": "reason". Any finding not listed here fails check 7.
KNOWN_FALSE_POSITIVES: dict[str, str] = {}

CYRILLIC = re.compile(r"[\u0400-\u04ff]")
HOME_PATH = re.compile(r"[a-z]:[\\/]users[\\/]", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ALLOWED_EMAIL = re.compile(r"@users\.noreply\.github\.com$")
# The privacy scanner reports in Russian: "CRITICAL n, IMPORTANT n".
PRIVACY_TOTAL = re.compile(r"\u041a\u0420\u0418\u0422\u0418\u0427\u041d\u041e (\d+), \u0412\u0410\u0416\u041d\u041e (\d+)")


class Failed(Exception):
    pass


def sh(cmd: list, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


def tracked_files() -> list[Path]:
    """What git would publish: tracked plus untracked-but-not-ignored."""
    out = sh(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    if out.returncode:
        raise Failed(f"git ls-files failed: {out.stderr.strip()}")
    return [ROOT / p for p in out.stdout.split("\0") if p and (ROOT / p).is_file()]


def readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def check_pytest() -> str:
    out = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    passed = re.search(r"(\d+) passed", out.stdout)
    if out.returncode or not passed:
        raise Failed(f"pytest exit {out.returncode}: {out.stdout.strip().splitlines()[-1:]}")
    if re.search(r"\d+ (skipped|failed|error)", out.stdout):
        raise Failed(f"pytest: {out.stdout.strip().splitlines()[-1]} (warehouse not loaded?)")
    if int(passed.group(1)) < 8:
        raise Failed(f"only {passed.group(1)} tests passed, need at least 8")
    return f"{passed.group(1)} passed"


def check_row_count() -> str:
    from analytics.db import scalar
    rows = int(scalar("SELECT count(*) FROM fact_sales"))
    if rows <= 0:
        raise Failed("fact_sales is empty")
    stated = re.search(r"\| fact_sales \| ([\d,]+) \|", readme())
    if not stated:
        raise Failed("README has no fact_sales row count")
    if int(stated.group(1).replace(",", "")) != rows:
        raise Failed(f"README says {stated.group(1)}, warehouse has {rows:,}")
    return f"fact_sales {rows:,} = README"


def check_queries() -> str:
    from analytics import queries
    names = queries.files()
    empty = [n.name for n in names if queries.run(n.name).empty]
    if not names or empty:
        raise Failed(f"no analysis files or empty results: {empty}")
    return f"{len(names)} files ran, all return rows"


def check_dashboard() -> str:
    page = ROOT / "docs" / "index.html"
    if not page.exists():
        raise Failed("docs/index.html missing")
    size = page.stat().st_size
    charts = page.read_text(encoding="utf-8").count("Plotly.newPlot")
    if size <= 50 * 1024 or charts < 5:
        raise Failed(f"{size:,} bytes, {charts} charts (need > 50 KB and >= 5)")
    return f"{size:,} bytes, {charts} charts"


def check_findings() -> str:
    from analytics import findings
    block = re.search(r"<!-- findings:start -->\s*```\n(.*?)\n```\s*<!-- findings:end -->", readme(), re.S)
    if not block:
        raise Failed("README findings block not found")
    stated, actual = block.group(1).splitlines(), findings.compute()
    if stated != actual:
        diff = [f"README: {s}\n      data:   {a}" for s, a in zip(stated, actual) if s != a]
        raise Failed(f"{len(stated)} lines in README vs {len(actual)} from data\n      " + "\n      ".join(diff))
    return f"{len(actual)} findings match the data"


def check_hygiene() -> str:
    problems = []
    files = tracked_files()
    for path in files:
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), 1):
            if CYRILLIC.search(line):
                problems.append(f"{rel}:{lineno} Cyrillic text")
            if HOME_PATH.search(line):
                problems.append(f"{rel}:{lineno} local home path")
            for email in EMAIL.findall(line):
                if not ALLOWED_EMAIL.search(email):
                    problems.append(f"{rel}:{lineno} email {email}")
    if problems:
        raise Failed("\n      ".join(problems[:20]))
    return f"{len(files)} files clean"


def check_secrets() -> str:
    if not SECRET_SCANNER.exists():
        raise Skipped(f"secret scanner not found at {SECRET_SCANNER.name}")
    out = sh([PY, str(SECRET_SCANNER), ".", "--format", "json"])
    found = json.loads(out.stdout or "[]")
    new = []
    for f in found:
        key = f"{Path(f['file']).as_posix().removeprefix('./')}:{f['line']}"
        if key not in KNOWN_FALSE_POSITIVES:
            new.append(f"{key} [{f['rule']}]")
    if new:
        raise Failed("unreviewed findings: " + ", ".join(new))
    return f"{len(found)} findings, all reviewed"


def check_privacy() -> str:
    if not PRIVACY_SCAN.exists():
        raise Skipped(f"privacy scanner not found at {PRIVACY_SCAN.name}")
    out = sh([PY, str(PRIVACY_SCAN), ROOT.name], cwd=ROOT.parent)
    totals = PRIVACY_TOTAL.findall(out.stdout)
    if out.returncode or not totals:
        raise Failed(f"privacy scan exit {out.returncode}, no totals line")
    critical, important = map(int, totals[-1])
    if critical or important:
        raise Failed(f"critical {critical}, important {important}")
    return "critical 0, important 0"


def check_sizes() -> str:
    big = [f"{p.relative_to(ROOT).as_posix()} {p.stat().st_size:,}" for p in tracked_files()
           if p.stat().st_size > MAX_TRACKED_BYTES]
    if big:
        raise Failed("files over 5 MB: " + ", ".join(big))
    return "no file over 5 MB"


class Skipped(Exception):
    pass


CHECKS = [
    ("pytest green, at least 8 tests", check_pytest),
    ("fact_sales loaded, count matches README", check_row_count),
    ("every sql/analysis file runs", check_queries),
    ("dashboard built", check_dashboard),
    ("README findings match the data", check_findings),
    ("no Cyrillic, home paths or personal emails", check_hygiene),
    ("secret scan", check_secrets),
    ("privacy scan", check_privacy),
    ("no large files", check_sizes),
]


def venv_python() -> Path | None:
    """The project's .venv interpreter, if there is one and we are not already in it."""
    for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidate.exists() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
            return candidate
    return None


def main() -> int:
    venv = venv_python()
    if venv:  # run under the pinned dependencies, not whatever python started us
        return subprocess.call([str(venv), __file__, *sys.argv[1:]])
    sys.path.insert(0, str(ROOT))
    failed, skipped = 0, 0
    for number, (name, check) in enumerate(CHECKS, 1):
        try:
            print(f"ok    {number}. {name}: {check()}", flush=True)
        except Skipped as exc:
            skipped += 1
            print(f"SKIP  {number}. {name}: {exc}", flush=True)
        except Exception as exc:  # any crash in a check is a failure, not a pass
            failed += 1
            print(f"FAIL  {number}. {name}: {exc}", flush=True)
    if failed:
        print(f"\n{failed} CHECK(S) FAILED")
        return 1
    if skipped:
        print(f"\nCHECKS PASSED, {skipped} SKIPPED")
        return 0
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
