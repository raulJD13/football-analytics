"""DAG: ingest_scorers

Downloads the current LaLiga top scorers table from football-data.org and
stores it in MinIO as raw/scorers/{YYYY-MM-DD}/data.parquet.
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timedelta

import pandas as pd
import requests
from airflow.decorators import dag, task
from airflow.models import Variable

from dags._datasets import RAW_SCORERS_DATASET

log = logging.getLogger(__name__)

FOOTBALL_API_BASE = "https://api.football-data.org/v4"
LALIGA_CODE = "PD"
MINIO_BUCKET = "raw"
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER", "admin")
MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD", "password123")
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_INTERNAL_PORT", "8123"))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "football")

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
}


@dag(
    dag_id="ingest_scorers",
    schedule="15 2 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["ingestion", "football-data"],
    doc_md=__doc__,
)
def ingest_scorers() -> None:

    @task()
    def fetch_scorers() -> dict:
        api_key = os.getenv("FOOTBALL_API_KEY") or Variable.get("FOOTBALL_API_KEY")
        headers = {"X-Auth-Token": api_key}
        url = f"{FOOTBALL_API_BASE}/competitions/{LALIGA_CODE}/scorers"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        log.info("Fetched %d scorers", len(payload.get("scorers", [])))
        return payload

    @task()
    def transform_scorers(payload: dict) -> list[dict]:
        season = payload.get("season", {})
        snapshot_date = datetime.utcnow().strftime("%Y-%m-%d")
        rows: list[dict] = []
        for idx, entry in enumerate(payload.get("scorers", []), start=1):
            player = entry.get("player", {})
            team = entry.get("team") or {}
            rows.append({
                "snapshot_date": snapshot_date,
                "season_start_date": season.get("startDate"),
                "season_end_date": season.get("endDate"),
                "rank": idx,
                "player_id": player.get("id"),
                "player_name": player.get("name"),
                "team_id": team.get("id"),
                "team_name": team.get("name"),
                "played_matches": entry.get("playedMatches"),
                "goals": entry.get("goals", 0),
                "assists": entry.get("assists"),
                "penalties": entry.get("penalties"),
            })
        return rows

    @task()
    def upload_to_minio(rows: list[dict]) -> None:
        import boto3
        from botocore.config import Config

        today = datetime.utcnow().strftime("%Y-%m-%d")
        object_key = f"scorers/{today}/data.parquet"
        df = pd.DataFrame(rows)
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False, engine="pyarrow")
        buffer.seek(0)

        s3 = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ROOT_USER,
            aws_secret_access_key=MINIO_ROOT_PASSWORD,
            config=Config(signature_version="s3v4"),
        )
        s3.put_object(Bucket=MINIO_BUCKET, Key=object_key, Body=buffer.getvalue())
        log.info("Uploaded %d rows to s3://%s/%s", len(df), MINIO_BUCKET, object_key)

    @task(outlets=[RAW_SCORERS_DATASET])
    def load_to_clickhouse(rows: list[dict]) -> None:
        import clickhouse_connect

        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            database=CLICKHOUSE_DB,
        )
        column_names = [
            "snapshot_date", "season_start_date", "season_end_date", "rank",
            "player_id", "player_name", "team_id", "team_name",
            "played_matches", "goals", "assists", "penalties",
        ]
        data = [[row.get(c) for c in column_names] for row in rows]
        client.insert("raw_scorers", data, column_names=column_names)
        log.info("Inserted %d rows into %s.raw_scorers", len(data), CLICKHOUSE_DB)

    raw_payload = fetch_scorers()
    scorer_rows = transform_scorers(raw_payload)
    upload_to_minio(scorer_rows)
    load_to_clickhouse(scorer_rows)


ingest_scorers()
