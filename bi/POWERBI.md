# Building the Power BI report (30-40 minutes)

The warehouse is already modelled as a star, so Power BI only needs the tables,
the relationships and the measures in `measures.md`.

**Shortcut:** `retail-sales.pbip` in this folder already has the tables, relationships, date
table, all measures and a one-page report. Start the database, open the file in Power BI
Desktop, enter the database credentials (user `retail`, password `retail`), press *Refresh*,
then check the numbers against the expected values in `measures.md`. The steps below are the
same model built by hand.

## 1. Get the data

Option A - straight from PostgreSQL (database running via `docker compose up -d db`):

1. *Get data* -> *PostgreSQL database*.
2. Server `127.0.0.1:5433`, database `retail`, mode *Import*.
3. Credentials: *Database*, user `retail`, password `retail` (local demo container only).
4. Select `public.dim_date`, `dim_country`, `dim_customer`, `dim_product`,
   `fact_sales`, `fact_returns` -> *Load*.

Option B - from CSV: `python -m analytics.export_bi`, then *Get data* -> *Text/CSV* for
each file in `bi/data/`.

## 2. Model

1. *Model view*: create the relationships from `fact_sales` and from `fact_returns`
   to each dimension on the `*_key` columns (many-to-one, single direction).
2. `dim_date` -> *Mark as date table* -> `full_date`.
3. Hide every `*_key` column from report view.

## 3. Measures

Paste the measures from `measures.md` into a new table `Measures`.
Check the numbers against the "Expected values" table at the end of `measures.md`.

## 4. Report page

| Visual | Fields |
|---|---|
| 5 cards | Net Revenue, Orders, Avg Order Value, Identified Customers, Cancellation Rate % |
| Line chart | `dim_date[month_start]`, Gross Revenue |
| Matrix (retention) | rows: first month (see note), columns: months since, values: customers |
| Clustered bar | `dim_country[country]` (filter out United Kingdom), Net Revenue, top 10 |
| Clustered bar | `dim_product[description]`, Net Revenue, top 10 |
| Slicers | `dim_date[year]`, `dim_country[country]` |

Note: cohort retention is easiest as a SQL view - `sql/analysis/02_cohort_retention.sql`
can be loaded as a query in step 1 (*Advanced options* -> *SQL statement*).

## 5. Save

Save as `bi/retail-sales.pbix` and export one page to `bi/retail-sales.pdf` for people
without Power BI.
