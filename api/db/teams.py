"""ClickHouse queries for the teams router."""

from __future__ import annotations

import clickhouse_connect.driver


def fetch_team_stats(client: clickhouse_connect.driver.Client, team_id: int) -> dict | None:
    """Return combined home/away stats for a single team, or None if not found."""
    rows = client.query("""
        SELECT
            ts.team_id,
            s.team_name,
            ts.home_played,
            ts.home_won,
            ts.home_draw,
            ts.home_lost,
            ts.home_points,
            ts.home_goals_for,
            ts.home_goals_against,
            ts.home_avg_goals_scored,
            ts.home_avg_goals_conceded,
            ts.home_avg_points_per_game,
            ts.away_played,
            ts.away_won,
            ts.away_draw,
            ts.away_lost,
            ts.away_points,
            ts.away_goals_for,
            ts.away_goals_against,
            ts.away_avg_goals_scored,
            ts.away_avg_goals_conceded,
            ts.away_avg_points_per_game,
            ts.home_attack_strength,
            ts.away_defence_weakness
        FROM football.mart_team_stats ts
        LEFT JOIN football.mart_standings s ON ts.team_id = s.team_id
        WHERE ts.team_id = {team_id:UInt32}
    """, parameters={"team_id": team_id}).result_rows

    if not rows:
        return None

    row = rows[0]
    (team_id_, team_name,
     h_played, h_won, h_draw, h_lost, h_pts, h_gf, h_ga,
     h_avg_scored, h_avg_conceded, h_ppg,
     a_played, a_won, a_draw, a_lost, a_pts, a_gf, a_ga,
     a_avg_scored, a_avg_conceded, a_ppg,
     attack_strength, defence_weakness) = row

    # Clean sheets and defensive variance (from match features)
    cs_rows = client.query("""
        SELECT
            countIf(home_team_id = {team_id:UInt32} AND away_goals = 0)  AS home_cs,
            countIf(away_team_id = {team_id:UInt32} AND home_goals = 0)  AS away_cs,
            varPopIf(toFloat64(away_goals), home_team_id = {team_id:UInt32} AND away_goals IS NOT NULL) AS home_def_var,
            varPopIf(toFloat64(home_goals), away_team_id = {team_id:UInt32} AND home_goals IS NOT NULL) AS away_def_var
        FROM football.mart_match_features
        WHERE result IN ('H', 'D', 'A')
          AND (home_team_id = {team_id:UInt32} OR away_team_id = {team_id:UInt32})
    """, parameters={"team_id": team_id}).result_rows[0]

    home_cs, away_cs, home_def_var, away_def_var = cs_rows

    return {
        "team_id": team_id_,
        "team_name": team_name or f"Team {team_id_}",
        "home_attack_strength": attack_strength,
        "away_defence_weakness": defence_weakness,
        "home": {
            "played": h_played,
            "won": h_won,
            "drawn": h_draw,
            "lost": h_lost,
            "points": h_pts,
            "goals_for": h_gf,
            "goals_against": h_ga,
            "avg_goals_scored": h_avg_scored,
            "avg_goals_conceded": h_avg_conceded,
            "points_per_game": h_ppg,
            "clean_sheets": int(home_cs),
            "defensive_variance": float(home_def_var) if home_def_var is not None else None,
        },
        "away": {
            "played": a_played,
            "won": a_won,
            "drawn": a_draw,
            "lost": a_lost,
            "points": a_pts,
            "goals_for": a_gf,
            "goals_against": a_ga,
            "avg_goals_scored": a_avg_scored,
            "avg_goals_conceded": a_avg_conceded,
            "points_per_game": a_ppg,
            "clean_sheets": int(away_cs),
            "defensive_variance": float(away_def_var) if away_def_var is not None else None,
        },
    }


def fetch_team_form(
    client: clickhouse_connect.driver.Client, team_id: int, n: int = 10
) -> list[dict]:
    """Return the last n finished matches for team_id, most recent first."""
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
        WHERE (home_team_id = {team_id:UInt32} OR away_team_id = {team_id:UInt32})
          AND result IN ('H', 'D', 'A')
        ORDER BY match_date DESC
        LIMIT {n:UInt32}
    """, parameters={"team_id": team_id, "n": n}).result_rows

    matches = []
    for match_id, match_date, home_id, away_id, hg, ag, result in rows:
        is_home = (home_id == team_id)
        team_goals = hg if is_home else ag
        opp_goals = ag if is_home else hg
        opponent_id = away_id if is_home else home_id

        if result == "D":
            outcome, pts = "D", 1
        elif (result == "H" and is_home) or (result == "A" and not is_home):
            outcome, pts = "W", 3
        else:
            outcome, pts = "L", 0

        matches.append({
            "match_id": match_id,
            "match_date": match_date,
            "is_home": is_home,
            "opponent_team_id": opponent_id,
            "team_goals": team_goals,
            "opponent_goals": opp_goals,
            "outcome": outcome,
            "points": pts,
        })
    return matches
