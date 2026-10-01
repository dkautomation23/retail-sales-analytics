-- One row per identified customer with RFM scores and segment.
-- Same rules as sql/analysis/03_rfm_segments.sql: net monetary, customer_key breaks ties.
with ref_day as (
    select max(invoice_ts)::date + 1 as day from {{ ref('stg_sales') }}
),
cancelled as (
    select customer_key, sum(amount) as amount
    from {{ ref('stg_cancellations') }}
    where customer_key <> 0
    group by customer_key
),
per_customer as (
    select s.customer_key,
           (select day from ref_day) - max(s.invoice_ts)::date as recency_days,
           count(distinct s.invoice)                           as frequency,
           sum(s.revenue) - coalesce(max(c.amount), 0)         as monetary
    from {{ ref('stg_sales') }} s
    left join cancelled c using (customer_key)
    where s.is_identified
    group by s.customer_key
),
scored as (
    select *,
           6 - ntile(5) over (order by recency_days, customer_key) as r,
           ntile(5) over (order by frequency, customer_key)        as f,
           ntile(5) over (order by monetary, customer_key)         as m
    from per_customer
)
select *,
       case
           when r >= 4 and f >= 4 then 'Champions'
           when r >= 3 and f >= 3 then 'Loyal'
           when r >= 4 and f <= 2 then 'New or promising'
           when r <= 2 and f >= 3 then 'At risk'
           when r <= 2 and f <= 2 then 'Lost'
           else 'Needs attention'
       end as segment
from scored
