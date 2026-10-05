"""One place for the connection string. Defaults match docker-compose.yml."""
import os

import psycopg

DSN = os.environ.get("RETAIL_DSN", "postgresql://retail:retail@127.0.0.1:5433/retail")


def connect() -> psycopg.Connection:
    return psycopg.connect(DSN)


def scalar(sql: str, params=None):
    with connect() as conn:
        return conn.execute(sql, params).fetchone()[0]
