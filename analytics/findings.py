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

from . import queries, stats
from .db import connect

SQL = {
    "net": "SELECT (SELECT sum(revenue) FROM fact_sales) - (SELECT sum(amount) FROM fact_returns)",
    "gross": "SELECT sum(revenue) FROM fact_sales",
    "uk_net": """SELECT (SELECT sum(revenue) FROM fact_sales JOIN dim_country USING (country_key)
                         WHERE country = 'United Kingdom')
                      - (SELECT sum(amount) FROM fact_returns JOIN dim_country USING (country_key)
                         WHERE country = 'United Kingdom')""",
    "guest_rev": "SELECT sum(revenue) FROM fact_sales WHERE customer_key = 0",
    "top2_cancelled": """SELECT sum(a) FROM (SELECT sum(amount) AS a FROM fact_returns
                         GROUP BY invoice ORDER BY a DESC LIMIT 2) t""",
    "nov_share": """SELECT sum(revenue) FILTER (WHERE d.month IN (9, 10, 11)) / sum(revenue)
                    FROM fact_sales f JOIN dim_date d USING (date_key)
                    WHERE d.full_date < '2011-12-01'""",
}


def cohort_table() -> tuple[pd.DataFrame, pd.Timestamp]:
    cohorts = queries.run("02_cohort_retention")
    cohorts["cohort"] = pd.to_datetime(cohorts["cohort"])
    with connect() as conn:
        partial = pd.Timestamp(conn.execute("SELECT max(month_start) FROM dim_date").fetchone()[0])
    return cohorts, partial


def next_month_retention_cohorts() -> pd.Series:
    """Size of every cohort whose month +1 is complete (Jan 2010 - Oct 2011)."""
    cohorts, partial = cohort_table()
    sizes = cohorts[cohorts["months_since_first"] == 0].set_index("cohort")["cohort_customers"].astype(float)
    return sizes[sizes.index + pd.DateOffset(months=1) < partial]


def next_month_retention() -> tuple[float, str, str]:
    """Customers back in month +1, over every cohort whose month +1 is complete."""
    cohorts, _ = cohort_table()
    complete = next_month_retention_cohorts()
    back = cohorts[cohorts["months_since_first"] == 1].set_index("cohort")["active_customers"]
    rate = back.reindex(complete.index, fill_value=0).sum() / complete.sum()
    return float(rate), complete.index.min().strftime("%b %Y"), complete.index.max().strftime("%b %Y")


def seasonal_retention() -> dict:
    """Month-1 retention of customers first seen in Sep-Nov against those first seen in other
    months, over the same complete cohorts as F4, tested with a two-proportion z-test."""
    cohorts, _ = cohort_table()
    sizes = next_month_retention_cohorts()
    back = (cohorts[cohorts["months_since_first"] == 1].set_index("cohort")["active_customers"]
            .reindex(sizes.index, fill_value=0))
    season = sizes.index.month.isin([9, 10, 11])
    result = stats.two_proportion_test(int(back[season].sum()), int(sizes[season].sum()),
                                       int(back[~season].sum()), int(sizes[~season].sum()))
    result.update(n_season=int(sizes[season].sum()), n_other=int(sizes[~season].sum()))
    return result


def product_name(description: str) -> str:
    return " ".join(description.split()).strip(" ,").title()


def facts() -> dict:
    """Every number behind the findings and the recommendations, computed once."""
    from . import impact
    with connect() as conn:
        f = {k: float(conn.execute(q).fetchone()[0]) for k, q in SQL.items()}
    rfm = queries.run("03_rfm_segments").set_index("segment")
    f["champ_customers"] = float(rfm.loc["Champions", "share_of_customers_pct"])
    f["champ_revenue"] = float(rfm.loc["Champions", "share_of_revenue_pct"])
    f["retention"], f["ret_first"], f["ret_last"] = next_month_retention()
    rates = queries.run("05_return_rate").set_index("product")
    all_rate = rates.loc["ALL PRODUCTS, all cancellations"]
    real_rate = rates.loc["ALL PRODUCTS, same-day reversals excluded"]
    f["cancel_rate"] = float(all_rate["return_rate_pct"])
    f["real_cancel_rate"] = float(real_rate["return_rate_pct"])
    f["reversal_share"] = 1 - float(real_rate["returned"]) / float(all_rate["returned"])
    f["top2_cancel_share"] = f["top2_cancelled"] / float(all_rate["returned"])
    pairs = queries.run("06_basket_pairs").reset_index(drop=True)
    f["first_cross"] = int((~pairs["same_line"].astype(bool)).idxmax())  # pairs before it are one collection
    f["top_pair"], f["cross_pair"] = pairs.iloc[0], pairs.iloc[f["first_cross"]]
    f["impact"] = impact.compute()
    f["seasonal"] = seasonal_retention()
    arm = lambda months: f["impact"].new_per_month * months / 2  # noqa: E731 - customers per arm, 50/50 split
    f["mde_6m"] = stats.min_detectable_lift(f["retention"], arm(6))
    f["mde_12m"] = stats.min_detectable_lift(f["retention"], arm(12))
    return f


def pair_name(row) -> str:
    return f"{product_name(row['product_a'])} + {product_name(row['product_b'])}"


def findings_from(f: dict) -> list:
    i, top, cross, s = f["impact"], f["top_pair"], f["cross_pair"], f["seasonal"]
    p_text = "p < 0.001" if s["p"] < 0.001 else f"p = {s['p']:.3f}"
    return [
        f"F1 Concentration: the United Kingdom is {100 * f['uk_net'] / f['net']:.1f}% of net revenue "
        f"({f['uk_net']:,.0f} of {f['net']:,.0f} GBP).",
        f"F2 Champions: {f['champ_customers']:.1f}% of identified customers (RFM Champions) "
        f"bring {f['champ_revenue']:.1f}% of identified-customer net revenue.",
        f"F3 Seasonality: September-November is {100 * f['nov_share']:.1f}% of revenue "
        f"against 25.0% if sales were flat (Dec 2009 - Nov 2011; the partial Dec 2011 is excluded).",
        f"F4 Retention: {100 * f['retention']:.1f}% of new customers buy again in the following month "
        f"(cohorts {f['ret_first']} - {f['ret_last']}).",
        f"F5 Cancellations: {f['cancel_rate']:.2f}% of sold value is cancelled, but "
        f"{100 * f['reversal_share']:.1f}% of that is same-day reversals of a line just keyed in; "
        f"without them the rate is {f['real_cancel_rate']:.2f}%.",
        f"F6 Guests: {100 * f['guest_rev'] / f['gross']:.1f}% of revenue has no Customer ID and is "
        f"invisible to every customer-level metric.",
        f"F7 Baskets: customers buy collections - the {f['first_cross']} strongest product pairs are all "
        f"pieces of one collection (top: {pair_name(top)}, lift {float(top['lift']):.1f}); the strongest pair "
        f"across collections is {pair_name(cross)}, bought together {float(cross['lift']):.1f}x more often "
        f"than chance ({int(cross['orders_together'])} orders).",
        f"F8 Retention value: each +1 pp of month-1 retention is worth about "
        f"{i.per_point_per_year:,.0f} GBP of net revenue a year (an estimate: {i.new_per_month:,.0f} new "
        f"customers a month; in the next 12 months a month-1 returner brings {i.returning_value:,.0f} GBP, "
        f"other new customers {i.other_value:,.0f} GBP).",
        f"F9 Seasonal customers: {100 * s['rate1']:.1f}% of customers first seen in September-November buy "
        f"again the next month, against {100 * s['rate2']:.1f}% of those first seen in other months "
        f"(difference {100 * s['diff']:+.1f} pp, 95% interval {100 * s['low']:+.1f} to {100 * s['high']:+.1f} pp, "
        f"{p_text}; {s['n_season']:,} and {s['n_other']:,} customers). "
        + ("The difference is unlikely to be chance."
           if s["p"] < 0.05 else "The difference is not distinguishable from chance at the 5% level."),
    ]


def recommendations_from(f: dict) -> list:
    i, cross = f["impact"], f["cross_pair"]
    return [
        f"1. **Win the second order.** Only {100 * f['retention']:.1f}% of new customers buy again the next "
        f"month (F4). Test a first-month follow-up offer on half of new customers; each +1 pp it adds is "
        f"worth up to {i.per_point_per_year:,.0f} GBP a year (F8), which is the budget ceiling for the test. "
        f"Size it first: at {i.new_per_month:,.0f} new customers a month, a 50/50 split can only detect a lift of "
        f"{100 * f['mde_6m']:.1f} pp after 6 months ({100 * f['mde_12m']:.1f} pp after 12; 80% power, 5% "
        f"significance), so a +1 pp effect would be invisible and the offer must aim higher.",
        f"2. **Confirm large orders before they are booked.** {100 * f['reversal_share']:.1f}% of cancelled "
        f"value is lines reversed the same day (F5), and the two largest cancelled orders alone are "
        f"{100 * f['top2_cancel_share']:.1f}% of it. A confirmation step for unusually large quantities "
        f"would have caught both, and keeps phantom orders out of the sales and stock reports.",
        f"3. **Sell collections as sets.** The {f['first_cross']} strongest product pairs are pieces of one "
        f"collection (F7): offer bundles and a \"complete the set\" prompt on the product page. Put "
        f"cross-collection pairs such as {pair_name(cross)} (lift {float(cross['lift']):.1f}) next to each "
        f"other in the catalogue.",
    ]


def compute() -> list:
    return findings_from(facts())


README = Path(__file__).resolve().parent.parent / "README.md"
BLOCK = re.compile(r"(<!-- findings:start -->\s*```\n).*?(\n```\s*<!-- findings:end -->)", re.S)


REC_BLOCK = re.compile(r"(<!-- recommendations:start -->\s*).*?(\s*<!-- recommendations:end -->)", re.S)


def write_readme(lines: list, recs: list) -> None:
    text = README.read_text(encoding="utf-8")
    text = BLOCK.sub(lambda m: m.group(1) + "\n".join(lines) + m.group(2), text)
    text = REC_BLOCK.sub(lambda m: m.group(1) + "\n".join(recs) + "\n" + m.group(2).lstrip(), text)
    README.write_text(text, encoding="utf-8")


def main() -> int:
    f = facts()
    lines, recs = findings_from(f), recommendations_from(f)
    print("\n".join(lines + [""] + recs))
    if "--write-readme" in sys.argv:  # the only way numbers get into the README
        write_readme(lines, recs)
        print(f"updated the findings and recommendations blocks in {README.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
