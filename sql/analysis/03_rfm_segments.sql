-- RFM: recency, frequency and monetary value scored 1-5 by quintile,
-- then mapped to named segments. Reference date = day after the last sale.
-- Monetary is NET (sales minus cancellations): otherwise an order keyed in and
-- cancelled the same day scores as a top customer.
-- customer_key breaks ties so equal customers always land in the same quintile
-- run after run; without it ntile splits ties in an arbitrary order.
WITH ref AS (SELECT max(invoice_ts)::date + 1 AS day FROM fact_sales),
cancelled AS (
    SELECT customer_key, sum(amount) AS amount
    FROM fact_returns WHERE customer_key <> 0 GROUP BY customer_key
),
per_customer AS (
    SELECT s.customer_key,
           (SELECT day FROM ref) - max(s.invoice_ts)::date AS recency_days,
           count(DISTINCT s.invoice)                        AS frequency,
           sum(s.revenue) - coalesce(max(c.amount), 0)      AS monetary
    FROM fact_sales s
    LEFT JOIN cancelled c USING (customer_key)
    WHERE s.customer_key <> 0
    GROUP BY s.customer_key
),
scored AS (
    SELECT *,
           6 - ntile(5) OVER (ORDER BY recency_days, customer_key) AS r,
           ntile(5) OVER (ORDER BY frequency, customer_key)        AS f,
           ntile(5) OVER (ORDER BY monetary, customer_key)         AS m
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
       sum(monetary)                                                AS net_revenue,
       round(100.0 * sum(monetary) / sum(sum(monetary)) OVER (), 1) AS share_of_revenue_pct,
       round(avg(recency_days))                                     AS avg_recency_days
FROM segmented
GROUP BY segment
ORDER BY net_revenue DESC;
