"""Live feature assembly for XGBoost prediction endpoint.

Queries ClickHouse to build a one-row DataFrame with the same features
used during XGBoost training (see ml/scripts/train_classifier.py).

Feature list and constants are imported from train_classifier to ensure
they stay in sync with training.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pandas as pd
import clickhouse_connect.driver

# Resolve project root so ml.scripts imports work in all execution contexts
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ml.scripts.train_classifier import FEATURES, MAX_REST_DAYS  # noqa: E402

# Defaults when data is missing (mirrors dbt coalesce values)
_DEFAULT_H2H_WIN_RATE = 0.45
_DEFAULT_ATTACK       = 1.0
_DEFAULT_DEFENCE      = 1.0


def fetch_prediction_features(
    client: clickhouse_connect.driver.Client,
    home_team_id: int,
    away_team_id: int,
) -> pd.DataFrame:
    """Return a one-row DataFrame with all XGBoost features for a fixture.

    Features are assembled from current database state:
      - form: from each team's most recent match row in mart_match_features
      - attack/defence strengths: from mart_team_stats
      - H2H: from historical mart_match_features for this (home, away) pair
      - rest days: days since each team's last match, capped at MAX_REST_DAYS
      - position_diff: from mart_standings

    Missing data (no H2H, new team, etc.) falls back to neutral defaults so
    predictions never hard-fail.
    """
    today = datetime.date.today()

    # ── 1. Attack / defence strengths ────────────────────────────────────────
    stats = client.query_df("""
        SELECT
            team_id,
            home_attack_strength,
            away_defence_weakness
        FROM football.mart_team_stats
        WHERE team_id IN ({home}, {away})
    """.format(home=home_team_id, away=away_team_id))

    def _stat(team_id: int, col: str, default: float) -> float:
        row = stats[stats["team_id"] == team_id]
        if row.empty or pd.isna(row.iloc[0][col]):
            return default
        return float(row.iloc[0][col])

    home_attack   = _stat(home_team_id, "home_attack_strength",  _DEFAULT_ATTACK)
    away_defence  = _stat(away_team_id, "away_defence_weakness", _DEFAULT_DEFENCE)

    # ── 2. Current form (points from last 5 matches) ──────────────────────────
    # Use the form columns of the most recent row in mart_match_features for
    # each team.  home_form_5 / away_form_5 record points *going into* that
    # match, so the latest row holds the most current form.
    def _team_form(team_id: int) -> tuple[float, float]:
        """Return (form_points, form_n) from most recent match for team."""
        row_df = client.query_df("""
            SELECT
                multiIf(home_team_id = {tid}, home_form_5,
                        away_team_id = {tid}, away_form_5,
                        0)                              AS form_pts,
                multiIf(home_team_id = {tid}, home_form_matches_available,
                        away_team_id = {tid}, away_form_matches_available,
                        0)                              AS form_n
            FROM football.mart_match_features
            WHERE home_team_id = {tid} OR away_team_id = {tid}
            ORDER BY match_date DESC
            LIMIT 1
        """.format(tid=team_id))
        if row_df.empty:
            return 0.0, 0.0
        return float(row_df.iloc[0]["form_pts"]), float(row_df.iloc[0]["form_n"])

    home_form_pts, home_form_n = _team_form(home_team_id)
    away_form_pts, away_form_n = _team_form(away_team_id)

    home_form_ppg = home_form_pts / max(home_form_n, 1)
    away_form_ppg = away_form_pts / max(away_form_n, 1)

    # ── 3. H2H (this exact (home, away) pair only) ────────────────────────────
    h2h_df = client.query_df("""
        SELECT
            countIf(result = 'H') / count()  AS h2h_home_win_rate,
            count()                           AS h2h_matches_played
        FROM football.mart_match_features
        WHERE home_team_id = {home}
          AND away_team_id = {away}
          AND result IN ('H', 'D', 'A')
    """.format(home=home_team_id, away=away_team_id))

    if h2h_df.empty or int(h2h_df.iloc[0]["h2h_matches_played"]) == 0:
        h2h_rate    = _DEFAULT_H2H_WIN_RATE
        h2h_matches = 0.0
    else:
        h2h_rate    = float(h2h_df.iloc[0]["h2h_home_win_rate"])
        h2h_matches = float(h2h_df.iloc[0]["h2h_matches_played"])

    # ── 4. Rest days ──────────────────────────────────────────────────────────
    def _rest_days(team_id: int) -> float:
        """Days since last match, capped at MAX_REST_DAYS."""
        row_df = client.query_df("""
            SELECT max(match_date) AS last_match
            FROM football.mart_match_features
            WHERE home_team_id = {tid} OR away_team_id = {tid}
        """.format(tid=team_id))
        if row_df.empty or pd.isna(row_df.iloc[0]["last_match"]):
            return float(MAX_REST_DAYS)
        last = pd.Timestamp(row_df.iloc[0]["last_match"]).date()
        days = (today - last).days
        return float(min(days, MAX_REST_DAYS))

    home_rest = _rest_days(home_team_id)
    away_rest = _rest_days(away_team_id)

    # ── 5. Standings position ─────────────────────────────────────────────────
    pos_df = client.query_df("""
        SELECT team_id, position
        FROM football.mart_standings
        WHERE team_id IN ({home}, {away})
    """.format(home=home_team_id, away=away_team_id))

    def _position(team_id: int) -> int:
        row = pos_df[pos_df["team_id"] == team_id]
        return int(row.iloc[0]["position"]) if not row.empty else 10

    home_pos = _position(home_team_id)
    away_pos = _position(away_team_id)
    position_diff = home_pos - away_pos

    # ── assemble in the exact column order expected by XGBClassifier ─────────
    row: dict[str, float] = {
        "home_form_5_ppg":       home_form_ppg,
        "away_form_5_ppg":       away_form_ppg,
        "home_attack_strength":  home_attack,
        "away_defence_weakness": away_defence,
        "h2h_home_win_rate":     h2h_rate,
        "home_rest_days":        home_rest,
        "away_rest_days":        away_rest,
        "rest_days_diff":        home_rest - away_rest,
        "position_diff":         float(position_diff),
        "h2h_matches_played":    h2h_matches,
    }
    # Return DataFrame with columns in the same order as FEATURES
    return pd.DataFrame([row])[FEATURES]
