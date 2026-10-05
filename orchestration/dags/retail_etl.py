"""Airflow DAG for the retail warehouse: is it loaded, is it clean, what does it say.

    docker compose -f docker-compose.yml -f docker-compose.airflow.yml run --rm airflow \
        bash -c "airflow db migrate > /dev/null && airflow dags test retail_etl 2026-10-01"

Three tasks in a chain. The load itself (python -m analytics.etl) is not a task here: it needs the
source workbook, which is not in the repository, so the DAG starts from a loaded warehouse.
"""
from __future__ import annotations

from datetime import datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PROJECT = "/opt/airflow/project"

with DAG(
    dag_id="retail_etl",
    schedule=None,
    start_date=datetime(2026, 10, 1),
    catchup=False,
    tags=["retail"],
) as dag:
    warehouse_loaded = BashOperator(
        task_id="warehouse_loaded",
        bash_command=(f"cd {PROJECT} && python -c \"from analytics.db import scalar; "
                      "n = scalar('SELECT count(*) FROM fact_sales'); print('fact_sales rows', n); "
                      "raise SystemExit(0 if n > 0 else 1)\""),
    )
    quality_checks = BashOperator(task_id="quality_checks", bash_command=f"cd {PROJECT} && python -m analytics.quality")
    findings = BashOperator(task_id="findings", bash_command=f"cd {PROJECT} && python -m analytics.findings")

    warehouse_loaded >> quality_checks >> findings
