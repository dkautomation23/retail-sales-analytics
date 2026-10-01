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


def test_basket_pairs_compute_lift_on_a_known_example():
    # 4 orders: mint+basil, mint+basil, mint, bucket+spade.
    # mint+basil: support 2/4 = 50%, confidence 2/min(3, 2) = 100%, lift 2*4/(3*2) = 1.3
    # bucket+spade: lift 1*4/(1*1) = 4.0, and they share no word, so not the same line.
    with connect() as conn:
        conn.execute("DROP SCHEMA IF EXISTS qa_basket CASCADE; CREATE SCHEMA qa_basket")
        conn.execute("CREATE TABLE qa_basket.dim_product (LIKE public.dim_product)")
        conn.execute("CREATE TABLE qa_basket.fact_sales (LIKE public.fact_sales)")
        conn.execute("INSERT INTO qa_basket.dim_product VALUES (1, 'A1', 'HERB MARKER MINT'), "
                     "(2, 'A2', 'HERB MARKER BASIL'), (3, 'B1', 'SEASIDE BUCKET'), (4, 'C1', 'BEACH SPADE')")
        lines = [("1", 1), ("1", 2), ("2", 1), ("2", 2), ("3", 1), ("4", 3), ("4", 4)]
        for invoice, product in lines:
            conn.execute("INSERT INTO qa_basket.fact_sales VALUES (%s, 20100101, now(), 0, %s, 1, 1, 1, 1)",
                         (invoice, product))
        conn.commit()
    try:
        pairs = queries.run("06_basket_pairs", schema="qa_basket").set_index("product_a")
        herbs, beach = pairs.loc["HERB MARKER MINT"], pairs.loc["SEASIDE BUCKET"]
        assert (float(herbs["support_pct"]), float(herbs["confidence_pct"]), float(herbs["lift"])) == (50.0, 100.0, 1.3)
        assert bool(herbs["same_line"]) and not bool(beach["same_line"])
        assert float(beach["lift"]) == 4.0
    finally:
        with connect() as conn:
            conn.execute("DROP SCHEMA qa_basket CASCADE")


def test_dbt_rfm_mart_matches_the_analysis_sql():
    # Two implementations of one rule set must agree; run `dbt build` in dbt/ first.
    with connect() as conn:
        built = conn.execute("SELECT to_regclass('dbt_marts.mart_customer_rfm')").fetchone()[0]
        if built is None:
            pytest.fail("dbt marts are missing - run: cd dbt && dbt build --profiles-dir .")
        mart = dict(conn.execute("SELECT segment, count(*) FROM dbt_marts.mart_customer_rfm GROUP BY 1").fetchall())
    sql_file = queries.run("03_rfm_segments").set_index("segment")["customers"]
    assert {k: int(v) for k, v in sql_file.items()} == {k: int(v) for k, v in mart.items()}
