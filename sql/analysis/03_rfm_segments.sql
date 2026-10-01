-- RFM: recency, frequency and monetary value scored 1-5 by quintile,
-- then mapped to named segments. Reference date = day after the last sale.
WITH ref AS (SELECT max(invoice_ts)::date + 1 AS day FROM fact_sales),
per_customer AS (
    SELECT customer_key,
           (SELECT day FROM ref) - max(invoice_ts)::date AS recency_days,
           count(DISTINCT invoice)                        AS frequency,
           sum(revenue)                                   AS monetary
    FROM fact_sales
    WHERE customer_key <> 0
    GROUP BY customer_key
),
scored AS (
    SELECT *,
           6 - ntile(5) OVER (ORDER BY recency_days) AS r,
           ntile(5) OVER (ORDER BY frequency)        AS f,
           ntile(5) OVER (ORDER BY monetary)         AS m
    FROM per_customer
),
segmented AS (
    SELECT *,
           CASE
               WHEN r >= 4 AND f >= 4 THEN 'Champions'
               WHEN r >= 3 AND f >= 3 THEN 'Loyal'
               WHEN r >= 4 AND f <= 2 THEN 'New or promising'
               WHEN r <= 2 AND f >= 3 THEN 'At risk'
               WHEN r <= 2 AND f <= 2 THEN 'Lost'
               ELSE 'Needs attention'
           END AS segment
    FROM scored
)
SELECT segment,
       count(*)                                                     AS customers,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)           AS share_of_customers_pct,
       sum(monetary)                                                AS revenue,
       round(100.0 * sum(monetary) / sum(sum(monetary)) OVER (), 1) AS share_of_revenue_pct,
       round(avg(recency_days))                                     AS avg_recency_days
FROM segmented
GROUP BY segment
ORDER BY revenue DESC;
