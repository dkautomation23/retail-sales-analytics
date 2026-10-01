select country_key, country
from {{ source('warehouse', 'dim_country') }}
