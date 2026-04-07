"""Shared helpers for shell-driven Airflow automation tasks."""

from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger(__name__)

AIRFLOW_PROJECT_ROOT = os.getenv("AIRFLOW_PROJECT_ROOT", "/opt/airflow")
DBT_PROJECT_DIR = os.path.join(AIRFLOW_PROJECT_ROOT, "dbt")
DBT_PROFILES_DIR = DBT_PROJECT_DIR
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = os.getenv("CLICKHOUSE_PORT", "8123")
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "football")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")


def run_command(command: list[str], *, cwd: str | None = None) -> None:
    """Run one command and raise on non-zero exit."""
    log.info("Running command: %s", " ".join(command))
    subprocess.run(command, cwd=cwd or AIRFLOW_PROJECT_ROOT, check=True)


def run_dbt_command(args: list[str]) -> None:
    """Execute dbt with the project and profiles configured for this repo."""
    run_command(
        [
            "dbt",
            *args,
            "--project-dir",
            DBT_PROJECT_DIR,
            "--profiles-dir",
            DBT_PROFILES_DIR,
        ],
        cwd=DBT_PROJECT_DIR,
    )
