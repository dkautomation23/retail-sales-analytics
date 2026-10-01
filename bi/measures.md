# DAX measures

Model: `fact_sales` and `fact_returns` both relate many-to-one to `dim_date[date_key]`,
`dim_product[product_key]`, `dim_customer[customer_key]` and `dim_country[country_key]`.
Mark `dim_date` as the date table on `full_date`.

```DAX
Gross Revenue = SUM ( fact_sales[revenue] )

Returned = SUM ( fact_returns[amount] )

Net Revenue = [Gross Revenue] - [Returned]

Orders = DISTINCTCOUNT ( fact_sales[invoice] )

Avg Order Value = DIVIDE ( [Gross Revenue], [Orders] )

Return Rate % = DIVIDE ( [Returned], [Gross Revenue] )

Identified Customers =
    CALCULATE ( DISTINCTCOUNT ( fact_sales[customer_key] ), fact_sales[customer_key] <> 0 )

-- Retention: identified customers in the selected month who also bought the month before.
Retention vs Prev Month % =
    VAR Retained =
        COUNTROWS (
            FILTER (
                VALUES ( fact_sales[customer_key] ),
                fact_sales[customer_key] <> 0
                    && CALCULATE ( COUNTROWS ( fact_sales ), DATEADD ( dim_date[full_date], -1, MONTH ) ) > 0
            )
        )
    RETURN DIVIDE ( Retained, [Identified Customers] )

Guest Revenue Share % =
    DIVIDE ( CALCULATE ( [Gross Revenue], fact_sales[customer_key] = 0 ), [Gross Revenue] )

Revenue MoM % =
    VAR Prev = CALCULATE ( [Gross Revenue], DATEADD ( dim_date[full_date], -1, MONTH ) )
    RETURN DIVIDE ( [Gross Revenue] - Prev, Prev )

Revenue YoY % =
    VAR Prev = CALCULATE ( [Gross Revenue], SAMEPERIODLASTYEAR ( dim_date[full_date] ) )
    RETURN DIVIDE ( [Gross Revenue] - Prev, Prev )
```

Check after building: with no filters, `Net Revenue` must show 18,926,266 and
`Return Rate %` 3.65% - the same numbers `python -m analytics.findings` prints.
If they differ, a relationship is missing or points the wrong way.
