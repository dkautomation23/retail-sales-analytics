"""Business findings, every number computed from the warehouse.

    python -m analytics.findings

The README quotes these lines verbatim and check.py compares them, so a number
in the README can never drift from what the data says.
"""
from __future__ import annotations

from .db import connect

SQL = {
    "net": "SELECT (SELECT sum(revenue) FROM fact_sales) - (SELECT sum(amount) FROM fact_returns)",
    "gross": "SELECT sum(revenue) FROM fact_sales",
    "returned": "SELECT sum(amount) FROM fact_returns",
    "uk_net": """SELECT (SELECT sum(revenue) FROM fact_sales JOIN dim_country USING (country_key)
                         WHERE country = 'United Kingdom')
                      - (SELECT sum(amount) FROM fact_returns JOIN dim_country USING (country_key)
                         WHERE country = 'United Kingdom')""",
    "guest_rev": "SELECT sum(revenue) FROM fact_sales WHERE customer_key = 0",
    "top2_returns": """SELECT sum(a) FROM (SELECT sum(amount) AS a FROM fact_returns
                       GROUP BY invoice ORDER BY a DESC LIMIT 2) t""",
    "nov_share": """SELECT sum(revenue) FILTER (WHERE d.month IN (9, 10, 11)) / sum(revenue)
                    FROM fact_sales f JOIN dim_date d USING (date_key)
                    WHERE d.full_date < '2011-12-01'""",
    "m1_retention": """WITH first_month AS (
                           SELECT customer_key, min(d.month_start) AS cohort
                           FROM fact_sales f JOIN dim_date d USING (date_key)
                           WHERE customer_key <> 0 GROUP BY customer_key),
                       next_month AS (
                           SELECT DISTINCT fm.customer_key
                           FROM first_month fm
                           JOIN fact_sales f USING (customer_key)
                           JOIN dim_date d USING (date_key)
                           WHERE d.month_start = fm.cohort + interval '1 month')
                       SELECT (SELECT count(*) FROM next_month)::numeric
                            / (SELECT count(*) FROM first_month
                               WHERE cohort < (SELECT max(month_start) FROM dim_date))""",
}

RFM = """
WITH ref AS (SELECT max(invoice_ts)::date + 1 AS day FROM fact_sales),
c AS (SELECT customer_key, (SELECT day FROM ref) - max(invoice_ts)::date AS r_days,
             count(DISTINCT invoice) AS freq, sum(revenue) AS money
      FROM fact_sales WHERE customer_key <> 0 GROUP BY customer_key),
s AS (SELECT *, 6 - ntile(5) OVER (ORDER BY r_days) AS r, ntile(5) OVER (ORDER BY freq) AS f FROM c)
SELECT count(*) FILTER (WHERE r >= 4 AND f >= 4)::numeric / count(*),
       sum(money) FILTER (WHERE r >= 4 AND f >= 4) / sum(money)
FROM s
"""


def compute() -> list:
    with connect() as conn:
        v = {k: float(conn.execute(q).fetchone()[0]) for k, q in SQL.items()}
        champ_customers, champ_revenue = (float(x) for x in conn.execute(RFM).fetchone())
    return [
        f"F1 Concentration: the United Kingdom is {100 * v['uk_net'] / v['net']:.1f}% of net revenue "
        f"({v['uk_net']:,.0f} of {v['net']:,.0f} GBP).",
        f"F2 Champions: {100 * champ_customers:.1f}% of identified customers (RFM Champions) "
        f"bring {100 * champ_revenue:.1f}% of identified-customer revenue.",
        f"F3 Seasonality: September-November is {100 * v['nov_share']:.1f}% of revenue "
        f"against 25.0% if sales were flat (Dec 2009 - Nov 2011; the partial Dec 2011 is excluded).",
        f"F4 Retention: {100 * v['m1_retention']:.1f}% of new customers buy again in the following month.",
        f"F5 Returns: {100 * v['returned'] / v['gross']:.2f}% of sold value is returned; "
        f"the two largest cancelled orders alone are {100 * v['top2_returns'] / v['returned']:.1f}% of it.",
        f"F6 Guests: {100 * v['guest_rev'] / v['gross']:.1f}% of revenue has no Customer ID and is "
        f"invisible to every customer-level metric.",
    ]


def main() -> int:
    for line in compute():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
