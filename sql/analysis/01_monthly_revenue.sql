-- Revenue, orders and customers by month, with month-over-month growth.
-- Net revenue = sales minus cancellations booked in the same month.
-- Dec 2011 is cut off on the 9th in the source; it is flagged, not dropped.
WITH monthly AS (
    SELECT d.month_start,
           sum(f.revenue)                          AS revenue,
           count(DISTINCT f.invoice)               AS orders,
           count(DISTINCT f.customer_key) FILTER (WHERE f.customer_key <> 0) AS customers
    FROM fact_sales f
    JOIN dim_date d USING (date_key)
    GROUP BY d.month_start
),
cancelled AS (
    SELECT d.month_start, sum(r.amount) AS cancelled
    FROM fact_returns r
    JOIN dim_date d USING (date_key)
    GROUP BY d.month_start
)
SELECT m.month_start,
       m.revenue,
       coalesce(c.cancelled, 0)                                                    AS cancelled,
       m.revenue - coalesce(c.cancelled, 0)                                        AS net_revenue,
       m.orders,
       m.customers,
       round(m.revenue / m.orders, 2)                                              AS avg_order_value,
       round(100.0 * (m.revenue / lag(m.revenue) OVER (ORDER BY m.month_start) - 1), 1) AS mom_growth_pct,
       m.month_start = (SELECT max(month_start) FROM monthly)                      AS partial_month
FROM monthly m
LEFT JOIN cancelled c USING (month_start)
ORDER BY m.month_start;
