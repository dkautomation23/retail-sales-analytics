-- Share of each first-purchase cohort that bought again N months later.
-- Guests (customer_key 0) are excluded: they cannot be followed over time.
-- Two edges are cut so they do not pass for behaviour:
--   * the first month of data (Dec 2009) is not a cohort of new customers, it is
--     everyone who was already buying when the data starts;
--   * the last month (Dec 2011) has only 8 trading days, so activity in it is
--     left out instead of showing as a drop in retention.
WITH bounds AS (
    SELECT min(month_start) AS first_month, max(month_start) AS partial_month FROM dim_date
),
first_month AS (
    SELECT customer_key, min(d.month_start) AS cohort
    FROM fact_sales f JOIN dim_date d USING (date_key)
    WHERE customer_key <> 0
    GROUP BY customer_key
),
activity AS (
    SELECT DISTINCT f.customer_key, d.month_start
    FROM fact_sales f JOIN dim_date d USING (date_key)
    WHERE f.customer_key <> 0
      AND d.month_start < (SELECT partial_month FROM bounds)
),
cohort_size AS (
    SELECT cohort, count(*) AS customers FROM first_month GROUP BY cohort
)
SELECT fm.cohort,
       (extract(year FROM age(a.month_start, fm.cohort)) * 12
        + extract(month FROM age(a.month_start, fm.cohort)))::int AS months_since_first,
       count(*)                                                    AS active_customers,
       cs.customers                                                AS cohort_customers,
       round(100.0 * count(*) / cs.customers, 1)                   AS retention_pct
FROM first_month fm
JOIN activity a USING (customer_key)
JOIN cohort_size cs USING (cohort)
WHERE fm.cohort > (SELECT first_month FROM bounds)
GROUP BY fm.cohort, months_since_first, cs.customers
ORDER BY fm.cohort, months_since_first;
