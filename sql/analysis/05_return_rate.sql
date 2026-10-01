-- Returned value as a share of sold value, overall and for products with
-- at least 1,000 in sales (smaller ones make the ratio noise).
WITH sold AS (
    SELECT product_key, sum(revenue) AS sold FROM fact_sales GROUP BY product_key
),
returned AS (
    SELECT product_key, sum(amount) AS returned FROM fact_returns GROUP BY product_key
)
(SELECT 'ALL PRODUCTS' AS product,
        (SELECT sum(sold) FROM sold) AS sold,
        (SELECT sum(returned) FROM returned) AS returned,
        round(100.0 * (SELECT sum(returned) FROM returned) / (SELECT sum(sold) FROM sold), 2) AS return_rate_pct)
UNION ALL
(SELECT p.stock_code || ' ' || p.description, s.sold, r.returned,
        round(100.0 * r.returned / s.sold, 2)
 FROM sold s
 JOIN returned r USING (product_key)
 JOIN dim_product p USING (product_key)
 WHERE s.sold >= 1000
 ORDER BY r.returned / s.sold DESC
 LIMIT 10);
