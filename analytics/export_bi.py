"""Export the star schema to CSV for Power BI or Tableau.

    python -m analytics.export_bi      # writes bi/data/*.csv (not committed, ~60 MB)

Power BI can also read the tables straight from PostgreSQL, see bi/POWERBI.md.
"""
from __future__ import annotations

from pathlib import Path

from .db import connect

OUT = Path(__file__).resolve().parent.parent / "bi" / "data"
TABLES = ("dim_date", "dim_country", "dim_customer", "dim_product", "fact_sales", "fact_returns")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        for table in TABLES:
            path = OUT / f"{table}.csv"
            with path.open("wb") as handle, conn.cursor().copy(
                    f"COPY {table} TO STDOUT WITH (FORMAT csv, HEADER true)") as cp:
                for chunk in cp:
                    handle.write(chunk)
            print(f"{path.name:<18} {path.stat().st_size:>12,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
