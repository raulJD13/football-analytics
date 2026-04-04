"""bootstrap_clickhouse.py

One-time dev script to load LaLiga data from football-data.org directly into
the ClickHouse raw tables, bypassing Airflow.  Run this after `docker compose
up -d clickhouse` to seed the database before running `dbt run`.

Usage:
    python scripts/bootstrap_clickhouse.py [--host localhost] [--port 8124]

The script reads FOOTBALL_API_KEY and ClickHouse credentials from environment
variables (or the .env file if python-dotenv is installed).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import clickhouse_connect
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

FOOTBALL_API_BASE = "https://api.football-data.org/v4"
LALIGA_CODE = "PD"


# ── helpers ───────────────────────────────────────────────────────────────────

def _api_get(path: str, api_key: str) -> dict:
    """GET a football-data.org endpoint, respecting the 10 req/min rate limit."""
    url = f"{FOOTBALL_API_BASE}{path}"
    resp = requests.get(url, headers={"X-Auth-Token": api_key}, timeout=30)
    if resp.status_code == 429:
        log.warning("Rate limited — sleeping 60 s")
        time.sleep(60)
        resp = requests.get(url, headers={"X-Auth-Token": api_key}, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── data fetchers / transformers ──────────────────────────────────────────────

def fetch_matches(api_key: str) -> list[list]:
    """Return rows for raw_matches."""
    data = _api_get(f"/competitions/{LALIGA_CODE}/matches", api_key)
    matches = data.get("matches", [])
    rows = []
    for m in matches:
        rows.append([
            m["id"],
            m["utcDate"],
            m["status"],
            m.get("matchday"),
            m.get("stage"),
            m["homeTeam"]["id"],
            m["homeTeam"]["name"],
            m["awayTeam"]["id"],
            m["awayTeam"]["name"],
            (m["score"]["fullTime"] or {}).get("home"),
            (m["score"]["fullTime"] or {}).get("away"),
            (m["score"]["halfTime"] or {}).get("home"),
            (m["score"]["halfTime"] or {}).get("away"),
            m["score"].get("winner"),
            m["season"]["startDate"],
            m["season"]["endDate"],
        ])
    log.info("Fetched %d matches", len(rows))
    return rows


MATCHES_COLUMNS = [
    "match_id", "utc_date", "status", "matchday", "stage",
    "home_team_id", "home_team_name", "away_team_id", "away_team_name",
    "home_score_full", "away_score_full", "home_score_half", "away_score_half",
    "winner", "season_start_date", "season_end_date",
]


def fetch_standings(api_key: str) -> list[list]:
    """Return rows for raw_standings (TOTAL table only)."""
    data = _api_get(f"/competitions/{LALIGA_CODE}/standings", api_key)
    groups = data.get("standings", [])
    table = next((g["table"] for g in groups if g["type"] == "TOTAL"), [])
    rows = []
    for entry in table:
        team = entry.get("team", {})
        rows.append([
            entry["position"],
            team["id"],
            team["name"],
            team.get("shortName"),
            entry["playedGames"],
            entry["won"],
            entry["draw"],
            entry["lost"],
            entry["points"],
            entry["goalsFor"],
            entry["goalsAgainst"],
            entry["goalDifference"],
            entry.get("form"),
        ])
    log.info("Fetched standings for %d teams", len(rows))
    return rows


STANDINGS_COLUMNS = [
    "position", "team_id", "team_name", "team_short_name",
    "played_games", "won", "draw", "lost", "points",
    "goals_for", "goals_against", "goal_difference", "form",
]


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Try to load .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Bootstrap ClickHouse raw tables.")
    # CLICKHOUSE_HOST in .env is the Docker service name — use localhost for host scripts
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=int(os.getenv("CLICKHOUSE_PORT", "8124")))
    parser.add_argument("--db", default=os.getenv("CLICKHOUSE_DB", "football"))
    args = parser.parse_args()

    api_key = os.getenv("FOOTBALL_API_KEY")
    if not api_key:
        log.error("FOOTBALL_API_KEY environment variable is not set.")
        sys.exit(1)

    log.info("Connecting to ClickHouse at %s:%d/%s", args.host, args.port, args.db)
    client = clickhouse_connect.get_client(
        host=args.host, port=args.port, database=args.db
    )
    # Verify connection
    client.ping()
    log.info("ClickHouse connection OK")

    # ── matches ───────────────────────────────────────────────────────────────
    match_rows = fetch_matches(api_key)
    client.insert("raw_matches", match_rows, column_names=MATCHES_COLUMNS)
    log.info("Inserted %d rows into raw_matches", len(match_rows))

    # Respect free-tier rate limit (10 req/min) before second call
    log.info("Sleeping 7 s to respect API rate limit …")
    time.sleep(7)

    # ── standings ─────────────────────────────────────────────────────────────
    standing_rows = fetch_standings(api_key)
    client.insert("raw_standings", standing_rows, column_names=STANDINGS_COLUMNS)
    log.info("Inserted %d rows into raw_standings", len(standing_rows))

    log.info("Bootstrap complete. Run `make dbt-run && make dbt-test`.")


if __name__ == "__main__":
    main()
