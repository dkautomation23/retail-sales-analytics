-- Cancelled value as a share of sold value.
-- Half of all cancelled value is a "same-day reversal": a cancellation line that
-- mirrors a sale line exactly (same customer, product, quantity, amount, day) -
-- an order keyed in and taken back, not goods coming back. The overall rate is
-- shown both ways; the product ranking leaves reversals out on both sides, so a
-- mis-keyed bulk order cannot top it. Products need 1,000+ GBP in real sales.
WITH reversal AS (
    SELECT r.invoice, r.customer_key, r.product_key, r.quantity, r.amount, r.date_key
    FROM fact_returns r
    WHERE r.customer_key <> 0
      AND EXISTS (SELECT 1 FROM fact_sales s
                  WHERE (s.customer_key, s.product_key, s.quantity, s.revenue, s.date_key)
                      = (r.customer_key, r.product_key, r.quantity, r.amount, r.date_key))
),
real_sales AS (
    SELECT s.product_key, s.revenue FROM fact_sales s
    WHERE NOT EXISTS (SELECT 1 FROM reversal v
                      WHERE (v.customer_key, v.product_key, v.quantity, v.amount, v.date_key)
                          = (s.customer_key, s.product_key, s.quantity, s.revenue, s.date_key))
),
real_returns AS (
    SELECT r.product_key, r.amount FROM fact_returns r
    WHERE NOT EXISTS (SELECT 1 FROM reversal v
                      WHERE (v.invoice, v.product_key, v.quantity, v.amount)
                          = (r.invoice, r.product_key, r.quantity, r.amount))
),
sold AS (SELECT product_key, sum(revenue) AS sold FROM real_sales GROUP BY product_key),
returned AS (SELECT product_key, sum(amount) AS returned FROM real_returns GROUP BY product_key)
(SELECT 'ALL PRODUCTS, all cancellations' AS product,
        (SELECT sum(revenue) FROM fact_sales) AS sold,
        (SELECT sum(amount) FROM fact_returns) AS returned,
        round(100.0 * (SELECT sum(amount) FROM fact_returns) / (SELECT sum(revenue) FROM fact_sales), 2)
            AS return_rate_pct)
UNION ALL
(SELECT 'ALL PRODUCTS, same-day reversals excluded',
        (SELECT sum(revenue) FROM real_sales),
        (SELECT sum(amount) FROM real_returns),
        round(100.0 * (SELECT sum(amount) FROM real_returns) / (SELECT sum(revenue) FROM real_sales), 2))
UNION ALL
(SELECT p.stock_code || ' ' || p.description, s.sold, r.returned,
        round(100.0 * r.returned / s.sold, 2)
 FROM sold s
 JOIN returned r USING (product_key)
 JOIN dim_product p USING (product_key)
 WHERE s.sold >= 1000
 ORDER BY r.returned / s.sold DESC, p.stock_code
 LIMIT 10);
