select product_key, stock_code, description
from {{ source('warehouse', 'dim_product') }}
