-- Revenue, orders and customers by month, with month-over-month growth.
-- Dec 2011 is cut off on the 9th in the source; it is flagged, not dropped.
WITH monthly AS (
    SELECT d.month_start,
           sum(f.revenue)                          AS revenue,
           count(DISTINCT f.invoice)               AS orders,
           count(DISTINCT f.customer_key) FILTER (WHERE f.customer_key <> 0) AS customers
    FROM fact_sales f
    JOIN dim_date d USING (date_key)
    GROUP BY d.month_start
)
SELECT month_start,
       revenue,
       orders,
       customers,
       round(revenue / orders, 2)                                              AS avg_order_value,
       round(100.0 * (revenue / lag(revenue) OVER (ORDER BY month_start) - 1), 1) AS mom_growth_pct,
       month_start = (SELECT max(month_start) FROM monthly)                    AS partial_month
FROM monthly
ORDER BY month_start;
