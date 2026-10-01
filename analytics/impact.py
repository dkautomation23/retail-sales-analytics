"""What is one percentage point of month-1 retention worth? An estimate, not a forecast.

    python -m analytics.impact

    value of +1 pp a year = new customers a month x 12 x 1%
                            x (12-month net revenue of a customer who came back in month 1
                               - 12-month net revenue of one who did not)

The difference, not the returning customer's whole revenue: customers who skip month 1
still buy later, and only the gap is what a second-order campaign could add.
"Next 12 months" = months +1 to +12 after the first purchase, so only cohorts with twelve
complete months behind them count (Jan 2010 - Nov 2010; data ends 9 Dec 2011). New
customers a month is the average over the complete cohorts used for F4 (Jan 2010 -
Oct 2011). Assumes a retained customer behaves like today's returners, which a campaign
does not guarantee - see Honest limits.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .db import connect

# Net revenue (sales minus cancellations) per identified customer per month, with the
# customer's first month. Cancellations count in the month they were booked.
MONTHLY_NET = """
WITH first AS (
    SELECT customer_key, min(d.month_start) AS cohort
    FROM fact_sales f JOIN dim_date d USING (date_key)
    WHERE customer_key <> 0 GROUP BY customer_key
),
sales AS (
    SELECT customer_key, d.month_start, sum(revenue) AS amount
    FROM fact_sales f JOIN dim_date d USING (date_key)
    WHERE customer_key <> 0 GROUP BY 1, 2
),
cancelled AS (
    SELECT customer_key, d.month_start, -sum(amount) AS amount
    FROM fact_returns r JOIN dim_date d USING (date_key)
    WHERE customer_key <> 0 GROUP BY 1, 2
)
SELECT customer_key, cohort, month_start,
       sum(amount)                AS net,
       sum(greatest(amount, 0))   AS sold        -- sales only: cancellations are negative
FROM (SELECT * FROM sales UNION ALL SELECT * FROM cancelled) m
JOIN first USING (customer_key)
GROUP BY customer_key, cohort, month_start
"""


@dataclass
class Impact:
    new_per_month: float
    returning_value: float
    other_value: float
    value_cohorts: tuple[str, str]
    size_cohorts: tuple[str, str]

    @property
    def per_point_per_year(self) -> float:
        return annual_value_of_one_point(self.new_per_month, self.returning_value, self.other_value)


def annual_value_of_one_point(new_per_month: float, returning_value: float, other_value: float) -> float:
    return new_per_month * 12 * 0.01 * (returning_value - other_value)


def months_between(start: pd.Series, end: pd.Series) -> pd.Series:
    return (end.dt.year - start.dt.year) * 12 + (end.dt.month - start.dt.month)


def twelve_month_values(monthly: pd.DataFrame, first_month: pd.Timestamp,
                        last_complete_month: pd.Timestamp) -> tuple[float, float, str, str]:
    """Average net revenue in months +1..+12 for month-1 returners and for everyone else,
    over cohorts after the first month of data whose month +12 is complete."""
    frame = monthly.copy()
    frame["cohort"] = pd.to_datetime(frame["cohort"])
    frame["month_start"] = pd.to_datetime(frame["month_start"])
    frame["offset"] = months_between(frame["cohort"], frame["month_start"])
    eligible = frame[(frame["cohort"] > first_month)          # first month = existing customers, not new
                     & (frame["cohort"] + pd.DateOffset(months=12) <= last_complete_month)]
    customers = eligible.groupby("customer_key")["cohort"].first()
    window = eligible[eligible["offset"].between(1, 12)]
    value = window.groupby("customer_key")["net"].sum().reindex(customers.index, fill_value=0).astype(float)
    came_back = window[(window["offset"] == 1) & (window["sold"] > 0)]["customer_key"].unique()  # as in F4
    returned = value.index.isin(came_back)
    return (float(value[returned].mean()), float(value[~returned].mean()),
            customers.min().strftime("%b %Y"), customers.max().strftime("%b %Y"))


def compute() -> Impact:
    from .findings import next_month_retention_cohorts
    with connect() as conn:
        cur = conn.execute(MONTHLY_NET)
        monthly = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
        first, partial = (pd.Timestamp(x) for x in
                          conn.execute("SELECT min(month_start), max(month_start) FROM dim_date").fetchone())
    monthly[["net", "sold"]] = monthly[["net", "sold"]].astype(float)
    returning, other, start, end = twelve_month_values(monthly, first, partial - pd.DateOffset(months=1))
    sizes = next_month_retention_cohorts()
    return Impact(new_per_month=float(sizes.mean()), returning_value=returning, other_value=other,
                  value_cohorts=(start, end),
                  size_cohorts=(sizes.index.min().strftime("%b %Y"), sizes.index.max().strftime("%b %Y")))


def main() -> int:
    i = compute()
    print(f"new customers a month ({i.size_cohorts[0]} - {i.size_cohorts[1]}): {i.new_per_month:,.1f}")
    print(f"12-month net revenue, cohorts {i.value_cohorts[0]} - {i.value_cohorts[1]}:")
    print(f"  came back in month 1: {i.returning_value:,.0f} GBP")
    print(f"  did not:              {i.other_value:,.0f} GBP")
    print(f"+1 pp of month-1 retention: about {i.per_point_per_year:,.0f} GBP of net revenue a year")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
