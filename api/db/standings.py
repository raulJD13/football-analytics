"""ClickHouse queries for the standings router."""

from __future__ import annotations

import clickhouse_connect.driver


_TOTAL_MATCHDAYS = 38  # LaLiga season length


def fetch_standings(client: clickhouse_connect.driver.Client) -> list[dict]:
    """Return mart_standings rows ordered by position, with projected_points added."""
    rows = client.query("""
        SELECT
            position,
            team_id,
            team_name,
            played_games,
            won,
            draw,
            lost,
            goals_for,
            goals_against,
            goal_difference,
            points
        FROM football.mart_standings
        ORDER BY position
    """).result_rows

    results = []
    for row in rows:
        (position, team_id, team_name, played, won, draw, lost,
         gf, ga, gd, points) = row
        projected = (
            round(points / played * _TOTAL_MATCHDAYS) if played > 0 else 0
        )
        results.append({
            "position": position,
            "team_id": team_id,
            "team_name": team_name,
            "played": played,
            "won": won,
            "drawn": draw,
            "lost": lost,
            "goals_for": gf,
            "goals_against": ga,
            "goal_difference": gd,
            "points": points,
            "projected_points": projected,
        })
    return results


def fetch_form_strings(client: clickhouse_connect.driver.Client, n: int = 5) -> dict[int, str]:
    """Return a dict mapping team_id → last-n form string (e.g. 'WWDLW').

    Fetches recent finished matches and computes form per team in Python.
    """
    # Fetch enough recent matches to guarantee n per team (20 teams × n + buffer)
    limit = 20 * n + 50
    rows = client.query(f"""
        SELECT match_id, match_date, home_team_id, away_team_id, result
        FROM football.mart_match_features
        WHERE result IN ('H', 'D', 'A')
        ORDER BY match_date DESC
        LIMIT {limit}
    """).result_rows

    # Build per-team ordered list (most recent first) of outcomes
    team_matches: dict[int, list[str]] = {}
    for _, _, home_id, away_id, result in rows:
        for team_id, outcome in [
            (home_id, "W" if result == "H" else ("D" if result == "D" else "L")),
            (away_id, "W" if result == "A" else ("D" if result == "D" else "L")),
        ]:
            team_matches.setdefault(team_id, [])
            if len(team_matches[team_id]) < n:
                team_matches[team_id].append(outcome)

    # Reverse so the string reads oldest → newest (conventional display)
    return {tid: "".join(reversed(outcomes)) for tid, outcomes in team_matches.items()}
