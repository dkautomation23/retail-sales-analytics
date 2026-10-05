FROM apache/airflow:3.3.2-python3.12

# The same pinned libraries as requirements.txt, only what analytics.quality and analytics.findings import.
RUN pip install --no-cache-dir "pandas==2.3.3" "psycopg[binary]==3.2.10"
