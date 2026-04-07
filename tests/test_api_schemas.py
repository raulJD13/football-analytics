from __future__ import annotations

import datetime as dt

import pytest

from api.schemas.predict import PredictRequest, PredictResponse
from api.schemas.standings import StandingEntry
from api.schemas.teams import FormMatch


def test_predict_request_rejects_same_team_ids() -> None:
    with pytest.raises(ValueError):
        PredictRequest(home_team_id=86, away_team_id=86)


def test_predict_response_accepts_probability_payload() -> None:
    response = PredictResponse(
        home_team_id=86,
        away_team_id=81,
        home_win=0.48,
        draw=0.26,
        away_win=0.26,
        expected_home_goals=1.8,
        expected_away_goals=1.1,
        model_version="ensemble-v2",
    )
    assert response.home_win + response.draw + response.away_win == pytest.approx(1.0)


def test_standing_entry_requires_form_string() -> None:
    entry = StandingEntry(
        position=1,
        team_id=86,
        team_name="Real Madrid CF",
        played=30,
        won=20,
        drawn=5,
        lost=5,
        goals_for=60,
        goals_against=25,
        goal_difference=35,
        points=65,
        form_last_5="WWDLW",
        projected_points=82,
    )
    assert entry.form_last_5 == "WWDLW"


def test_form_match_serializes_date() -> None:
    match = FormMatch(
        match_id=1,
        match_date=dt.date(2026, 4, 7),
        is_home=True,
        opponent_team_id=81,
        team_goals=2,
        opponent_goals=1,
        outcome="W",
        points=3,
    )
    assert match.match_date == dt.date(2026, 4, 7)
