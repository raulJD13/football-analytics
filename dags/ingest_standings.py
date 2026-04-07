"""DAG: ingest_standings

Downloads the current LaLiga standings from football-data.org and stores them
in MinIO as raw/standings/{YYYY-MM-DD}/data.parquet.
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
    dag_id="ingest_standings",
    schedule="0 2 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["ingestion", "football-data"],
    doc_md=__doc__,
)
def ingest_standings() -> None:

    @task()
    def fetch_standings() -> list[dict]:
        """Fetch LaLiga standings table from football-data.org."""
        api_key = os.getenv("FOOTBALL_API_KEY") or Variable.get("FOOTBALL_API_KEY")
        headers = {"X-Auth-Token": api_key}

        url = f"{FOOTBALL_API_BASE}/competitions/{LALIGA_CODE}/standings"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()

        # The API returns standings grouped by type (TOTAL, HOME, AWAY).
        # We keep the TOTAL table.
        standings_groups = payload.get("standings", [])
        total_table = next(
            (g["table"] for g in standings_groups if g["type"] == "TOTAL"), []
        )
        season = payload.get("season", {})
        log.info("Fetched standings with %d teams", len(total_table))
        return [{
            "table": total_table,
            "season_start_date": season.get("startDate"),
            "season_end_date": season.get("endDate"),
        }]

    @task()
    def transform_standings(payloads: list[dict]) -> list[dict]:
        """Flatten the standings table into a flat row per team."""
        payload = payloads[0]
        table = payload["table"]
        snapshot_date = datetime.utcnow().strftime("%Y-%m-%d")
        rows = []
        for entry in table:
            team = entry.get("team", {})
            rows.append(
                {
                    "position": entry["position"],
                    "team_id": team["id"],
                    "team_name": team["name"],
                    "team_short_name": team.get("shortName"),
                    "played_games": entry["playedGames"],
                    "won": entry["won"],
                    "draw": entry["draw"],
                    "lost": entry["lost"],
                    "points": entry["points"],
                    "goals_for": entry["goalsFor"],
                    "goals_against": entry["goalsAgainst"],
                    "goal_difference": entry["goalDifference"],
                    "form": entry.get("form"),
                    "season_start_date": payload["season_start_date"],
                    "season_end_date": payload["season_end_date"],
                    "snapshot_date": snapshot_date,
                }
            )
        log.info("Transformed standings for %d teams", len(rows))
        return rows

    @task()
    def upload_to_minio(rows: list[dict]) -> None:
        """Write rows as Parquet to MinIO at raw/standings/{date}/data.parquet."""
        import boto3
        from botocore.config import Config

        today = datetime.utcnow().strftime("%Y-%m-%d")
        object_key = f"standings/{today}/data.parquet"

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
        """Insert rows into football.raw_standings (ClickHouse).

        snapshot_date defaults to today() in the table definition so each daily
        run produces a new versioned snapshot. ReplacingMergeTree deduplicates
        by (team_id, snapshot_date) during merges.
        """
        import clickhouse_connect

        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            database=CLICKHOUSE_DB,
        )
        column_names = [
            "position", "team_id", "team_name", "team_short_name",
            "played_games", "won", "draw", "lost", "points",
            "goals_for", "goals_against", "goal_difference", "form",
            "season_start_date", "season_end_date", "snapshot_date",
        ]
        data = [[row.get(c) for c in column_names] for row in rows]
        client.insert("raw_standings", data, column_names=column_names)
        log.info("Inserted %d rows into %s.raw_standings", len(data), CLICKHOUSE_DB)

    standings_raw = fetch_standings()
    standings_flat = transform_standings(standings_raw)
    upload_to_minio(standings_flat)
    load_to_clickhouse(standings_flat)


ingest_standings()
