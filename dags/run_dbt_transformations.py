"""DAG: run_dbt_transformations

Runs dbt after any raw ingestion DAG updates its dataset.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task

from dags._datasets import (
    RAW_ADVANCED_STATS_DATASET,
    RAW_MATCHES_DATASET,
    RAW_SCORERS_DATASET,
    RAW_STANDINGS_DATASET,
)
from dags._pipeline import run_dbt_command

DEFAULT_ARGS = {
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
}


@dag(
    dag_id="run_dbt_transformations",
    schedule=[
        RAW_MATCHES_DATASET,
        RAW_STANDINGS_DATASET,
        RAW_SCORERS_DATASET,
        RAW_ADVANCED_STATS_DATASET,
    ],
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["automation", "dbt"],
    doc_md=__doc__,
)
def run_dbt_transformations() -> None:

    @task()
    def dbt_run() -> None:
        """Build dbt models after ingestion updates raw data."""
        run_dbt_command(["run"])

    @task()
    def dbt_test() -> None:
        """Validate dbt models after the run completes."""
        run_dbt_command(["test"])

    dbt_run() >> dbt_test()


run_dbt_transformations()
