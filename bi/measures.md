# DAX measures

Model: `fact_sales` and `fact_returns` both relate many-to-one to `dim_date[date_key]`,
`dim_product[product_key]`, `dim_customer[customer_key]` and `dim_country[country_key]`.
`dim_date` is a continuous calendar (739 days, no gaps), so it can be marked as the date
table on `full_date`. `fact_returns` holds cancellation invoices; the source does not
separate customer returns from cancelled orders.

```DAX
Gross Revenue = SUM ( fact_sales[revenue] )

Cancelled = SUM ( fact_returns[amount] )

Net Revenue = [Gross Revenue] - [Cancelled]

Orders = DISTINCTCOUNT ( fact_sales[invoice] )

Avg Order Value = DIVIDE ( [Gross Revenue], [Orders] )

-- The "return rate" of the brief: cancelled value as a share of sold value.
Cancellation Rate % = DIVIDE ( [Cancelled], [Gross Revenue] )

Identified Customers =
    CALCULATE ( DISTINCTCOUNT ( fact_sales[customer_key] ), fact_sales[customer_key] <> 0 )

-- Retention: identified customers in the selected month who also bought the month before.
Retention vs Prev Month % =
    VAR Retained =
        COUNTROWS (
            FILTER (
                VALUES ( fact_sales[customer_key] ),
                fact_sales[customer_key] <> 0
                    && CALCULATE (
                        COUNTROWS ( fact_sales ),
                        REMOVEFILTERS ( dim_date ),
                        DATEADD ( dim_date[full_date], -1, MONTH )
                    ) > 0
            )
        )
    RETURN DIVIDE ( Retained, [Identified Customers] )

Guest Revenue Share % =
    DIVIDE ( CALCULATE ( [Gross Revenue], fact_sales[customer_key] = 0 ), [Gross Revenue] )

Revenue MoM % =
    VAR Prev =
        CALCULATE ( [Gross Revenue], REMOVEFILTERS ( dim_date ), DATEADD ( dim_date[full_date], -1, MONTH ) )
    RETURN DIVIDE ( [Gross Revenue] - Prev, Prev )

Revenue YoY % =
    VAR Prev =
        CALCULATE ( [Gross Revenue], REMOVEFILTERS ( dim_date ), SAMEPERIODLASTYEAR ( dim_date[full_date] ) )
    RETURN DIVIDE ( [Gross Revenue] - Prev, Prev )
```

`REMOVEFILTERS ( dim_date )` matters when a visual filters on `month_start` or `year`
rather than on `full_date`: without it the shifted dates are intersected with the
current month and the result is blank.

## Expected values

Computed with SQL on the same warehouse. If the report shows anything else, a
relationship is missing or points the wrong way.

| Measure | Filter | Expected |
|---|---|---:|
| Net Revenue | none | 18,926,266 |
| Cancellation Rate % | none | 3.65% |
| Orders | none | 39,516 |
| Avg Order Value | none | 497.08 |
| Identified Customers | none | 5,852 |
| Guest Revenue Share % | none | 13.1% |
| Identified Customers | Nov 2011 | 1,660 |
| Retention vs Prev Month % | Nov 2011 | 37.1% |
| Revenue MoM % | Nov 2011 | 31.6% |
| Revenue YoY % | Nov 2011 | 1.6% |
