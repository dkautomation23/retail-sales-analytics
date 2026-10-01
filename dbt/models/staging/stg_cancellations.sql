-- One row per cancelled invoice line (C-invoices), amount stored positive.
select
    r.invoice,
    d.full_date      as cancel_date,
    d.month_start,
    r.customer_key,
    r.product_key,
    r.country_key,
    r.quantity,
    r.amount
from {{ source('warehouse', 'fact_returns') }} r
join {{ source('warehouse', 'dim_date') }} d using (date_key)
