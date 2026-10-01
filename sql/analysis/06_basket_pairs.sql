-- Which products are bought together? Market-basket pairs with support, confidence and lift.
--   support    = share of all orders that contain both products
--   confidence = share of the rarer product's orders that also contain the other one
--   lift       = how many times more often the pair occurs than if the two were independent
-- Threshold: a pair must be in at least 0.5% of orders (198 of 39,516 here). Lift on rare
-- pairs is noise - two products bought once, together, get a huge lift - and 0.5% keeps
-- about two hundred orders behind every number. It is a share, not a count, so the same
-- query runs unchanged on a small test set. Products below the threshold cannot be in a
-- pair above it, so they are pruned first (the Apriori trick); that keeps the self-join
-- to minutes' worth of rows instead of 47 million.
-- same_line: the two descriptions share a word of 3+ letters that is not a colour or a
-- filler (HERB MARKER MINT / HERB MARKER BASIL, KEY FOB SHED / KEY FOB BACK DOOR,
-- REGENCY TEAPOT / REGENCY MILK JUG): variants or pieces of one collection. A heuristic -
-- the source has no product category - so it is used to split the chart, not as a fact. Pairs without a shared word are different
-- products that customers combine on their own (a bucket and a spade).
WITH orders AS (
    SELECT count(DISTINCT invoice)::numeric AS n FROM fact_sales
),
item AS (
    SELECT product_key, count(DISTINCT invoice) AS n
    FROM fact_sales
    GROUP BY product_key
    HAVING count(DISTINCT invoice) >= 0.005 * (SELECT n FROM orders)
),
basket AS (
    SELECT DISTINCT f.invoice, f.product_key
    FROM fact_sales f JOIN item USING (product_key)
),
pair AS (
    SELECT a.product_key AS key_a, b.product_key AS key_b, count(*) AS n
    FROM basket a
    JOIN basket b ON a.invoice = b.invoice AND a.product_key < b.product_key
    GROUP BY a.product_key, b.product_key
    HAVING count(*) >= 0.005 * (SELECT n FROM orders)
)
SELECT pa.description                                              AS product_a,
       pb.description                                              AS product_b,
       p.n                                                         AS orders_together,
       round(100 * p.n / o.n, 2)                                   AS support_pct,
       round(100.0 * p.n / least(ia.n, ib.n), 1)                   AS confidence_pct,
       round(p.n * o.n / (ia.n::numeric * ib.n), 1)                AS lift,
       EXISTS (SELECT 1
               FROM unnest(regexp_split_to_array(upper(pa.description), '[^A-Z]+')) AS w
               WHERE length(w) >= 3
                 AND w NOT IN ('RED', 'PINK', 'BLUE', 'GREEN', 'WHITE', 'BLACK', 'IVORY', 'GOLD',
                               'SILVER', 'CREAM', 'PURPLE', 'YELLOW', 'ORANGE', 'BROWN', 'GREY',
                               'SET', 'THE', 'AND', 'WITH', 'DESIGN', 'LARGE', 'SMALL', 'MINI',
                               'VINTAGE')
                 AND w = ANY (regexp_split_to_array(upper(pb.description), '[^A-Z]+')))
                                                                   AS same_line
FROM pair p
JOIN item ia ON ia.product_key = p.key_a
JOIN item ib ON ib.product_key = p.key_b
JOIN dim_product pa ON pa.product_key = p.key_a
JOIN dim_product pb ON pb.product_key = p.key_b
CROSS JOIN orders o
ORDER BY lift DESC, product_a, product_b;
