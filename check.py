"""Release gate: the README's numbers and the repository are re-checked against the data.

    python check.py

Needs the warehouse loaded (python scripts/run_all.py). Prints ALL CHECKS PASSED
only if every check below passes; exit code 1 otherwise.

Checks 7 and 8 use the maintainer's scanners, found next to this repository or
through SECRET_SCANNER / PRIVACY_SCAN. Without them the run ends with
"CHECKS PASSED, 2 SKIPPED", never with ALL CHECKS PASSED.
"""
from __future__ import annotations

import functools
import html
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
KNOWN_FALSE_POSITIVES: dict[str, str] = {
    "dbt/profiles.yml:11": "default password of the throwaway local demo container, "
                           "the same value as POSTGRES_PASSWORD in docker-compose.yml",
}

CYRILLIC = re.compile(r"[\u0400-\u04ff]")
HOME_PATH = re.compile(r"[a-z]:[\\/]users[\\/]", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ALLOWED_EMAIL = re.compile(r"(@users\.noreply\.github\.com|@example\.com)$")
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
    stated = re.search(r"(\d+) pytest tests", readme())
    if not stated or stated.group(1) != passed.group(1):
        raise Failed(f"README says {stated.group(1) if stated else 'nothing'} tests, pytest ran {passed.group(1)}")
    return f"{passed.group(1)} passed = README"


def check_row_count() -> str:
    from analytics.db import scalar
    tables = ("fact_sales", "fact_returns", "dim_customer", "dim_product", "dim_date", "dim_country")
    wrong = []
    for table in tables:
        rows = int(scalar(f"SELECT count(*) FROM {table}"))
        stated = re.search(rf"\| {table} \| ([\d,]+) \|", readme())
        if rows <= 0 or not stated or int(stated.group(1).replace(",", "")) != rows:
            wrong.append(f"{table}: README {stated.group(1) if stated else 'missing'}, warehouse {rows:,}")
    if wrong:
        raise Failed("; ".join(wrong))
    return f"{len(tables)} tables, row counts = README"


def check_queries() -> str:
    from analytics import queries
    names = queries.files()
    empty = [n.name for n in names if queries.run(n.name).empty]
    if not names or empty:
        raise Failed(f"no analysis files or empty results: {empty}")
    return f"{len(names)} files ran, all return rows"


def check_dbt() -> str:
    exe = next((c for c in (Path(PY).with_name("dbt.exe"), Path(PY).with_name("dbt")) if c.exists()), None)
    if exe is None:
        raise Skipped("dbt is not installed in this environment")
    out = sh([str(exe), "build", "--profiles-dir", "."], cwd=ROOT / "dbt")
    total = re.search(r"TOTAL=(\d+)", out.stdout)
    errors = re.search(r"ERROR=(\d+)", out.stdout)
    if out.returncode or not total or not errors or errors.group(1) != "0":
        tail = [line for line in out.stdout.splitlines() if "ERROR" in line or "FAIL" in line][:5]
        raise Failed(f"dbt build exit {out.returncode}: " + " | ".join(tail))
    stated = re.search(r"(\d+) dbt nodes", readme())
    if not stated or stated.group(1) != total.group(1):
        raise Failed(f"README says {stated.group(1) if stated else 'nothing'} dbt nodes, dbt built {total.group(1)}")
    return f"{total.group(1)} nodes built and tested = README"


def check_dashboard() -> str:
    page = ROOT / "docs" / "index.html"
    if not page.exists():
        raise Failed("docs/index.html missing")
    size = page.stat().st_size
    text = page.read_text(encoding="utf-8")
    charts = text.count("Plotly.newPlot")
    if size <= 50 * 1024 or charts < 5:
        raise Failed(f"{size:,} bytes, {charts} charts (need > 50 KB and >= 5)")
    from analytics import findings
    stale = [line[:2] for line in findings.findings_from(data_facts()) if html.escape(line) not in text]
    if stale:
        raise Failed(f"page is stale, findings {stale} differ - run python -m analytics.dashboard")
    return f"{size:,} bytes, {charts} charts, built from current data"


@functools.lru_cache(maxsize=1)
def data_facts() -> dict:
    from analytics import findings
    return findings.facts()


def check_findings() -> str:
    from analytics import findings
    block = re.search(r"<!-- findings:start -->\s*```\n(.*?)\n```\s*<!-- findings:end -->", readme(), re.S)
    if not block:
        raise Failed("README findings block not found")
    stated, actual = block.group(1).splitlines(), findings.findings_from(data_facts())
    if stated != actual:
        diff = [f"README: {s}\n      data:   {a}" for s, a in zip(stated, actual) if s != a]
        raise Failed(f"{len(stated)} lines in README vs {len(actual)} from data\n      " + "\n      ".join(diff))
    recs = re.search(r"<!-- recommendations:start -->\s*(.*?)\s*<!-- recommendations:end -->", readme(), re.S)
    if not recs:
        raise Failed("README recommendations block not found")
    stated_recs, actual_recs = recs.group(1).splitlines(), findings.recommendations_from(data_facts())
    if stated_recs != actual_recs:
        wrong = [s[:60] for s, a in zip(stated_recs, actual_recs) if s != a] or ["line count differs"]
        raise Failed("recommendations drifted from the data: " + "; ".join(wrong))
    return f"{len(actual)} findings and {len(actual_recs)} recommendations match the data"


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
    try:
        found = json.loads(out.stdout)
    except ValueError:
        raise Failed(f"scanner exit {out.returncode}, unreadable output: {out.stderr.strip()[:200]}")
    if out.returncode not in (0, 1) or (out.returncode == 1 and not found):
        raise Failed(f"scanner exit {out.returncode}: {out.stderr.strip()[:200]}")
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


def check_powerbi_project() -> str:
    """The Power BI project is text: compare it with the warehouse and with measures.md."""
    from analytics.db import connect
    bi = ROOT / "bi"
    model = bi / "retail-sales.SemanticModel" / "definition"
    if not (bi / "retail-sales.pbip").exists() or not model.exists():
        raise Failed("bi/retail-sales.pbip or its SemanticModel/definition folder is missing")
    for path in sorted(bi.glob("retail-sales.*/**/*.json")) + [bi / "retail-sales.pbip"]:
        if "$schema" not in json.loads(path.read_text(encoding="utf-8")):
            raise Failed(f"{path.relative_to(ROOT)} has no $schema")
    in_model: dict[str, set] = {}
    for tmdl in sorted((model / "tables").glob("*.tmdl")):
        in_model[tmdl.stem] = set(re.findall(r"^\tcolumn (\S+)$", tmdl.read_text(encoding="utf-8"), re.M))
    with connect() as conn:
        wrong = []
        for table, columns in in_model.items():
            rows = conn.execute("SELECT column_name FROM information_schema.columns "
                                "WHERE table_schema = 'public' AND table_name = %s", (table,)).fetchall()
            if columns != {r[0] for r in rows}:
                wrong.append(f"{table}: model {sorted(columns)} vs warehouse {sorted(r[0] for r in rows)}")
    if wrong:
        raise Failed("; ".join(wrong))
    relationships = re.findall(r"fromColumn: (\w+)\.(\w+)\n\ttoColumn: (\w+)\.(\w+)",
                               (model / "relationships.tmdl").read_text(encoding="utf-8"))
    for ft, fc, tt, tc in relationships:
        if fc not in in_model.get(ft, ()) or tc not in in_model.get(tt, ()):
            raise Failed(f"relationship {ft}.{fc} -> {tt}.{tc} names a column the model does not have")

    def squash(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    docs = (bi / "measures.md").read_text(encoding="utf-8")
    dax = re.search(r"```DAX\n(.*?)```", docs, re.S).group(1)
    documented = {}
    for block in re.split(r"\n\s*\n", dax.strip()):
        body = "\n".join(l for l in block.splitlines() if not l.lstrip().startswith("--"))
        name, _, expression = body.partition("=")
        documented[name.strip()] = squash(expression)
    fact = (model / "tables" / "fact_sales.tmdl").read_text(encoding="utf-8")
    built = {}
    for found in re.finditer(r"^\tmeasure (?:'([^']+)'|(\S+)) =(.*?)^\t\tformatString:", fact, re.S | re.M):
        built[found.group(1) or found.group(2)] = squash(found.group(3))
    if built != documented:
        diff = sorted(set(built) ^ set(documented)) or [k for k in built if built[k] != documented.get(k)]
        raise Failed(f"measures differ between measures.md and the Power BI project: {diff}")
    stated = re.search(r"(\d+) DAX measures", readme())
    if not stated or int(stated.group(1)) != len(built):
        raise Failed(f"README says {stated.group(1) if stated else 'nothing'} DAX measures, the project has {len(built)}")
    return (f"{len(in_model)} tables = warehouse columns, {len(relationships)} relationships valid, "
            f"{len(built)} measures = measures.md = README")


def check_excel_workbook() -> str:
    """The workbook must equal what export_excel would write from the warehouse today, cell by cell."""
    from datetime import date, datetime

    from openpyxl import load_workbook

    from analytics.db import connect
    from analytics.export_excel import MONTHLY, WAREHOUSE_NET, build
    path = ROOT / "bi" / "retail-sales-summary.xlsx"
    if not path.exists():
        raise Failed("bi/retail-sales-summary.xlsx is missing (python -m analytics.export_excel)")
    with connect() as conn:
        rows = conn.execute(MONTHLY).fetchall()
        net = float(conn.execute(WAREHOUSE_NET).fetchone()[0])
        partial = conn.execute("SELECT max(month_start) FROM dim_date").fetchone()[0]
    expected, actual = build(rows, net, partial), load_workbook(path)
    if actual.sheetnames != expected.sheetnames:
        raise Failed(f"sheets are {actual.sheetnames}, expected {expected.sheetnames}")

    def plain(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, float):
            return round(value, 2)
        return "" if value is None else value

    differing = []
    for name in expected.sheetnames:
        want, got = expected[name], actual[name]
        if want.dimensions != got.dimensions:
            differing.append(f"{name} size {got.dimensions} vs {want.dimensions}")
            continue
        for want_row, got_row in zip(want.iter_rows(), got.iter_rows()):
            differing += [f"{name}!{w.coordinate}" for w, g in zip(want_row, got_row)
                          if plain(w.value) != plain(g.value)]
    if differing:
        raise Failed("the workbook differs from a fresh build: " + ", ".join(differing[:5])
                     + "; rebuild it with python -m analytics.export_excel")
    return f"{len(rows)} months, every cell of both sheets equals a fresh build, net revenue {net:,.2f}"


def check_metabase_service() -> str:
    """Metabase runs from docker-compose.yml: pinned image, local port only, waits for a healthy database."""
    import yaml
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    service = (compose.get("services") or {}).get("metabase")
    if not service:
        raise Failed("docker-compose.yml has no metabase service")
    image = str(service.get("image", ""))
    name, _, tag = image.partition(":")
    if name != "metabase/metabase" or not re.fullmatch(r"v\d+\.\d+\.\d+(\.\d+)?", tag):
        raise Failed(f"image is {image!r}; expected metabase/metabase pinned to an exact version")
    if "127.0.0.1:3000:3000" not in [str(p) for p in service.get("ports", [])]:
        raise Failed("port must be published as 127.0.0.1:3000:3000 (local only)")
    if (service.get("depends_on") or {}).get("db", {}).get("condition") != "service_healthy":
        raise Failed("metabase must wait for db with condition: service_healthy")
    if not (ROOT / "bi" / "metabase" / "dashboard.png").exists() or not (ROOT / "bi" / "metabase" / "provision.py").exists():
        raise Failed("bi/metabase/provision.py or dashboard.png is missing")
    return f"{image}, 127.0.0.1:3000, waits for a healthy db, provisioning script and screenshot present"


def check_airflow_dag() -> str:
    """The Airflow DAG is a plain file: three chained tasks, and an image pinned to an exact version."""
    import ast

    import yaml
    dag_file = ROOT / "orchestration" / "dags" / "retail_etl.py"
    compose_file = ROOT / "docker-compose.airflow.yml"
    if not dag_file.exists() or not compose_file.exists():
        raise Failed("orchestration/dags/retail_etl.py or docker-compose.airflow.yml is missing")
    tree = ast.parse(dag_file.read_text(encoding="utf-8"))
    task_ids = [kw.value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                for kw in node.keywords if kw.arg == "task_id" and isinstance(kw.value, ast.Constant)]
    dag_ids = [kw.value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
               for kw in node.keywords if kw.arg == "dag_id" and isinstance(kw.value, ast.Constant)]
    arrows = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.RShift)]
    if dag_ids != ["retail_etl"] or len(task_ids) != 3 or len(set(task_ids)) != 3 or len(arrows) < 2:
        raise Failed(f"expected dag_id retail_etl with 3 distinct chained tasks, got {dag_ids}, {task_ids}, {len(arrows)} arrows")
    service = (yaml.safe_load(compose_file.read_text(encoding="utf-8")).get("services") or {}).get("airflow")
    build = (service or {}).get("build")
    if not service or not build:
        raise Failed("docker-compose.airflow.yml has no airflow service built from orchestration/Dockerfile")
    dockerfile = (ROOT / "orchestration" / "Dockerfile").read_text(encoding="utf-8")
    base = re.search(r"^FROM apache/airflow:(\S+)", dockerfile, re.M)
    if not base or not re.fullmatch(r"\d+\.\d+\.\d+-python\d+\.\d+", base.group(1)):
        raise Failed("orchestration/Dockerfile must start FROM apache/airflow:<exact version>-pythonX.Y")
    return f"dag retail_etl, tasks {task_ids}, image apache/airflow:{base.group(1)}"


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
    ("dbt build green", check_dbt),
    ("dashboard built", check_dashboard),
    ("README findings and recommendations match the data", check_findings),
    ("no Cyrillic, home paths or personal emails", check_hygiene),
    ("secret scan", check_secrets),
    ("privacy scan", check_privacy),
    ("no large files", check_sizes),
    ("Power BI project matches the warehouse and measures.md", check_powerbi_project),
    ("Excel workbook values equal the warehouse", check_excel_workbook),
    ("Metabase service is pinned and local-only", check_metabase_service),
    ("Airflow DAG has three chained tasks, image pinned", check_airflow_dag),
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
