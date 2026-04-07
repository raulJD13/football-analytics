"""DAG: retrain_model

Runs the full weekly training pipeline:
dbt run -> dbt test -> Poisson -> classifier -> ensemble.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task

from dags._pipeline import (
    AIRFLOW_PROJECT_ROOT,
    CLICKHOUSE_DB,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PORT,
    MLFLOW_TRACKING_URI,
    run_command,
    run_dbt_command,
)

DEFAULT_ARGS = {
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": True,
}


@dag(
    dag_id="retrain_model",
    schedule="0 3 * * 1",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["automation", "ml", "dbt"],
    doc_md=__doc__,
)
def retrain_model() -> None:

    @task()
    def dbt_run() -> None:
        """Build dbt models before training."""
        run_dbt_command(["run"])

    @task()
    def dbt_test() -> None:
        """Run dbt quality checks before training."""
        run_dbt_command(["test"])

    @task()
    def train_poisson() -> None:
        """Train and register the Poisson model."""
        run_command(
            [
                "python",
                "ml/scripts/train_poisson.py",
                "--ch-host",
                CLICKHOUSE_HOST,
                "--ch-port",
                CLICKHOUSE_PORT,
                "--ch-db",
                CLICKHOUSE_DB,
                "--mlflow-uri",
                MLFLOW_TRACKING_URI,
            ],
            cwd=AIRFLOW_PROJECT_ROOT,
        )

    @task()
    def train_classifier() -> None:
        """Train and register the calibrated XGBoost classifier."""
        run_command(
            [
                "python",
                "ml/scripts/train_classifier.py",
                "--ch-host",
                CLICKHOUSE_HOST,
                "--ch-port",
                CLICKHOUSE_PORT,
                "--ch-db",
                CLICKHOUSE_DB,
                "--mlflow-uri",
                MLFLOW_TRACKING_URI,
            ],
            cwd=AIRFLOW_PROJECT_ROOT,
        )

    @task()
    def build_ensemble() -> None:
        """Build and register the production ensemble."""
        run_command(
            [
                "python",
                "ml/scripts/ensemble.py",
                "--ch-host",
                CLICKHOUSE_HOST,
                "--ch-port",
                CLICKHOUSE_PORT,
                "--ch-db",
                CLICKHOUSE_DB,
                "--mlflow-uri",
                MLFLOW_TRACKING_URI,
            ],
            cwd=AIRFLOW_PROJECT_ROOT,
        )

    dbt_run_task = dbt_run()
    dbt_test_task = dbt_test()
    train_poisson_task = train_poisson()
    train_classifier_task = train_classifier()
    build_ensemble_task = build_ensemble()

    dbt_run_task >> dbt_test_task >> train_poisson_task >> train_classifier_task >> build_ensemble_task


retrain_model()
