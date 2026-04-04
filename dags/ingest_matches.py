"""DAG: ingest_matches

Downloads LaLiga match data from football-data.org and stores it in MinIO
as raw/matches/{YYYY-MM-DD}/data.parquet.
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
    dag_id="ingest_matches",
    schedule="0 2 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["ingestion", "football-data"],
    doc_md=__doc__,
)
def ingest_matches() -> None:

    @task()
    def fetch_matches() -> list[dict]:
        """Fetch all LaLiga matches for the current season from football-data.org."""
        api_key = os.getenv("FOOTBALL_API_KEY") or Variable.get("FOOTBALL_API_KEY")
        headers = {"X-Auth-Token": api_key}

        url = f"{FOOTBALL_API_BASE}/competitions/{LALIGA_CODE}/matches"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        matches = response.json().get("matches", [])
        log.info("Fetched %d matches from football-data.org", len(matches))
        return matches

    @task()
    def transform_matches(matches: list[dict]) -> list[dict]:
        """Flatten nested match payload into a tabular structure."""
        rows = []
        for m in matches:
            rows.append(
                {
                    "match_id": m["id"],
                    "utc_date": m["utcDate"],
                    "status": m["status"],
                    "matchday": m.get("matchday"),
                    "stage": m.get("stage"),
                    "home_team_id": m["homeTeam"]["id"],
                    "home_team_name": m["homeTeam"]["name"],
                    "away_team_id": m["awayTeam"]["id"],
                    "away_team_name": m["awayTeam"]["name"],
                    "home_score_full": (m["score"]["fullTime"] or {}).get("home"),
                    "away_score_full": (m["score"]["fullTime"] or {}).get("away"),
                    "home_score_half": (m["score"]["halfTime"] or {}).get("home"),
                    "away_score_half": (m["score"]["halfTime"] or {}).get("away"),
                    "winner": (m["score"].get("winner")),
                    "season_start_date": m["season"]["startDate"],
                    "season_end_date": m["season"]["endDate"],
                }
            )
        log.info("Transformed %d match records", len(rows))
        return rows

    @task()
    def upload_to_minio(rows: list[dict]) -> None:
        """Write rows as Parquet to MinIO at raw/matches/{date}/data.parquet."""
        import boto3
        from botocore.config import Config

        today = datetime.utcnow().strftime("%Y-%m-%d")
        object_key = f"matches/{today}/data.parquet"

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
        log.info(
            "Uploaded %d rows to s3://%s/%s", len(df), MINIO_BUCKET, object_key
        )

    @task()
    def load_to_clickhouse(rows: list[dict]) -> None:
        """Insert rows into football.raw_matches (ClickHouse).

        Uses ReplacingMergeTree so re-runs are idempotent: duplicate match_ids
        are deduplicated during the next ClickHouse merge.
        """
        import clickhouse_connect

        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            database=CLICKHOUSE_DB,
        )
        column_names = [
            "match_id", "utc_date", "status", "matchday", "stage",
            "home_team_id", "home_team_name", "away_team_id", "away_team_name",
            "home_score_full", "away_score_full", "home_score_half", "away_score_half",
            "winner", "season_start_date", "season_end_date",
        ]
        data = [[row.get(c) for c in column_names] for row in rows]
        client.insert("raw_matches", data, column_names=column_names)
        log.info("Inserted %d rows into %s.raw_matches", len(data), CLICKHOUSE_DB)

    matches_raw = fetch_matches()
    matches_flat = transform_matches(matches_raw)
    upload_to_minio(matches_flat)
    load_to_clickhouse(matches_flat)


ingest_matches()
