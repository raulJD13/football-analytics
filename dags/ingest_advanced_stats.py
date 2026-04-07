"""DAG: ingest_advanced_stats

Fetches API-Football fixture statistics for finished LaLiga fixtures, matches
them to football-data.org match IDs, and stores them in MinIO as
raw/advanced_stats/{YYYY-MM-DD}/data.parquet.
"""

from __future__ import annotations

import io
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta

import pandas as pd
import requests
from airflow.decorators import dag, task
from airflow.models import Variable

from common.competitions import get_enabled_competitions
from dags._datasets import RAW_ADVANCED_STATS_DATASET

log = logging.getLogger(__name__)

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
MINIO_BUCKET = "raw"
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER", "admin")
MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD", "password123")
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_INTERNAL_PORT", "8123"))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "football")

DEFAULT_ARGS = {
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": True,
}


def _season_year(today: datetime) -> int:
    return today.year if today.month >= 8 else today.year - 1


def _normalize_team_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    normalized = normalized.lower()
    normalized = re.sub(
        r"\b(cf|fc|club|de|del|balompie|futbol|deportivo|rcd|rc|ud|ca|cd)\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)
    return normalized


def _team_names_match(left: str, right: str) -> bool:
    """Return True when provider name variants are close enough to match."""
    l_norm = _normalize_team_name(left)
    r_norm = _normalize_team_name(right)
    return bool(l_norm and r_norm and (l_norm == r_norm or l_norm in r_norm or r_norm in l_norm))


def _extract_stat_value(stats: list[dict], *aliases: str) -> float | None:
    alias_set = {alias.lower() for alias in aliases}
    for stat in stats:
        key = str(stat.get("type", "")).lower()
        if key not in alias_set:
            continue
        value = stat.get("value")
        if value in (None, "", "-"):
            return None
        if isinstance(value, str) and value.endswith("%"):
            value = value[:-1]
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


@dag(
    dag_id="ingest_advanced_stats",
    schedule="30 2 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["ingestion", "api-football"],
    doc_md=__doc__,
)
def ingest_advanced_stats() -> None:

    @task()
    def fetch_stats() -> list[dict]:
        import clickhouse_connect

        api_key = os.getenv("API_FOOTBALL_KEY") or Variable.get("API_FOOTBALL_KEY")
        daily_limit = int(
            os.getenv("ADVANCED_STATS_DAILY_LIMIT")
            or Variable.get("ADVANCED_STATS_DAILY_LIMIT", default_var=20)
        )
        season = _season_year(datetime.utcnow())
        headers = {"x-apisports-key": api_key}

        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            database=CLICKHOUSE_DB,
        )

        matches_df = client.query_df("""
            SELECT
                match_id,
                league_code,
                toDate(parseDateTimeBestEffort(utc_date)) AS match_date,
                home_team_id,
                away_team_id,
                home_team_name,
                away_team_name,
                toDate(season_start_date) AS season_start_date,
                status
            FROM football.raw_matches
            WHERE season_start_date LIKE '{season}%'
              AND status = 'FINISHED'
        """.format(season=season))

        existing_df = client.query_df("SELECT match_id FROM football.raw_advanced_stats")
        existing_ids = set(existing_df["match_id"].astype(int).tolist()) if not existing_df.empty else set()

        matches_by_date: dict[str, list[pd.Series]] = {}
        for _, row in matches_df.iterrows():
            matches_by_date.setdefault(
                pd.Timestamp(row["match_date"]).date().isoformat(),
                [],
            ).append(row)

        candidate_rows: list[dict] = []
        for competition in get_enabled_competitions():
            if competition.api_football_league_id is None:
                continue
            fixtures_resp = requests.get(
                f"{API_FOOTBALL_BASE}/fixtures",
                headers=headers,
                params={"league": competition.api_football_league_id, "season": season},
                timeout=30,
            )
            fixtures_resp.raise_for_status()
            fixtures = fixtures_resp.json().get("response", [])

            for fixture in fixtures:
                status = ((fixture.get("fixture") or {}).get("status") or {}).get("short")
                if status not in {"FT", "AET", "PEN"}:
                    continue
                fixture_date = str((fixture.get("fixture") or {}).get("date", ""))[:10]
                home_name = ((fixture.get("teams") or {}).get("home") or {}).get("name", "")
                away_name = ((fixture.get("teams") or {}).get("away") or {}).get("name", "")
                match_row = next(
                    (
                        row for row in matches_by_date.get(fixture_date, [])
                        if str(row["league_code"]) == competition.code
                        and _team_names_match(str(row["home_team_name"]), home_name)
                        and _team_names_match(str(row["away_team_name"]), away_name)
                    ),
                    None,
                )
                if match_row is None:
                    continue
                match_id = int(match_row["match_id"])
                if match_id in existing_ids:
                    continue
                candidate_rows.append({
                    "match_id": match_id,
                    "league_code": competition.code,
                    "api_football_fixture_id": int((fixture.get("fixture") or {}).get("id")),
                    "match_date": fixture_date,
                    "season_start_date": str(match_row["season_start_date"]),
                    "home_team_id": int(match_row["home_team_id"]),
                    "away_team_id": int(match_row["away_team_id"]),
                    "home_team_name": str(match_row["home_team_name"]),
                    "away_team_name": str(match_row["away_team_name"]),
                })

        selected = candidate_rows[:daily_limit]
        rows: list[dict] = []
        for idx, candidate in enumerate(selected, start=1):
            resp = requests.get(
                f"{API_FOOTBALL_BASE}/fixtures/statistics",
                headers=headers,
                params={"fixture": candidate["api_football_fixture_id"]},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json().get("response", [])
            if len(payload) < 2:
                continue

            home_block = next(
                (item for item in payload if ((item.get("team") or {}).get("name") or "") == candidate["home_team_name"]),
                payload[0],
            )
            away_block = next(
                (item for item in payload if ((item.get("team") or {}).get("name") or "") == candidate["away_team_name"]),
                payload[-1],
            )

            home_stats = home_block.get("statistics", [])
            away_stats = away_block.get("statistics", [])
            rows.append({
                **candidate,
                "home_shots_on_target": _extract_stat_value(home_stats, "Shots on Goal", "Shots on Target"),
                "away_shots_on_target": _extract_stat_value(away_stats, "Shots on Goal", "Shots on Target"),
                "home_total_shots": _extract_stat_value(home_stats, "Total Shots"),
                "away_total_shots": _extract_stat_value(away_stats, "Total Shots"),
                "home_possession_pct": _extract_stat_value(home_stats, "Ball Possession", "Possession"),
                "away_possession_pct": _extract_stat_value(away_stats, "Ball Possession", "Possession"),
                "home_expected_goals": _extract_stat_value(home_stats, "expected_goals", "Expected Goals", "xG"),
                "away_expected_goals": _extract_stat_value(away_stats, "expected_goals", "Expected Goals", "xG"),
            })
            if idx < len(selected):
                time.sleep(1)

        log.info("Fetched advanced stats for %d fixtures", len(rows))
        return rows

    @task()
    def upload_to_minio(rows: list[dict]) -> None:
        import boto3
        from botocore.config import Config

        if not rows:
            log.info("No advanced stats rows to upload")
            return

        today = datetime.utcnow().strftime("%Y-%m-%d")
        object_key = f"advanced_stats/{today}/data.parquet"
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

    @task(outlets=[RAW_ADVANCED_STATS_DATASET])
    def load_to_clickhouse(rows: list[dict]) -> None:
        import clickhouse_connect

        if not rows:
            log.info("No advanced stats rows to insert")
            return

        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            database=CLICKHOUSE_DB,
        )
        column_names = [
            "match_id", "league_code", "api_football_fixture_id", "match_date", "season_start_date",
            "home_team_id", "away_team_id", "home_team_name", "away_team_name",
            "home_shots_on_target", "away_shots_on_target",
            "home_total_shots", "away_total_shots",
            "home_possession_pct", "away_possession_pct",
            "home_expected_goals", "away_expected_goals",
        ]
        data = [[row.get(c) for c in column_names] for row in rows]
        client.insert("raw_advanced_stats", data, column_names=column_names)
        log.info("Inserted %d rows into %s.raw_advanced_stats", len(data), CLICKHOUSE_DB)

    advanced_rows = fetch_stats()
    upload_to_minio(advanced_rows)
    load_to_clickhouse(advanced_rows)


ingest_advanced_stats()
