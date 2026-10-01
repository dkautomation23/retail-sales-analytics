-- One row per invoice line that is a real sale, with its calendar month.
select
    s.invoice,
    s.invoice_ts,
    d.full_date      as order_date,
    d.month_start,
    s.customer_key,
    s.customer_key <> 0 as is_identified,
    s.product_key,
    s.country_key,
    s.quantity,
    s.unit_price,
    s.revenue
from {{ source('warehouse', 'fact_sales') }} s
join {{ source('warehouse', 'dim_date') }} d using (date_key)
