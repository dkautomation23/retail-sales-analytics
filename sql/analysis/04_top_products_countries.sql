-- Top 10 products and top 10 countries by NET revenue (sales minus returns).
-- Ranking by gross sales put "PAPER CRAFT, LITTLE BIRDIE" in the top 5: it is
-- a single order of 80,995 units that was cancelled in full. Net revenue
-- removes it, which is why returns live in their own fact table.
WITH sold_p AS (SELECT product_key, sum(revenue) AS gross FROM fact_sales GROUP BY product_key),
ret_p AS (SELECT product_key, sum(amount) AS returned FROM fact_returns GROUP BY product_key),
sold_c AS (SELECT country_key, sum(revenue) AS gross FROM fact_sales GROUP BY country_key),
ret_c AS (SELECT country_key, sum(amount) AS returned FROM fact_returns GROUP BY country_key),
total AS (SELECT (SELECT sum(revenue) FROM fact_sales) - (SELECT sum(amount) FROM fact_returns) AS net)
(SELECT 'product' AS dimension,
        p.stock_code || ' ' || p.description                         AS name,
        s.gross,
        coalesce(r.returned, 0)                                       AS returned,
        s.gross - coalesce(r.returned, 0)                             AS net_revenue,
        round(100.0 * (s.gross - coalesce(r.returned, 0)) / (SELECT net FROM total), 2) AS share_of_net_pct
 FROM sold_p s
 LEFT JOIN ret_p r USING (product_key)
 JOIN dim_product p USING (product_key)
 ORDER BY net_revenue DESC
 LIMIT 10)
UNION ALL
(SELECT 'country',
        c.country,
        s.gross,
        coalesce(r.returned, 0),
        s.gross - coalesce(r.returned, 0),
        round(100.0 * (s.gross - coalesce(r.returned, 0)) / (SELECT net FROM total), 2)
 FROM sold_c s
 LEFT JOIN ret_c r USING (country_key)
 JOIN dim_country c USING (country_key)
 ORDER BY s.gross - coalesce(r.returned, 0) DESC
 LIMIT 10);
