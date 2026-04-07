"""Queries for fixtures, match detail, and xG series."""

from __future__ import annotations

import datetime

import clickhouse_connect.driver


def fetch_fixtures(
    client: clickhouse_connect.driver.Client,
    season_start_year: int | None = None,
    limit: int = 12,
) -> list[dict]:
    """Return current-season fixtures around the current date."""
    if season_start_year is None:
        today = datetime.date.today()
        season_start_year = today.year if today.month >= 8 else today.year - 1

    rows = client.query("""
        SELECT
            match_id,
            toDate(parseDateTimeBestEffort(utc_date)) AS match_date,
            status,
            matchday,
            home_team_id,
            home_team_name,
            away_team_id,
            away_team_name,
            home_score_full,
            away_score_full
        FROM football.raw_matches
        WHERE toDate(season_start_date) >= toDate({season_start:String})
          AND toDate(season_start_date) < addYears(toDate({season_start:String}), 1)
        ORDER BY abs(dateDiff('day', toDate(parseDateTimeBestEffort(utc_date)), today())), utc_date
        LIMIT {limit:UInt32}
    """, parameters={
        "season_start": f"{season_start_year}-08-01",
        "limit": limit,
    }).result_rows

    return [
        {
            "match_id": match_id,
            "match_date": match_date,
            "status": status,
            "matchday": matchday,
            "home_team_id": home_team_id,
            "home_team_name": home_team_name,
            "away_team_id": away_team_id,
            "away_team_name": away_team_name,
            "home_goals": home_goals,
            "away_goals": away_goals,
        }
        for (
            match_id,
            match_date,
            status,
            matchday,
            home_team_id,
            home_team_name,
            away_team_id,
            away_team_name,
            home_goals,
            away_goals,
        ) in rows
    ]


def fetch_fixture_detail(
    client: clickhouse_connect.driver.Client,
    match_id: int,
) -> dict | None:
    """Return one raw fixture row by match_id."""
    rows = client.query("""
        SELECT
            match_id,
            toDate(parseDateTimeBestEffort(utc_date)) AS match_date,
            status,
            matchday,
            home_team_id,
            home_team_name,
            away_team_id,
            away_team_name,
            home_score_full,
            away_score_full
        FROM football.raw_matches
        WHERE match_id = {match_id:UInt32}
        LIMIT 1
    """, parameters={"match_id": match_id}).result_rows
    if not rows:
        return None
    row = rows[0]
    return {
        "match_id": row[0],
        "match_date": row[1],
        "status": row[2],
        "matchday": row[3],
        "home_team_id": row[4],
        "home_team_name": row[5],
        "away_team_id": row[6],
        "away_team_name": row[7],
        "home_goals": row[8],
        "away_goals": row[9],
    }


def fetch_head_to_head(
    client: clickhouse_connect.driver.Client,
    home_team_id: int,
    away_team_id: int,
    limit: int = 5,
) -> list[dict]:
    """Return latest direct meetings between two teams."""
    rows = client.query("""
        SELECT
            match_id,
            match_date,
            home_team_id,
            away_team_id,
            home_goals,
            away_goals,
            result
        FROM football.mart_match_features
        WHERE (home_team_id = {home:UInt32} AND away_team_id = {away:UInt32})
           OR (home_team_id = {away:UInt32} AND away_team_id = {home:UInt32})
        ORDER BY match_date DESC
        LIMIT {limit:UInt32}
    """, parameters={"home": home_team_id, "away": away_team_id, "limit": limit}).result_rows

    if not rows:
        return []

    team_names = client.query("""
        SELECT team_id, team_name
        FROM football.stg_teams
        WHERE team_id IN ({home:UInt32}, {away:UInt32})
    """, parameters={"home": home_team_id, "away": away_team_id}).result_rows
    name_map = {team_id: name for team_id, name in team_names}

    return [
        {
            "match_id": match_id,
            "match_date": match_date,
            "home_team_name": name_map.get(home_id, str(home_id)),
            "away_team_name": name_map.get(away_id, str(away_id)),
            "home_goals": home_goals,
            "away_goals": away_goals,
            "result": result,
        }
        for match_id, match_date, home_id, away_id, home_goals, away_goals, result in rows
    ]


def fetch_team_xg_series(
    client: clickhouse_connect.driver.Client,
    team_id: int,
) -> list[dict]:
    """Return cumulative xG time series for one team."""
    rows = client.query("""
        SELECT
            match_id,
            match_date,
            opponent_team_id,
            is_home,
            expected_goals_for,
            expected_goals_against,
            sum(expected_goals_for) over (
                partition by team_id
                order by match_date, match_id
                rows between unbounded preceding and current row
            ) AS cumulative_expected_goals_for,
            sum(expected_goals_against) over (
                partition by team_id
                order by match_date, match_id
                rows between unbounded preceding and current row
            ) AS cumulative_expected_goals_against
        FROM (
            SELECT
                match_id,
                match_date,
                home_team_id AS team_id,
                away_team_id AS opponent_team_id,
                1 AS is_home,
                coalesce(home_expected_goals, 0.0) AS expected_goals_for,
                coalesce(away_expected_goals, 0.0) AS expected_goals_against
            FROM football.stg_advanced_stats
            UNION ALL
            SELECT
                match_id,
                match_date,
                away_team_id AS team_id,
                home_team_id AS opponent_team_id,
                0 AS is_home,
                coalesce(away_expected_goals, 0.0) AS expected_goals_for,
                coalesce(home_expected_goals, 0.0) AS expected_goals_against
            FROM football.stg_advanced_stats
        )
        WHERE team_id = {team_id:UInt32}
        ORDER BY match_date, match_id
    """, parameters={"team_id": team_id}).result_rows

    return [
        {
            "match_id": match_id,
            "match_date": match_date,
            "opponent_team_id": opponent_team_id,
            "is_home": bool(is_home),
            "expected_goals_for": float(xgf),
            "expected_goals_against": float(xga),
            "cumulative_expected_goals_for": float(cum_xgf),
            "cumulative_expected_goals_against": float(cum_xga),
        }
        for (
            match_id,
            match_date,
            opponent_team_id,
            is_home,
            xgf,
            xga,
            cum_xgf,
            cum_xga,
        ) in rows
    ]
