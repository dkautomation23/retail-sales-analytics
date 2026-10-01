-- Star schema for UCI Online Retail II.
-- Grain of fact_sales: one invoice line that is a real product sale.
-- Cancellations go to fact_returns with the same keys, so return rates can be
-- computed without mixing negative quantities into revenue.

DROP TABLE IF EXISTS fact_returns, fact_sales, dim_product, dim_customer, dim_country, dim_date CASCADE;

CREATE TABLE dim_date (
    date_key      integer PRIMARY KEY,          -- yyyymmdd
    full_date     date    NOT NULL UNIQUE,
    year          smallint NOT NULL,
    quarter       smallint NOT NULL,
    month         smallint NOT NULL,
    month_start   date    NOT NULL,
    day_of_week   smallint NOT NULL             -- 1 = Monday
);

CREATE TABLE dim_country (
    country_key   integer PRIMARY KEY,
    country       text    NOT NULL UNIQUE
);

CREATE TABLE dim_customer (
    customer_key  integer PRIMARY KEY,          -- 0 = guest, no Customer ID in the source
    customer_id   integer UNIQUE,
    home_country_key integer NOT NULL REFERENCES dim_country
);

CREATE TABLE dim_product (
    product_key   integer PRIMARY KEY,
    stock_code    text    NOT NULL UNIQUE,
    description   text    NOT NULL
);

CREATE TABLE fact_sales (
    invoice       text     NOT NULL,
    date_key      integer  NOT NULL REFERENCES dim_date,
    invoice_ts    timestamp NOT NULL,
    customer_key  integer  NOT NULL REFERENCES dim_customer,
    product_key   integer  NOT NULL REFERENCES dim_product,
    country_key   integer  NOT NULL REFERENCES dim_country,
    quantity      integer  NOT NULL CHECK (quantity > 0),
    unit_price    numeric(12, 2) NOT NULL CHECK (unit_price > 0),
    revenue       numeric(14, 2) NOT NULL CHECK (revenue > 0)
);

CREATE TABLE fact_returns (
    invoice       text     NOT NULL,
    date_key      integer  NOT NULL REFERENCES dim_date,
    customer_key  integer  NOT NULL REFERENCES dim_customer,
    product_key   integer  NOT NULL REFERENCES dim_product,
    country_key   integer  NOT NULL REFERENCES dim_country,
    quantity      integer  NOT NULL CHECK (quantity > 0),   -- stored positive
    amount        numeric(14, 2) NOT NULL CHECK (amount >= 0)
);

CREATE INDEX ON fact_sales (date_key);
CREATE INDEX ON fact_sales (customer_key);
CREATE INDEX ON fact_sales (product_key);
CREATE INDEX ON fact_returns (product_key);
