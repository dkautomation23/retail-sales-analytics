-- Share of each first-purchase cohort that bought again N months later.
-- Guests (customer_key 0) are excluded: they cannot be followed over time.
WITH first_month AS (
    SELECT customer_key, min(d.month_start) AS cohort
    FROM fact_sales f JOIN dim_date d USING (date_key)
    WHERE customer_key <> 0
    GROUP BY customer_key
),
activity AS (
    SELECT DISTINCT f.customer_key, d.month_start
    FROM fact_sales f JOIN dim_date d USING (date_key)
    WHERE f.customer_key <> 0
),
cohort_size AS (
    SELECT cohort, count(*) AS customers FROM first_month GROUP BY cohort
)
SELECT fm.cohort,
       (extract(year FROM age(a.month_start, fm.cohort)) * 12
        + extract(month FROM age(a.month_start, fm.cohort)))::int AS months_since_first,
       count(*)                                                    AS active_customers,
       round(100.0 * count(*) / cs.customers, 1)                   AS retention_pct
FROM first_month fm
JOIN activity a USING (customer_key)
JOIN cohort_size cs USING (cohort)
GROUP BY fm.cohort, months_since_first, cs.customers
ORDER BY fm.cohort, months_since_first;
