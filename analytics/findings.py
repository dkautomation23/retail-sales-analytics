"""Business findings, every number computed from the warehouse.

    python -m analytics.findings                  # print
    python -m analytics.findings --write-readme   # print and refresh the README block

The README quotes these lines verbatim and check.py compares them, so a number
in the README can never drift from what the data says. RFM, retention and
cancellations reuse the files in sql/analysis/, so a finding and its chart
cannot disagree.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from . import queries
from .db import connect

SQL = {
    "net": "SELECT (SELECT sum(revenue) FROM fact_sales) - (SELECT sum(amount) FROM fact_returns)",
    "gross": "SELECT sum(revenue) FROM fact_sales",
    "uk_net": """SELECT (SELECT sum(revenue) FROM fact_sales JOIN dim_country USING (country_key)
                         WHERE country = 'United Kingdom')
                      - (SELECT sum(amount) FROM fact_returns JOIN dim_country USING (country_key)
                         WHERE country = 'United Kingdom')""",
    "guest_rev": "SELECT sum(revenue) FROM fact_sales WHERE customer_key = 0",
    "nov_share": """SELECT sum(revenue) FILTER (WHERE d.month IN (9, 10, 11)) / sum(revenue)
                    FROM fact_sales f JOIN dim_date d USING (date_key)
                    WHERE d.full_date < '2011-12-01'""",
}


def next_month_retention() -> tuple[float, str, str]:
    """Customers back in month +1, over every cohort whose month +1 is complete."""
    cohorts = queries.run("02_cohort_retention")
    cohorts["cohort"] = pd.to_datetime(cohorts["cohort"])
    sizes = cohorts[cohorts["months_since_first"] == 0].set_index("cohort")["cohort_customers"]
    back = cohorts[cohorts["months_since_first"] == 1].set_index("cohort")["active_customers"]
    with connect() as conn:
        partial = pd.Timestamp(conn.execute("SELECT max(month_start) FROM dim_date").fetchone()[0])
    complete = sizes[sizes.index + pd.DateOffset(months=1) < partial]
    rate = back.reindex(complete.index, fill_value=0).sum() / complete.sum()
    return float(rate), complete.index.min().strftime("%b %Y"), complete.index.max().strftime("%b %Y")


def product_name(description: str) -> str:
    return " ".join(description.split()).strip(" ,").title()


def basket_finding() -> str:
    pairs = queries.run("06_basket_pairs").reset_index(drop=True)
    same = pairs["same_line"].astype(bool)
    first_cross = int((~same).idxmax())          # 0-based rank of the first pair across collections
    top, cross = pairs.iloc[0], pairs.iloc[first_cross]
    return (f"F7 Baskets: customers buy collections - the {first_cross} strongest product pairs are all "
            f"pieces of one collection (top: {product_name(top['product_a'])} + {product_name(top['product_b'])}, "
            f"lift {float(top['lift']):.1f}); the strongest pair across collections is "
            f"{product_name(cross['product_a'])} + {product_name(cross['product_b'])}, bought together "
            f"{float(cross['lift']):.1f}x more often than chance ({int(cross['orders_together'])} orders).")


def compute() -> list:
    with connect() as conn:
        v = {k: float(conn.execute(q).fetchone()[0]) for k, q in SQL.items()}
    rfm = queries.run("03_rfm_segments").set_index("segment")
    champ_customers = float(rfm.loc["Champions", "share_of_customers_pct"])
    champ_revenue = float(rfm.loc["Champions", "share_of_revenue_pct"])
    retention, first, last = next_month_retention()
    rates = queries.run("05_return_rate").set_index("product")
    all_rate = rates.loc["ALL PRODUCTS, all cancellations"]
    real_rate = rates.loc["ALL PRODUCTS, same-day reversals excluded"]
    reversal_share = 1 - float(real_rate["returned"]) / float(all_rate["returned"])
    return [
        f"F1 Concentration: the United Kingdom is {100 * v['uk_net'] / v['net']:.1f}% of net revenue "
        f"({v['uk_net']:,.0f} of {v['net']:,.0f} GBP).",
        f"F2 Champions: {champ_customers:.1f}% of identified customers (RFM Champions) "
        f"bring {champ_revenue:.1f}% of identified-customer net revenue.",
        f"F3 Seasonality: September-November is {100 * v['nov_share']:.1f}% of revenue "
        f"against 25.0% if sales were flat (Dec 2009 - Nov 2011; the partial Dec 2011 is excluded).",
        f"F4 Retention: {100 * retention:.1f}% of new customers buy again in the following month "
        f"(cohorts {first} - {last}).",
        f"F5 Cancellations: {float(all_rate['return_rate_pct']):.2f}% of sold value is cancelled, but "
        f"{100 * reversal_share:.1f}% of that is same-day reversals of a line just keyed in; "
        f"without them the rate is {float(real_rate['return_rate_pct']):.2f}%.",
        f"F6 Guests: {100 * v['guest_rev'] / v['gross']:.1f}% of revenue has no Customer ID and is "
        f"invisible to every customer-level metric.",
        basket_finding(),
    ]


README = Path(__file__).resolve().parent.parent / "README.md"
BLOCK = re.compile(r"(<!-- findings:start -->\s*```\n).*?(\n```\s*<!-- findings:end -->)", re.S)


def main() -> int:
    lines = compute()
    for line in lines:
        print(line)
    if "--write-readme" in sys.argv:  # the only way numbers get into the README
        text = README.read_text(encoding="utf-8")
        README.write_text(BLOCK.sub(lambda m: m.group(1) + "\n".join(lines) + m.group(2), text), encoding="utf-8")
        print(f"updated the findings block in {README.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
