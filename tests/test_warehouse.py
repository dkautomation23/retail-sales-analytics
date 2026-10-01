"""Checks against the loaded database (run `python -m analytics.etl` first).

The broken-copy test is the important one: every quality check must be able to
fail, or a green run proves nothing.
"""
import pytest

from analytics import quality, queries
from analytics.db import connect


def loaded():
    try:
        with connect() as conn:
            return conn.execute("SELECT count(*) FROM fact_sales").fetchone()[0] > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not loaded(), reason="database not loaded - run python -m analytics.etl")


def test_loaded_warehouse_passes_every_quality_check():
    assert quality.failures() == {}


def test_every_quality_check_fails_on_a_broken_copy():
    with connect() as conn:
        conn.execute("DROP SCHEMA IF EXISTS qa_broken CASCADE; CREATE SCHEMA qa_broken")
        for table in ("dim_date", "dim_product", "dim_customer", "fact_sales", "fact_returns"):
            conn.execute(f"CREATE TABLE qa_broken.{table} (LIKE public.{table})")
        conn.execute("ALTER TABLE qa_broken.dim_product ALTER COLUMN description DROP NOT NULL")
        conn.execute("INSERT INTO qa_broken.dim_date SELECT * FROM public.dim_date ORDER BY date_key LIMIT 1")
        conn.execute("INSERT INTO qa_broken.dim_date "                       # a gap in the calendar
                     "SELECT * FROM public.dim_date ORDER BY date_key DESC LIMIT 1")
        conn.execute("INSERT INTO qa_broken.dim_product VALUES (1, '10001', '  ')")
        conn.execute("INSERT INTO qa_broken.dim_customer VALUES (1, 777, 1), (2, 777, 1)")
        d = conn.execute("SELECT date_key FROM qa_broken.dim_date").fetchone()[0]
        conn.execute(
            "INSERT INTO qa_broken.fact_sales VALUES "
            f"('C1', {d}, now(), 1, 1, 1, 1, 1.00, 1.00),"        # cancellation in sales
            f"('2', {d}, now(), 1, 1, 1, 1, 1.00, -5.00),"        # negative revenue, wrong arithmetic
            "('3', 19000101, now(), 9, 9, 1, 1, 1.00, 1.00)")     # orphan date, product, customer
        conn.execute(f"INSERT INTO qa_broken.fact_returns VALUES ('C9', {d}, 1, 1, 1, 0, 0)")
        conn.commit()
    try:
        assert set(quality.failures("qa_broken")) == set(quality.CHECKS)
    finally:
        with connect() as conn:
            conn.execute("DROP SCHEMA qa_broken CASCADE")


def test_cleaning_removed_every_cancellation_from_sales():
    with connect() as conn:
        assert conn.execute("SELECT count(*) FROM fact_sales WHERE invoice LIKE 'C%'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM fact_returns").fetchone()[0] > 0


@pytest.mark.parametrize("path", queries.files(), ids=lambda p: p.name)
def test_every_analysis_query_returns_rows(path):
    assert len(queries.run(path.name)) > 0


def test_net_ranking_drops_the_cancelled_bulk_order():
    top = queries.run("04_top_products_countries")
    products = top[top["dimension"] == "product"]["name"].str.cat(sep=" | ")
    assert "LITTLE BIRDIE" not in products


def test_cancellation_ranking_ignores_same_day_reversals():
    rates = queries.run("05_return_rate")
    products = rates[~rates["product"].str.startswith("ALL PRODUCTS")]["product"].str.cat(sep=" | ")
    assert "LITTLE BIRDIE" not in products and "MEDIUM CERAMIC TOP STORAGE JAR" not in products
    overall = rates.set_index("product")["return_rate_pct"]
    assert overall["ALL PRODUCTS, same-day reversals excluded"] < overall["ALL PRODUCTS, all cancellations"]


def test_retention_starts_after_the_first_month_of_data():
    cohorts = queries.run("02_cohort_retention")
    with connect() as conn:
        first = conn.execute("SELECT min(month_start) FROM dim_date").fetchone()[0]
    assert cohorts["cohort"].min() > first
