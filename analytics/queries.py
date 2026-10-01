"""Run the business questions in sql/analysis/ and return them as DataFrames.

    python -m analytics.queries        # runs every query, prints the first rows
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from psycopg import sql

from .db import connect

ANALYSIS = Path(__file__).resolve().parent.parent / "sql" / "analysis"


def files() -> list:
    return sorted(ANALYSIS.glob("*.sql"))


def run(name: str, schema: str = "public") -> pd.DataFrame:
    """Run one analysis file; `schema` lets tests point it at a small synthetic copy."""
    path = ANALYSIS / (name if name.endswith(".sql") else f"{name}.sql")
    with connect() as conn:
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        cur = conn.execute(path.read_text(encoding="utf-8"))
        columns = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)


def main() -> int:
    with pd.option_context("display.width", 160, "display.max_columns", 12):
        for path in files():
            frame = run(path.name)
            print(f"== {path.name}: {len(frame)} rows")
            print(frame.head(6).to_string(index=False))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
