-- Same logic as sql/analysis/01_monthly_revenue.sql, as a table BI tools can read.
with sales as (
    select month_start,
           sum(revenue)                                              as revenue,
           count(distinct invoice)                                   as orders,
           count(distinct customer_key) filter (where is_identified) as customers
    from {{ ref('stg_sales') }}
    group by month_start
),
cancelled as (
    select month_start, sum(amount) as cancelled
    from {{ ref('stg_cancellations') }}
    group by month_start
)
select s.month_start,
       s.revenue,
       coalesce(c.cancelled, 0)                   as cancelled,
       s.revenue - coalesce(c.cancelled, 0)       as net_revenue,
       s.orders,
       s.customers,
       round(s.revenue / s.orders, 2)             as avg_order_value,
       s.month_start = max(s.month_start) over () as partial_month
from sales s
left join cancelled c using (month_start)
