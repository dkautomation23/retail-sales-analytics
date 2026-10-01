"""Data-quality checks on a loaded star schema.

Each check is a query that counts offending rows; zero means pass. They run
against any schema, so the tests can point them at a deliberately broken copy
and prove that every check is able to fail.

    python -m analytics.quality
"""
from __future__ import annotations

from .db import connect

CHECKS = {
    "sales lines with a cancellation invoice":
        "SELECT count(*) FROM fact_sales WHERE invoice LIKE 'C%'",
    "sales lines with revenue <= 0":
        "SELECT count(*) FROM fact_sales WHERE revenue <= 0",
    "sales lines whose revenue != quantity * unit_price":
        "SELECT count(*) FROM fact_sales WHERE abs(revenue - round(quantity * unit_price, 2)) > 0.01",
    "sales lines with no matching date":
        "SELECT count(*) FROM fact_sales f LEFT JOIN dim_date d USING (date_key) WHERE d.date_key IS NULL",
    "sales lines with no matching product":
        "SELECT count(*) FROM fact_sales f LEFT JOIN dim_product p USING (product_key) WHERE p.product_key IS NULL",
    "sales lines with no matching customer":
        "SELECT count(*) FROM fact_sales f LEFT JOIN dim_customer c USING (customer_key) WHERE c.customer_key IS NULL",
    "products with an empty description":
        "SELECT count(*) FROM dim_product WHERE coalesce(trim(description), '') = ''",
    "returns with quantity <= 0":
        "SELECT count(*) FROM fact_returns WHERE quantity <= 0",
    "customer ids that appear twice":
        "SELECT count(*) FROM (SELECT customer_id FROM dim_customer WHERE customer_id IS NOT NULL "
        "GROUP BY customer_id HAVING count(*) > 1) d",
}


def failures(schema: str = "public") -> dict:
    """{check name: offending rows} for every check that does not return 0."""
    out = {}
    with connect() as conn:
        conn.execute(f"SET search_path TO {schema}")
        for name, sql in CHECKS.items():
            bad = conn.execute(sql).fetchone()[0]
            if bad:
                out[name] = bad
    return out


def main() -> int:
    bad = failures()
    for name in CHECKS:
        print(f"{'FAIL' if name in bad else 'ok  '}  {name}" + (f": {bad[name]}" if name in bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
