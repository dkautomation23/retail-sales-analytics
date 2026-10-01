"""Load UCI Online Retail II into the star schema.

    python -m analytics.etl

Reads both sheets of the workbook (cached as CSV after the first run, the
xlsx takes minutes to parse), applies the cleaning rules in analytics.clean,
builds the dimensions and bulk-loads everything with COPY. Prints the
cleaning table and the final row counts.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from .clean import clean, format_steps
from .db import connect

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
XLSX = RAW / "online_retail_II.xlsx"
CACHE = RAW / "online_retail_ii.csv"
SCHEMA = ROOT / "sql" / "schema.sql"


def read_raw() -> pd.DataFrame:
    if CACHE.exists():
        return pd.read_csv(CACHE, dtype={"Invoice": str, "StockCode": str},
                           parse_dates=["InvoiceDate"])
    if not XLSX.exists():
        raise SystemExit("data/raw/online_retail_II.xlsx is missing - run scripts/download_data.py")
    sheets = pd.read_excel(XLSX, sheet_name=None, dtype={"Invoice": str, "StockCode": str})
    raw = pd.concat(sheets.values(), ignore_index=True)
    raw.to_csv(CACHE, index=False)
    return raw


def build(raw: pd.DataFrame) -> dict:
    cleaned = clean(raw)
    sales, returns = cleaned.sales, cleaned.returns
    both = pd.concat([sales, returns], ignore_index=True)

    dates = pd.to_datetime(both["InvoiceDate"]).dt.normalize().drop_duplicates().sort_values()
    dim_date = pd.DataFrame({
        "date_key": dates.dt.strftime("%Y%m%d").astype(int),
        "full_date": dates.dt.date,
        "year": dates.dt.year, "quarter": dates.dt.quarter, "month": dates.dt.month,
        "month_start": dates.dt.to_period("M").dt.start_time.dt.date,
        "day_of_week": dates.dt.dayofweek + 1,
    })

    countries = sorted(both["Country"].astype(str).unique())
    dim_country = pd.DataFrame({"country_key": range(1, len(countries) + 1), "country": countries})
    country_key = dict(zip(dim_country["country"], dim_country["country_key"]))

    known = both.dropna(subset=["Customer ID"])
    home = (known.groupby(["Customer ID", "Country"]).size().reset_index(name="n")
            .sort_values(["Customer ID", "n", "Country"], ascending=[True, False, True])
            .drop_duplicates("Customer ID"))
    dim_customer = pd.DataFrame({
        "customer_key": range(1, len(home) + 1),
        "customer_id": home["Customer ID"].astype(int).to_numpy(),
        "home_country_key": home["Country"].map(country_key).to_numpy(),
    })
    guest_country = country_key.get("Unspecified", dim_country["country_key"].iloc[0])
    dim_customer = pd.concat([pd.DataFrame({"customer_key": [0], "customer_id": [pd.NA],
                                            "home_country_key": [guest_country]}),
                              dim_customer], ignore_index=True)
    customer_key = dict(zip(dim_customer["customer_id"].dropna().astype(int),
                            dim_customer["customer_key"].iloc[1:]))

    # One description per product: the most frequent one in the sales lines.
    desc = (both.assign(Description=both["Description"].fillna("").astype(str).str.strip())
            .groupby(["StockCode", "Description"]).size().reset_index(name="n")
            .sort_values(["StockCode", "n", "Description"], ascending=[True, False, True])
            .drop_duplicates("StockCode"))
    dim_product = pd.DataFrame({
        "product_key": range(1, len(desc) + 1),
        "stock_code": desc["StockCode"].to_numpy(),
        "description": desc["Description"].replace("", "(no description)").to_numpy(),
    })
    product_key = dict(zip(dim_product["stock_code"], dim_product["product_key"]))

    def keys(frame: pd.DataFrame) -> pd.DataFrame:
        ts = pd.to_datetime(frame["InvoiceDate"])
        cust = frame["Customer ID"].map(lambda c: customer_key.get(int(c), 0) if pd.notna(c) else 0)
        return pd.DataFrame({
            "invoice": frame["Invoice"].astype(str),
            "date_key": ts.dt.strftime("%Y%m%d").astype(int),
            "invoice_ts": ts,
            "customer_key": cust.astype(int),
            "product_key": frame["StockCode"].map(product_key).astype(int),
            "country_key": frame["Country"].astype(str).map(country_key).astype(int),
            "quantity": frame["Quantity"].astype(int),
            "unit_price": frame["Price"].round(2),
        })

    fact_sales = keys(sales)
    fact_sales["revenue"] = (fact_sales["quantity"] * fact_sales["unit_price"]).round(2)
    # A price that rounds to 0.00 would break the CHECK; it is a sub-cent line.
    fact_sales = fact_sales[(fact_sales["unit_price"] > 0) & (fact_sales["revenue"] > 0)]

    fr = keys(returns)
    fact_returns = fr.drop(columns=["invoice_ts", "unit_price"])
    fact_returns["amount"] = (fr["quantity"] * fr["unit_price"]).round(2)

    return {"steps": cleaned.steps, "guest_lines": cleaned.guest_lines, "dim_date": dim_date, "dim_country": dim_country,
            "dim_customer": dim_customer, "dim_product": dim_product,
            "fact_sales": fact_sales, "fact_returns": fact_returns}


def copy(conn, table: str, frame: pd.DataFrame) -> None:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, header=False)
    with conn.cursor().copy(f"COPY {table} ({', '.join(frame.columns)}) FROM STDIN WITH (FORMAT csv)") as cp:
        cp.write(buffer.getvalue())


def main() -> int:
    tables = build(read_raw())
    print(format_steps(tables["steps"]))
    print(f"kept without Customer ID (guest, customer_key 0): {tables['guest_lines']:,} lines")
    print()
    with connect() as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        for name in ("dim_date", "dim_country", "dim_customer", "dim_product",
                     "fact_sales", "fact_returns"):
            copy(conn, name, tables[name])
        conn.commit()
        for name in ("dim_date", "dim_country", "dim_customer", "dim_product",
                     "fact_sales", "fact_returns"):
            count = conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            print(f"{name:<14} {count:>9,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
