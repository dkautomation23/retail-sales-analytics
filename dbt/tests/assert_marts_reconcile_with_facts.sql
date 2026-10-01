-- Fails (returns rows) if a mart loses or double-counts money on the way from the facts.
-- The RFM mart covers customers who bought in the period, so the cancellations of the
-- 23 customers who only cancel (their purchases predate the data) are reconciled
-- separately instead of being hidden in a tolerance.
with facts as (
    select (select sum(revenue) from {{ source('warehouse', 'fact_sales') }})  as revenue,
           (select sum(amount)  from {{ source('warehouse', 'fact_returns') }}) as cancelled,
           (select sum(revenue) from {{ source('warehouse', 'fact_sales') }} where customer_key <> 0)
         - (select sum(amount)  from {{ source('warehouse', 'fact_returns') }} r
            where customer_key <> 0
              and exists (select 1 from {{ source('warehouse', 'fact_sales') }} s
                          where s.customer_key = r.customer_key))               as identified_net
),
marts as (
    select (select sum(revenue)   from {{ ref('mart_monthly_revenue') }}) as revenue,
           (select sum(cancelled) from {{ ref('mart_monthly_revenue') }}) as cancelled,
           (select sum(monetary)  from {{ ref('mart_customer_rfm') }})    as identified_net
)
select *
from facts, marts
where abs(facts.revenue - marts.revenue) > 0.01
   or abs(facts.cancelled - marts.cancelled) > 0.01
   or abs(facts.identified_net - marts.identified_net) > 0.01
